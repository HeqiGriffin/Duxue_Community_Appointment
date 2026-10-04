"""预约接口：自然语言提交、AI 三级审核、管理员审批、原子占房与动态时长。"""
from __future__ import annotations

import json
from io import BytesIO
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import require_admin, require_normal_account, require_password_changed
from config import SessionLocal, get_db
from core.ai_prompt import AIAuditResult, ROOM_CODES, audit_booking_with_ai
from models.bookings import AuditSource, Booking, BookingSlotLock, BookingStatus
from models.users import User
from utils.time_calc import APP_TZ, duration_minutes, ensure_local, iter_half_hour_slots

router = APIRouter(prefix="/bookings", tags=["booking"])

ACTIVE_QUOTA_STATUSES = {
    BookingStatus.APPROVED,
    BookingStatus.ACTIVE,
    BookingStatus.AWAITING_CLEANUP,
    BookingStatus.COMPLETED,
}
CANCELLABLE_STATUSES = {
    BookingStatus.PENDING_AI,
    BookingStatus.PENDING_MANUAL,
    BookingStatus.APPROVED,
}


class BookingCreateRequest(BaseModel):
    start_time: datetime
    end_time: datetime
    people_count: int = Field(default=1, ge=1, le=500)
    purpose: str = Field(min_length=2, max_length=1000)


class AdminReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    room_code: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=2000)


class SuperBookingRequest(BaseModel):
    user_id: int
    room_code: str = Field(min_length=1, max_length=32)
    start_time: datetime
    end_time: datetime
    people_count: int = Field(default=1, ge=1, le=500)
    purpose: str = Field(min_length=2, max_length=1000)


class BookingResponse(BaseModel):
    id: int
    user_id: int
    purpose: str
    people_count: int
    intent_type: str | None
    candidate_rooms: list[str]
    room_code: str | None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    daily_limit_minutes: int | None
    single_limit_minutes: int | None
    status: BookingStatus
    ai_decision: str | None
    ai_reason: str | None
    ai_guidance: str | None
    ai_confidence: int | None
    audit_source: AuditSource | None
    rejection_reason: str | None
    checked_in_at: datetime | None
    checked_out_at: datetime | None
    cleanup_deadline_at: datetime | None
    cleanup_review_status: str | None
    is_violation: bool
    violation_reason: str | None
    created_at: datetime


class BookingListResponse(BaseModel):
    items: list[BookingResponse]
    total: int


def _candidate_rooms(booking: Booking) -> list[str]:
    if booking.candidate_rooms_json:
        try:
            value = json.loads(booking.candidate_rooms_json)
            if isinstance(value, list):
                rooms = [str(x).upper() for x in value if str(x).upper() in ROOM_CODES]
                if rooms:
                    return list(dict.fromkeys(rooms))
        except json.JSONDecodeError:
            pass
    return list(ROOM_CODES)


def _serialize(booking: Booking) -> BookingResponse:
    try:
        minutes = duration_minutes(booking.start_time, booking.end_time)
    except ValueError:
        minutes = int((booking.end_time - booking.start_time).total_seconds() // 60)
    return BookingResponse(
        id=booking.id,
        user_id=booking.user_id,
        purpose=booking.purpose,
        people_count=booking.people_count,
        intent_type=booking.intent_type,
        candidate_rooms=_candidate_rooms(booking),
        room_code=booking.room_code,
        start_time=booking.start_time,
        end_time=booking.end_time,
        duration_minutes=minutes,
        daily_limit_minutes=booking.daily_limit_minutes,
        single_limit_minutes=booking.single_limit_minutes,
        status=booking.status,
        ai_decision=booking.ai_decision,
        ai_reason=booking.ai_reason,
        ai_guidance=booking.ai_guidance,
        ai_confidence=booking.ai_confidence,
        audit_source=booking.audit_source,
        rejection_reason=booking.rejection_reason,
        checked_in_at=booking.checked_in_at,
        checked_out_at=booking.checked_out_at,
        cleanup_deadline_at=booking.cleanup_deadline_at,
        cleanup_review_status=booking.cleanup_review_status,
        is_violation=booking.is_violation,
        violation_reason=booking.violation_reason,
        created_at=booking.created_at,
    )


def _validate_request_window(start: datetime, end: datetime) -> tuple[datetime, datetime, int]:
    start_local = ensure_local(start)
    end_local = ensure_local(end)
    try:
        minutes = duration_minutes(start_local, end_local)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if start_local.date() != end_local.date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="单笔预约暂不跨自然日，请按日期拆分提交",
        )
    if start_local <= datetime.now(APP_TZ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="预约开始时间必须晚于当前时间")
    return start_local, end_local, minutes


