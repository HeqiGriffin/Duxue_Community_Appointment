"""被冻结用户的线上申诉与管理员审核。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_admin, require_password_changed
from config import get_db
from models.appeals import Appeal, AppealStatus
from models.bookings import Booking
from models.users import User, UserStatus

router = APIRouter(prefix="/appeals", tags=["appeal"])


class AppealCreateRequest(BaseModel):
    statement: str = Field(min_length=10, max_length=4000)
    booking_id: int | None = None


class AppealReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = Field(min_length=1, max_length=2000)


class AppealResponse(BaseModel):
    id: int
    user_id: int
    booking_id: int | None
    statement: str
    status: AppealStatus
    reviewer_id: int | None
    review_comment: str | None
    created_at: datetime
    reviewed_at: datetime | None


def _serialize(item: Appeal) -> AppealResponse:
    return AppealResponse(
        id=item.id,
        user_id=item.user_id,
        booking_id=item.booking_id,
        statement=item.statement,
        status=item.status,
        reviewer_id=item.reviewer_id,
        review_comment=item.review_comment,
        created_at=item.created_at,
        reviewed_at=item.reviewed_at,
    )


@router.post("", response_model=AppealResponse, status_code=status.HTTP_201_CREATED)
def create_appeal(
    payload: AppealCreateRequest,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> AppealResponse:
    if user.status != UserStatus.FROZEN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前账号未被冻结，无需提交解封申诉")
    pending = db.scalar(
        select(Appeal).where(Appeal.user_id == user.id, Appeal.status == AppealStatus.PENDING)
    )
    if pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已有待处理申诉，请勿重复提交")
    if payload.booking_id is not None:
        booking = db.get(Booking, payload.booking_id)
        if booking is None or booking.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="关联预约不存在")

    item = Appeal(user_id=user.id, booking_id=payload.booking_id, statement=payload.statement.strip())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize(item)


@router.get("/me", response_model=list[AppealResponse])
def my_appeals(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AppealResponse]:
    rows = db.scalars(select(Appeal).where(Appeal.user_id == user.id).order_by(Appeal.created_at.desc())).all()
    return [_serialize(x) for x in rows]


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
    return [_serialize(x) for x in rows]


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

    item.status = AppealStatus.APPROVED if payload.action == "approve" else AppealStatus.REJECTED
    item.reviewer_id = admin.id
    item.review_comment = payload.comment.strip()
    item.reviewed_at = datetime.now(timezone.utc)

    if item.status == AppealStatus.APPROVED:
        user = db.get(User, item.user_id)
        if user is not None:
            user.status = UserStatus.NORMAL
            user.frozen_reason = None
            user.frozen_at = None
            db.add(user)

    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize(item)
