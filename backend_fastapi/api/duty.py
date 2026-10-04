"""值班工作台：排班、两次定时巡视、房间雷达、交接班与管理记录。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_admin, resolve_mode
from config import get_db
from core.room_policy import ROOM_CODES
from models.bookings import Booking, BookingStatus
from models.users import DutyLog, DutyPatrol, DutySchedule, User, UserRole
from utils.time_calc import APP_TZ, ensure_local

router = APIRouter(prefix="/duty", tags=["duty"])
SHIFT_STARTS = tuple(range(8, 22, 2))
PATROL_OFFSETS = (30, 90)
PATROL_EARLY_MINUTES = 15


class RoomOccupant(BaseModel):
    booking_id: int
    user_name: str
    class_name: str | None
    purpose: str
    usage_mode: str
    people_count: int
    start_time: datetime
    end_time: datetime


class RoomRadarItem(BaseModel):
    room_code: str
    occupied: bool
    occupancy_mode: str = "free"
    people_total: int = 0
    occupants: list[RoomOccupant] = []


class DutyScheduleItem(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_hour: int
    class_name: str = Field(min_length=1, max_length=128)


class DutyLogResponse(BaseModel):
    id: int
    user_id: int
    class_name: str | None
    scheduled_class: str
    shift_date: date
    start_hour: int
    checkin_at: datetime
    handover_note: str | None
    handover_at: datetime | None


class PatrolResponse(BaseModel):
    id: int
    duty_log_id: int
    sequence: int
    due_at: datetime
    submitted_at: datetime | None
    booking_match_ok: bool | None
    hygiene_ok: bool | None
    safety_ok: bool | None
    order_ok: bool | None
    facility_ok: bool | None
    issue_note: str | None
    timing_status: str
    can_submit: bool


class DutyCurrentResponse(BaseModel):
    shift_date: date
    start_hour: int
    end_hour: int
    scheduled_class: str | None
    log: DutyLogResponse | None
    patrols: list[PatrolResponse]
    patrol_rule: str = "每个两小时班次至少完成两次巡视，计划时间为开班后 30 分钟与 90 分钟。"


class PatrolSubmitRequest(BaseModel):
    booking_match_ok: bool
    hygiene_ok: bool
    safety_ok: bool
    order_ok: bool
    facility_ok: bool
    issue_note: str | None = Field(default=None, max_length=2000)


class HandoverRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class ViolationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class DutyHistoryItem(BaseModel):
    log_id: int
    shift_date: date
    start_hour: int
    scheduled_class: str
    user_id: int
    user_name: str
    login_id: str
    class_name: str | None
    checkin_at: datetime
    handover_at: datetime | None
    handover_note: str | None
    patrol_completed: int
    patrol_required: int = 2
    late_patrols: int
    patrols: list[PatrolResponse]


def _duty_user(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    x_duty_terminal_token: Annotated[str | None, Header(alias="X-Duty-Terminal-Token")] = None,
) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="首次登录必须先修改密码")
    mode = resolve_mode(user, request, x_duty_terminal_token)
    if mode not in {"duty", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅值班电脑或管理员可访问值班工作台")
    return user


def _current_shift(now: datetime) -> int:
    local = ensure_local(now)
    for start in SHIFT_STARTS:
        if start <= local.hour < start + 2:
            return start
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前不在值班时段（08:00-22:00）")


def _shift_start(date_value: date, start_hour: int) -> datetime:
    return datetime.combine(date_value, time(hour=start_hour), tzinfo=APP_TZ)


def _ensure_patrols(db: Session, log: DutyLog) -> list[DutyPatrol]:
    rows = list(db.scalars(select(DutyPatrol).where(DutyPatrol.duty_log_id == log.id).order_by(DutyPatrol.sequence)).all())
    existing = {x.sequence for x in rows}
    start = _shift_start(log.shift_date, log.start_hour)
    changed = False
    for seq, offset in enumerate(PATROL_OFFSETS, start=1):
        if seq in existing:
            continue
        db.add(DutyPatrol(duty_log_id=log.id, sequence=seq, due_at=start + timedelta(minutes=offset)))
        changed = True
    if changed:
        db.commit()
        rows = list(db.scalars(select(DutyPatrol).where(DutyPatrol.duty_log_id == log.id).order_by(DutyPatrol.sequence)).all())
    return rows


def _patrol_response(patrol: DutyPatrol, now: datetime | None = None) -> PatrolResponse:
    current = ensure_local(now or datetime.now(APP_TZ))
    due = ensure_local(patrol.due_at)
    if patrol.submitted_at:
        submitted = ensure_local(patrol.submitted_at)
        timing = "on_time" if submitted <= due + timedelta(minutes=15) else "late"
        can_submit = False
    else:
        if current < due - timedelta(minutes=PATROL_EARLY_MINUTES):
            timing = "not_open"
            can_submit = False
        elif current <= due + timedelta(minutes=15):
            timing = "due"
            can_submit = True
        else:
            timing = "late"
            can_submit = True
    return PatrolResponse(
        id=patrol.id,
        duty_log_id=patrol.duty_log_id,
        sequence=patrol.sequence,
        due_at=patrol.due_at,
        submitted_at=patrol.submitted_at,
        booking_match_ok=patrol.booking_match_ok,
        hygiene_ok=patrol.hygiene_ok,
        safety_ok=patrol.safety_ok,
        order_ok=patrol.order_ok,
        facility_ok=patrol.facility_ok,
        issue_note=patrol.issue_note,
        timing_status=timing,
        can_submit=can_submit,
    )


def _log_response(log: DutyLog) -> DutyLogResponse:
    return DutyLogResponse.model_validate(log, from_attributes=True)


@router.get("/rooms", response_model=list[RoomRadarItem])
def room_radar(
    _: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RoomRadarItem]:
    now = datetime.now(APP_TZ)
    rows = db.execute(
        select(Booking, User)
        .join(User, User.id == Booking.user_id)
        .where(
            Booking.room_code.is_not(None),
            Booking.status.in_([BookingStatus.APPROVED, BookingStatus.ACTIVE]),
            Booking.start_time <= now,
            Booking.end_time > now,
        )
        .order_by(Booking.room_code, Booking.start_time, Booking.id)
    ).all()
    grouped: dict[str, list[tuple[Booking, User]]] = defaultdict(list)
    for booking, user in rows:
        if booking.room_code:
            grouped[booking.room_code].append((booking, user))

    result: list[RoomRadarItem] = []
    for room in ROOM_CODES:
        pairs = grouped.get(room, [])
        occupants = [
            RoomOccupant(
                booking_id=b.id,
                user_name=u.name,
                class_name=u.class_name,
                purpose=b.purpose,
                usage_mode=b.usage_mode,
                people_count=b.people_count,
                start_time=b.start_time,
                end_time=b.end_time,
            )
            for b, u in pairs
        ]
        modes = {b.usage_mode for b, _ in pairs}
        occupancy_mode = "study_shared" if pairs and modes == {"study"} else ("exclusive" if pairs else "free")
        result.append(
            RoomRadarItem(
                room_code=room,
                occupied=bool(pairs),
                occupancy_mode=occupancy_mode,
                people_total=sum(max(1, int(b.people_count or 1)) for b, _ in pairs),
                occupants=occupants,
            )
        )
    return result


@router.put("/admin/schedule", response_model=list[DutyScheduleItem])
def replace_schedule(
    items: list[DutyScheduleItem],
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DutyScheduleItem]:
    if not items:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="排班表不能为空")
    seen: set[tuple[int, int]] = set()
    for item in items:
        if item.start_hour not in SHIFT_STARTS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="班次必须从 8/10/12/14/16/18/20 点开始")
        key = (item.weekday, item.start_hour)
        if key in seen:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="排班表存在重复班次")
        seen.add(key)

    for old in db.scalars(select(DutySchedule)).all():
        db.delete(old)
    for item in items:
        db.add(DutySchedule(weekday=item.weekday, start_hour=item.start_hour, class_name=item.class_name.strip(), created_by=admin.id))
    db.commit()
    return items


@router.get("/schedule", response_model=list[DutyScheduleItem])
def get_schedule(
    _: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DutyScheduleItem]:
    rows = db.scalars(select(DutySchedule).order_by(DutySchedule.weekday, DutySchedule.start_hour)).all()
    return [DutyScheduleItem(weekday=x.weekday, start_hour=x.start_hour, class_name=x.class_name) for x in rows]


@router.get("/current", response_model=DutyCurrentResponse)
def current_duty(
    user: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DutyCurrentResponse:
    now = datetime.now(APP_TZ)
    start_hour = _current_shift(now)
    schedule = db.scalar(select(DutySchedule).where(DutySchedule.weekday == now.weekday(), DutySchedule.start_hour == start_hour))
    log = None
    patrols: list[DutyPatrol] = []
    if user.role == UserRole.STUDENT:
        log = db.scalar(
            select(DutyLog).where(
                DutyLog.shift_date == now.date(), DutyLog.start_hour == start_hour, DutyLog.user_id == user.id
            )
        )
        if log:
            patrols = _ensure_patrols(db, log)
    return DutyCurrentResponse(
        shift_date=now.date(),
        start_hour=start_hour,
        end_hour=start_hour + 2,
        scheduled_class=schedule.class_name if schedule else None,
        log=_log_response(log) if log else None,
        patrols=[_patrol_response(x, now) for x in patrols],
    )


@router.post("/checkin", response_model=DutyCurrentResponse)
def duty_checkin(
    user: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DutyCurrentResponse:
    if user.role != UserRole.STUDENT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="管理员无需学生值班签到")
    now = datetime.now(APP_TZ)
    start_hour = _current_shift(now)
    schedule = db.scalar(select(DutySchedule).where(DutySchedule.weekday == now.weekday(), DutySchedule.start_hour == start_hour))
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前班次尚未配置值班班级")
    if not user.class_name or user.class_name != schedule.class_name:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"当前应由 {schedule.class_name} 值班")

    existing = db.scalar(
        select(DutyLog).where(DutyLog.shift_date == now.date(), DutyLog.start_hour == start_hour, DutyLog.user_id == user.id)
    )
    if existing is None:
        existing = DutyLog(
            user_id=user.id,
            class_name=user.class_name,
            shift_date=now.date(),
            start_hour=start_hour,
            scheduled_class=schedule.class_name,
            checkin_at=now,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
    patrols = _ensure_patrols(db, existing)
    return DutyCurrentResponse(
        shift_date=now.date(), start_hour=start_hour, end_hour=start_hour + 2,
        scheduled_class=schedule.class_name, log=_log_response(existing),
        patrols=[_patrol_response(x, now) for x in patrols],
    )


@router.post("/patrols/{patrol_id}", response_model=PatrolResponse)
def submit_patrol(
    patrol_id: int,
    payload: PatrolSubmitRequest,
    user: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PatrolResponse:
    patrol = db.get(DutyPatrol, patrol_id)
    if patrol is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="巡视任务不存在")
    log = db.get(DutyLog, patrol.duty_log_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="值班记录不存在")
    if user.role != UserRole.ADMIN and log.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权提交该巡视任务")
    if patrol.submitted_at is not None:
        return _patrol_response(patrol)

    now = datetime.now(APP_TZ)
    due = ensure_local(patrol.due_at)
    if now < due - timedelta(minutes=PATROL_EARLY_MINUTES):
        open_at = due - timedelta(minutes=PATROL_EARLY_MINUTES)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"本次巡视尚未到时间，请在 {open_at.strftime('%H:%M')} 后进行并提交",
        )
    shift_end = _shift_start(log.shift_date, log.start_hour) + timedelta(hours=2)
    if now > shift_end + timedelta(minutes=15):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前班次已经结束，无法补交本次巡视")

    checks = [payload.booking_match_ok, payload.hygiene_ok, payload.safety_ok, payload.order_ok, payload.facility_ok]
    if not all(checks) and not (payload.issue_note or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="存在异常项目时必须填写异常情况说明")

    patrol.booking_match_ok = payload.booking_match_ok
    patrol.hygiene_ok = payload.hygiene_ok
    patrol.safety_ok = payload.safety_ok
    patrol.order_ok = payload.order_ok
    patrol.facility_ok = payload.facility_ok
    patrol.issue_note = (payload.issue_note or "").strip() or "本次巡视无异常"
    patrol.submitted_at = now
    db.add(patrol)
    db.commit()
    db.refresh(patrol)
    return _patrol_response(patrol, now)


@router.post("/handover/{log_id}", response_model=DutyLogResponse)
def handover(
    log_id: int,
    payload: HandoverRequest,
    user: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DutyLogResponse:
    item = db.get(DutyLog, log_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="值班记录不存在")
    if user.role != UserRole.ADMIN and item.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权修改该值班记录")
    patrols = _ensure_patrols(db, item)
    if sum(1 for x in patrols if x.submitted_at is not None) < 2:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="两次社区巡视尚未全部完成，不能交接班")
    item.handover_note = payload.note.strip()
    item.handover_at = datetime.now(APP_TZ)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _log_response(item)


@router.post("/bookings/{booking_id}/violation")
def mark_booking_violation(
    booking_id: int,
    payload: ViolationRequest,
    _: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    now = datetime.now(APP_TZ)
    booking = db.get(Booking, booking_id)
    if booking is None or booking.status not in {BookingStatus.APPROVED, BookingStatus.ACTIVE}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前预约不存在或不在有效使用状态")
    if not (ensure_local(booking.start_time) <= now < ensure_local(booking.end_time)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该预约当前不在使用时段")
    booking.is_violation = True
    booking.violation_reason = payload.reason.strip()
    db.add(booking)
    db.commit()
    return {"booking_id": booking.id, "room_code": booking.room_code, "marked": True}


@router.get("/admin/logs", response_model=list[DutyHistoryItem])
def admin_duty_logs(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DutyHistoryItem]:
    rows = db.execute(
        select(DutyLog, User)
        .join(User, User.id == DutyLog.user_id)
        .order_by(DutyLog.shift_date.desc(), DutyLog.start_hour.desc(), DutyLog.checkin_at.desc())
        .limit(limit)
    ).all()
    result: list[DutyHistoryItem] = []
    now = datetime.now(APP_TZ)
    for log, user in rows:
        patrols = list(db.scalars(select(DutyPatrol).where(DutyPatrol.duty_log_id == log.id).order_by(DutyPatrol.sequence)).all())
        responses = [_patrol_response(x, now) for x in patrols]
        result.append(
            DutyHistoryItem(
                log_id=log.id,
                shift_date=log.shift_date,
                start_hour=log.start_hour,
                scheduled_class=log.scheduled_class,
                user_id=user.id,
                user_name=user.name,
                login_id=user.login_id,
                class_name=user.class_name,
                checkin_at=log.checkin_at,
                handover_at=log.handover_at,
                handover_note=log.handover_note,
                patrol_completed=sum(1 for x in patrols if x.submitted_at),
                late_patrols=sum(1 for x in responses if x.submitted_at and x.timing_status == "late"),
                patrols=responses,
            )
        )
    return result


@router.get("/print-data")
def print_center_data(
    _: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    now = datetime.now(APP_TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    week_start = day_start - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=7)

    schedule = db.scalars(select(DutySchedule).order_by(DutySchedule.weekday, DutySchedule.start_hour)).all()
    bookings = db.execute(
        select(Booking, User)
        .join(User, User.id == Booking.user_id)
        .where(Booking.start_time >= day_start, Booking.start_time < day_end)
        .order_by(Booking.start_time, Booking.room_code)
    ).all()
    logs = db.scalars(select(DutyLog).where(DutyLog.shift_date >= week_start.date(), DutyLog.shift_date < week_end.date())).all()
    log_ids = [x.id for x in logs]
    patrols = list(db.scalars(select(DutyPatrol).where(DutyPatrol.duty_log_id.in_(log_ids))).all()) if log_ids else []
    violations = db.scalars(
        select(Booking).where(Booking.is_violation.is_(True), Booking.start_time >= week_start, Booking.start_time < week_end)
    ).all()

    completed_shifts = 0
    for log in logs:
        count = sum(1 for x in patrols if x.duty_log_id == log.id and x.submitted_at)
        if count >= 2 and log.handover_at:
            completed_shifts += 1

    return {
        "generated_at": now.isoformat(),
        "week_schedule": [
            {
                "weekday": x.weekday,
                "start_hour": x.start_hour,
                "end_hour": x.start_hour + 2,
                "class_name": x.class_name,
                "patrol_times": [f"{x.start_hour:02d}:30", f"{x.start_hour + 1:02d}:30"],
            }
            for x in schedule
        ],
        "today_bookings": [
            {
                "booking_id": b.id,
                "room_code": b.room_code,
                "start_time": ensure_local(b.start_time).isoformat(),
                "end_time": ensure_local(b.end_time).isoformat(),
                "name": u.name,
                "class_name": u.class_name,
                "people_count": b.people_count,
                "usage_mode": b.usage_mode,
                "purpose": b.purpose,
                "status": b.status.value,
            }
            for b, u in bookings
        ],
        "weekly_summary": {
            "duty_checkins": len(logs),
            "completed_shifts": completed_shifts,
            "patrol_submissions": sum(1 for x in patrols if x.submitted_at),
            "bookings": db.scalar(select(func.count()).select_from(Booking).where(Booking.start_time >= week_start, Booking.start_time < week_end)) or 0,
            "violations": len(violations),
        },
    }