def _day_bounds(dt: datetime) -> tuple[datetime, datetime]:
    local = ensure_local(dt)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _used_minutes_for_day(db: Session, *, user_id: int, booking: Booking) -> int:
    day_start, day_end = _day_bounds(booking.start_time)
    rows = db.scalars(
        select(Booking).where(
            Booking.user_id == user_id,
            Booking.id != booking.id,
            Booking.status.in_(ACTIVE_QUOTA_STATUSES),
            Booking.start_time >= day_start,
            Booking.start_time < day_end,
        )
    ).all()
    total = 0
    for row in rows:
        try:
            total += duration_minutes(row.start_time, row.end_time)
        except ValueError:
            continue
    return total


def _check_dynamic_duration(db: Session, booking: Booking) -> None:
    current_minutes = duration_minutes(booking.start_time, booking.end_time)
    if booking.single_limit_minutes and current_minutes > booking.single_limit_minutes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"本次预约时长超过该用途允许的单次上限 {booking.single_limit_minutes} 分钟",
        )

    if booking.daily_limit_minutes:
        used = _used_minutes_for_day(db, user_id=booking.user_id, booking=booking)
        if used + current_minutes > booking.daily_limit_minutes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"当日已占用 {used} 分钟，本次 {current_minutes} 分钟，"
                    f"超过该用途动态日上限 {booking.daily_limit_minutes} 分钟"
                ),
            )


def _release_locks(db: Session, booking_id: int) -> None:
    db.execute(delete(BookingSlotLock).where(BookingSlotLock.booking_id == booking_id))


def _try_lock_room(db: Session, *, booking: Booking, room_code: str) -> bool:
    """尝试一次性占住一个房间的全部 30 分钟 slot。

    使用 SAVEPOINT + 唯一约束处理并发冲突。任一 slot 已被占用则回滚这一候选房间，
    不影响外围事务，再继续尝试下一个候选房间。
    """
    slots = iter_half_hour_slots(booking.start_time, booking.end_time)
    try:
        with db.begin_nested():
            for slot_start, _ in slots:
                db.add(
                    BookingSlotLock(
                        booking_id=booking.id,
                        room_code=room_code,
                        slot_start=slot_start,
                    )
                )
            db.flush()
        return True
    except IntegrityError:
        return False


def approve_booking_record(
    db: Session,
    *,
    booking: Booking,
    source: AuditSource,
    reviewer_id: int | None = None,
    preferred_room: str | None = None,
    review_reason: str | None = None,
) -> Booking:
    """审批通过并原子抢占房间；供 AI、管理员和 scheduler 共用。"""
    if booking.status not in {BookingStatus.PENDING_AI, BookingStatus.PENDING_MANUAL}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前订单状态不可再次审批")

    _check_dynamic_duration(db, booking)

    candidates = _candidate_rooms(booking)
    if preferred_room:
        preferred_room = preferred_room.upper().strip()
        if preferred_room not in ROOM_CODES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知房间编号")
        candidates = [preferred_room]

    for room_code in candidates:
        if _try_lock_room(db, booking=booking, room_code=room_code):
            booking.room_code = room_code
            booking.status = BookingStatus.APPROVED
            booking.audit_source = source
            booking.reviewed_by = reviewer_id
            booking.reviewed_at = datetime.now(timezone.utc)
            if review_reason:
                booking.ai_reason = review_reason if source == AuditSource.AI else booking.ai_reason
            db.add(booking)
            db.commit()
            db.refresh(booking)
            return booking

    booking.status = BookingStatus.INVALIDATED
    booking.audit_source = source
    booking.reviewed_by = reviewer_id
    booking.reviewed_at = datetime.now(timezone.utc)
    booking.rejection_reason = "审批通过时所有候选房间对应时段均已被更早通过的订单占用"
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def apply_ai_result(db: Session, *, booking: Booking, result: AIAuditResult) -> Booking:
    booking.ai_decision = result.decision
    booking.ai_reason = result.reason
    booking.ai_guidance = result.guidance
    booking.ai_confidence = result.confidence
    booking.intent_type = result.intent_type
    booking.candidate_rooms_json = json.dumps(result.candidate_rooms, ensure_ascii=False)
    booking.daily_limit_minutes = result.daily_limit_minutes
    booking.single_limit_minutes = result.single_limit_minutes
    booking.ai_raw_json = result.raw_json

    if result.decision == "reject":
        booking.status = BookingStatus.REJECTED
        booking.audit_source = AuditSource.AI
        booking.reviewed_at = datetime.now(timezone.utc)
        booking.rejection_reason = result.reason
        db.add(booking)
        db.commit()
        db.refresh(booking)
        return booking

    if result.decision == "manual":
        booking.status = BookingStatus.PENDING_MANUAL
        db.add(booking)
        db.commit()
        db.refresh(booking)
        return booking

    # AI 秒批：先把 AI 结果 flush 进当前事务，再走统一的原子占房逻辑。
    db.add(booking)
    db.flush()
    return approve_booking_record(db, booking=booking, source=AuditSource.AI, review_reason=result.reason)


