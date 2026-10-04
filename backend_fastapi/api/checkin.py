"""预约签到接口。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import require_normal_account
from config import get_db
from models.bookings import Booking, BookingStatus
from models.users import User
from utils.time_calc import APP_TZ, ensure_local

router = APIRouter(prefix="/checkin", tags=["checkin"])

CHECKIN_WINDOW = timedelta(hours=1)


class CheckinResponse(BaseModel):
    booking_id: int
    room_code: str
    status: BookingStatus
    checked_in_at: datetime
    window_start: datetime
    window_end: datetime


@router.post("/{booking_id}", response_model=CheckinResponse)
def checkin_booking(
    booking_id: int,
    user: Annotated[User, Depends(require_normal_account)],
    db: Annotated[Session, Depends(get_db)],
) -> CheckinResponse:
    """在预约开始时间前后各 1 小时内完成签到。"""
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")

    if booking.status not in {BookingStatus.APPROVED, BookingStatus.ACTIVE}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前预约状态不可签到")

    if not booking.room_code:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="预约尚未分配房间")

    start = ensure_local(booking.start_time)
    window_start = start - CHECKIN_WINDOW
    window_end = start + CHECKIN_WINDOW
    now = datetime.now(APP_TZ)

    # 已签到请求保持幂等，重复点击不会产生第二次签到记录。
    if booking.checked_in_at is not None:
        return CheckinResponse(
            booking_id=booking.id,
            room_code=booking.room_code,
            status=BookingStatus.ACTIVE,
            checked_in_at=booking.checked_in_at,
            window_start=window_start,
            window_end=window_end,
        )

    if not (window_start <= now <= window_end):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅可在预约开始时间前 1 小时至开始后 1 小时内签到",
        )

    booking.checked_in_at = datetime.now(timezone.utc)
    booking.status = BookingStatus.ACTIVE
    db.add(booking)
    db.commit()
    db.refresh(booking)

    return CheckinResponse(
        booking_id=booking.id,
        room_code=booking.room_code,
        status=booking.status,
        checked_in_at=booking.checked_in_at,
        window_start=window_start,
        window_end=window_end,
    )
