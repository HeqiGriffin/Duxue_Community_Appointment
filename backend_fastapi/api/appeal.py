"""账号解封申诉与 AI 驳回预约的人工复核申诉。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_admin, require_password_changed
from api.booking import approve_booking_record
from config import get_db
from models.appeals import Appeal, AppealStatus, AppealType
from models.bookings import AuditSource, Booking, BookingStatus
from models.users import User, UserStatus
from utils.time_calc import APP_TZ, ensure_local

router = APIRouter(prefix="/appeals", tags=["appeal"])


class AppealCreateRequest(BaseModel):
    statement: str = Field(min_length=10, max_length=4000)
    booking_id: int | None = None


class AppealReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = Field(min_length=1, max_length=2000)
    room_code: str | None = Field(default=None, max_length=32)


class AppealResponse(BaseModel):
    id: int
    user_id: int
    booking_id: int | None
    appeal_type: AppealType
    statement: str
    status: AppealStatus
    reviewer_id: int | None
    review_comment: str | None
    created_at: datetime
    reviewed_at: datetime | None
    booking_status: BookingStatus | None = None
    booking_purpose: str | None = None
    requested_room_code: str | None = None


def _serialize(item: Appeal, booking: Booking | None = None) -> AppealResponse:
    return AppealResponse(
        id=item.id,
        user_id=item.user_id,
        booking_id=item.booking_id,
        appeal_type=item.appeal_type,
        statement=item.statement,
        status=item.status,
        reviewer_id=item.reviewer_id,
        review_comment=item.review_comment,
        created_at=item.created_at,
        reviewed_at=item.reviewed_at,
        booking_status=booking.status if booking else None,
        booking_purpose=booking.purpose if booking else None,
        requested_room_code=booking.requested_room_code if booking else None,
    )


def _booking_for_appeal(db: Session, item: Appeal) -> Booking | None:
    return db.get(Booking, item.booking_id) if item.booking_id is not None else None


@router.post("", response_model=AppealResponse, status_code=status.HTTP_201_CREATED)
def create_appeal(
    payload: AppealCreateRequest,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> AppealResponse:
    statement = payload.statement.strip()

    if payload.booking_id is None:
        if user.status != UserStatus.FROZEN:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前账号未被冻结，无需提交解封申诉")
        pending = db.scalar(
            select(Appeal).where(
                Appeal.user_id == user.id,
                Appeal.appeal_type == AppealType.ACCOUNT,
                Appeal.status == AppealStatus.PENDING,
            )
        )
        if pending:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已有待处理解封申诉，请勿重复提交")
        item = Appeal(
            user_id=user.id,
            booking_id=None,
            appeal_type=AppealType.ACCOUNT,
            statement=statement,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return _serialize(item)

    booking = db.get(Booking, payload.booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="关联预约不存在")
    if booking.status != BookingStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅 AI/管理员已驳回的预约可以申请人工复核")
    if ensure_local(booking.start_time) <= datetime.now(APP_TZ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="预约开始时间已到，无法再发起人工复核")

    pending = db.scalar(
        select(Appeal).where(
            Appeal.user_id == user.id,
            Appeal.booking_id == booking.id,
            Appeal.appeal_type == AppealType.BOOKING_REVIEW,
            Appeal.status == AppealStatus.PENDING,
        )
    )
    if pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该预约已有待处理人工复核，请勿重复提交")

    item = Appeal(
        user_id=user.id,
        booking_id=booking.id,
        appeal_type=AppealType.BOOKING_REVIEW,
        statement=statement,
    )
    # 转人工后进入统一待人工预约队列，管理员既可在预约管理页处理，也可在申诉中心处理。
    booking.status = BookingStatus.PENDING_MANUAL
    db.add_all([item, booking])
    db.commit()
    db.refresh(item)
    db.refresh(booking)
    return _serialize(item, booking)


@router.get("/me", response_model=list[AppealResponse])
def my_appeals(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AppealResponse]:
    rows = db.scalars(
        select(Appeal).where(Appeal.user_id == user.id).order_by(Appeal.created_at.desc())
    ).all()
    return [_serialize(x, _booking_for_appeal(db, x)) for x in rows]


@router.get("/admin/pending", response_model=list[AppealResponse])
def pending_appeals(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AppealResponse]:
    rows = db.scalars(
        select(Appeal)
        .where(Appeal.status == AppealStatus.PENDING)
        .order_by(Appeal.created_at.asc())
        .limit(limit)
    ).all()
    return [_serialize(x, _booking_for_appeal(db, x)) for x in rows]


@router.post("/admin/{appeal_id}/review", response_model=AppealResponse)
def review_appeal(
    appeal_id: int,
    payload: AppealReviewRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> AppealResponse:
    item = db.get(Appeal, appeal_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申诉不存在")
    if item.status != AppealStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该申诉已处理")

    if item.appeal_type == AppealType.ACCOUNT:
        item.status = AppealStatus.APPROVED if payload.action == "approve" else AppealStatus.REJECTED
        item.reviewer_id = admin.id
        item.review_comment = payload.comment.strip()
        item.reviewed_at = datetime.now(timezone.utc)
        if item.status == AppealStatus.APPROVED:
            target = db.get(User, item.user_id)
            if target is not None:
                target.status = UserStatus.NORMAL
                target.frozen_reason = None
                target.frozen_at = None
                db.add(target)
        db.add(item)
        db.commit()
        db.refresh(item)
        return _serialize(item)

    booking = _booking_for_appeal(db, item)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联预约已不存在")
    if ensure_local(booking.start_time) <= datetime.now(APP_TZ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="预约开始时间已到，无法再批准复核")
    if booking.status != BookingStatus.PENDING_MANUAL:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联预约已被其他管理员处理")

    if payload.action == "reject":
        booking.status = BookingStatus.REJECTED
        booking.audit_source = AuditSource.ADMIN
        booking.reviewed_by = admin.id
        booking.reviewed_at = datetime.now(timezone.utc)
        booking.rejection_reason = payload.comment.strip()
        item.status = AppealStatus.REJECTED
        item.reviewer_id = admin.id
        item.review_comment = payload.comment.strip()
        item.reviewed_at = datetime.now(timezone.utc)
        db.add_all([booking, item])
        db.commit()
        db.refresh(item)
        return _serialize(item, booking)

    approved = approve_booking_record(
        db,
        booking=booking,
        source=AuditSource.ADMIN,
        reviewer_id=admin.id,
        preferred_room=payload.room_code or booking.requested_room_code,
        review_reason=payload.comment,
    )
    item.status = AppealStatus.APPROVED
    item.reviewer_id = admin.id
    item.review_comment = payload.comment.strip()
    item.reviewed_at = datetime.now(timezone.utc)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize(item, approved)