def process_booking_ai(booking_id: int) -> None:
    """响应返回后继续处理 AI 审核，避免外部 AI 延迟拖死小程序请求。"""
    with SessionLocal() as db:
        booking = db.get(Booking, booking_id)

        if booking is None or booking.status != BookingStatus.PENDING_AI:
            return

        try:
            result = audit_booking_with_ai(
                purpose=booking.purpose,
                people_count=booking.people_count,
                start_iso=ensure_local(booking.start_time).isoformat(),
                end_iso=ensure_local(booking.end_time).isoformat(),
            )

            apply_ai_result(
                db,
                booking=booking,
                result=result,
            )

        except HTTPException as exc:
            db.rollback()

            booking = db.get(Booking, booking_id)
            if booking is None or booking.status != BookingStatus.PENDING_AI:
                return

            if exc.status_code == status.HTTP_409_CONFLICT:
                booking.status = BookingStatus.REJECTED
                booking.audit_source = AuditSource.AI
                booking.reviewed_at = datetime.now(timezone.utc)
                booking.rejection_reason = str(exc.detail)

            else:
                booking.status = BookingStatus.PENDING_MANUAL
                booking.ai_decision = "manual"
                booking.ai_reason = (
                    f"AI 后台处理异常，已转人工：HTTP {exc.status_code}"
                )
                booking.ai_confidence = 0

            db.add(booking)
            db.commit()

        except Exception as exc:
            db.rollback()

            booking = db.get(Booking, booking_id)
            if booking is None or booking.status != BookingStatus.PENDING_AI:
                return

            booking.status = BookingStatus.PENDING_MANUAL
            booking.ai_decision = "manual"
            booking.ai_reason = (
                f"AI 后台处理异常，已转人工：{type(exc).__name__}"
            )
            booking.ai_confidence = 0

            db.add(booking)
            db.commit()


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreateRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_normal_account)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingResponse:
    start_local, end_local, _ = _validate_request_window(
        payload.start_time,
        payload.end_time,
    )
    purpose = payload.purpose.strip()

    booking = Booking(
        user_id=user.id,
        purpose=purpose,
        people_count=payload.people_count,
        start_time=start_local,
        end_time=end_local,
        status=BookingStatus.PENDING_AI,
    )

    db.add(booking)
    db.commit()
    db.refresh(booking)

    # HTTP 响应发给小程序后，再继续执行 AI 审核。
    background_tasks.add_task(
        process_booking_ai,
        booking.id,
    )

    return _serialize(booking)


@router.get("/me", response_model=BookingListResponse)
def my_bookings(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BookingListResponse:
    total = db.scalar(select(func.count()).select_from(Booking).where(Booking.user_id == user.id)) or 0
    rows = db.scalars(
        select(Booking)
        .where(Booking.user_id == user.id)
        .order_by(Booking.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return BookingListResponse(items=[_serialize(x) for x in rows], total=total)


@router.get("/admin/pending", response_model=BookingListResponse)
def admin_pending_bookings(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> BookingListResponse:
    stmt = (
        select(Booking)
        .where(Booking.status == BookingStatus.PENDING_MANUAL)
        .order_by(Booking.start_time.asc(), Booking.created_at.asc())
        .limit(limit)
    )
    rows = db.scalars(stmt).all()
    return BookingListResponse(items=[_serialize(x) for x in rows], total=len(rows))


@router.get("/admin/all", response_model=BookingListResponse)
def admin_all_bookings(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    booking_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BookingListResponse:
    filters = []
    if booking_status:
        try:
            filters.append(Booking.status == BookingStatus(booking_status))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知预约状态") from exc
    count_stmt = select(func.count()).select_from(Booking)
    stmt = select(Booking)
    if filters:
        count_stmt = count_stmt.where(*filters)
        stmt = stmt.where(*filters)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Booking.created_at.desc()).offset(offset).limit(limit)).all()
    return BookingListResponse(items=[_serialize(x) for x in rows], total=total)


@router.get("/admin/export.xlsx")
def export_bookings_excel(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    booking_status: Annotated[str | None, Query(alias="status")] = None,
) -> StreamingResponse:
    stmt = select(Booking, User).join(User, User.id == Booking.user_id)
    if start_date:
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=APP_TZ)
        stmt = stmt.where(Booking.start_time >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=APP_TZ)
        stmt = stmt.where(Booking.start_time < end_dt)
    if booking_status:
        try:
            stmt = stmt.where(Booking.status == BookingStatus(booking_status))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知预约状态") from exc

    rows = db.execute(stmt.order_by(Booking.start_time.asc())).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "预约记录"
    ws.append([
        "预约ID", "姓名", "学号/工号", "班级", "用途", "AI内部意图", "房间", "开始时间", "结束时间",
        "人数", "状态", "AI决定", "AI理由", "审核来源", "驳回/失效原因", "离场照片", "OCR结果",
        "清扫核验状态", "违规", "违规原因", "创建时间",
    ])
    for booking, user in rows:
        ws.append([
            booking.id, user.name, user.login_id, user.class_name, booking.purpose, booking.intent_type, booking.room_code,
            ensure_local(booking.start_time).strftime("%Y-%m-%d %H:%M"),
            ensure_local(booking.end_time).strftime("%Y-%m-%d %H:%M"),
            booking.people_count, booking.status.value, booking.ai_decision, booking.ai_reason,
            booking.audit_source.value if booking.audit_source else None, booking.rejection_reason,
            (f"/api/cleanup/admin/{booking.id}/photo" if booking.cleanup_photo_path else None), booking.ocr_result, booking.cleanup_review_status,
            "是" if booking.is_violation else "否", booking.violation_reason,
            ensure_local(booking.created_at).strftime("%Y-%m-%d %H:%M:%S"),
        ])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for column in ws.columns:
        width = min(40, max(10, max(len(str(cell.value or "")) for cell in column) + 2))
        ws.column_dimensions[column[0].column_letter].width = width

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"duxue_bookings_{datetime.now(APP_TZ).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/{booking_id}/review", response_model=BookingResponse)
def admin_review_booking(
    booking_id: int,
    payload: AdminReviewRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingResponse:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")
    if booking.status != BookingStatus.PENDING_MANUAL:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅存疑待人工订单可审核")

    if payload.action == "reject":
        booking.status = BookingStatus.REJECTED
        booking.audit_source = AuditSource.ADMIN
        booking.reviewed_by = admin.id
        booking.reviewed_at = datetime.now(timezone.utc)
        booking.rejection_reason = (payload.reason or "管理员驳回").strip()
        db.add(booking)
        db.commit()
        db.refresh(booking)
        return _serialize(booking)

    approved = approve_booking_record(
        db,
        booking=booking,
        source=AuditSource.ADMIN,
        reviewer_id=admin.id,
        preferred_room=payload.room_code,
        review_reason=payload.reason,
    )
    return _serialize(approved)


@router.post("/admin/super", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_super_booking(
    payload: SuperBookingRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingResponse:
    target = db.get(User, payload.user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标用户不存在或已停用")

    start_local, end_local, minutes = _validate_request_window(payload.start_time, payload.end_time)
    room_code = payload.room_code.upper().strip()
    if room_code not in ROOM_CODES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知房间编号")

    booking = Booking(
        user_id=target.id,
        purpose=payload.purpose.strip(),
        people_count=payload.people_count,
        intent_type="admin_super_booking",
        candidate_rooms_json=json.dumps([room_code], ensure_ascii=False),
        start_time=start_local,
        end_time=end_local,
        # 超级预约由管理员直接决定，本身不套 AI 的用途时长，但仍不允许超过自然日技术边界。
        daily_limit_minutes=24 * 60,
        single_limit_minutes=max(30, minutes),
        status=BookingStatus.PENDING_MANUAL,
        ai_decision="admin_override",
        ai_reason="管理员超级预约，跳过 AI 分流",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    approved = approve_booking_record(
        db,
        booking=booking,
        source=AuditSource.SUPER_BOOKING,
        reviewer_id=admin.id,
        preferred_room=room_code,
    )
    return _serialize(approved)


@router.post("/{booking_id}/cancel", response_model=BookingResponse)
def cancel_booking(
    booking_id: int,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingResponse:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")
    if booking.status not in CANCELLABLE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前状态不可取消")
    if ensure_local(booking.start_time) <= datetime.now(APP_TZ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="预约已经开始，不能取消")

    _release_locks(db, booking.id)
    booking.status = BookingStatus.CANCELLED
    booking.room_code = None
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return _serialize(booking)


@router.get("/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: int,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingResponse:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")
    if booking.user_id != user.id and user.role.value != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该预约")
    return _serialize(booking)
