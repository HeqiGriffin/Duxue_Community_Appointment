"""值班工作台：房间雷达、排班、交接班签到与打印数据。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_admin, resolve_mode
from config import get_db
from core.ai_prompt import ROOM_CODES
from models.bookings import Booking, BookingStatus
from models.users import DutyLog, DutySchedule, User, UserRole
from utils.time_calc import APP_TZ, ensure_local

router = APIRouter(prefix="/duty", tags=["duty"])
SHIFT_STARTS = tuple(range(8, 22, 2))


class RoomRadarItem(BaseModel):
    room_code: str
    occupied: bool
    booking_id: int | None = None
    user_name: str | None = None
    class_name: str | None = None
    purpose: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


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


class HandoverRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class ViolationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


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
    ).all()
    occupied = {b.room_code: (b, u) for b, u in rows if b.room_code}
    result: list[RoomRadarItem] = []
    for room in ROOM_CODES:
        pair = occupied.get(room)
        if not pair:
            result.append(RoomRadarItem(room_code=room, occupied=False))
            continue
        booking, user = pair
        result.append(
            RoomRadarItem(
                room_code=room,
                occupied=True,
                booking_id=booking.id,
                user_name=user.name,
                class_name=user.class_name,
                purpose=booking.purpose,
                start_time=booking.start_time,
                end_time=booking.end_time,
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

    # 本接口按“完整周表”替换，避免局部编辑留下旧数据。
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


@router.post("/checkin", response_model=DutyLogResponse)
def duty_checkin(
    user: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DutyLogResponse:
    if user.role != UserRole.STUDENT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="管理员无需学生值班签到")
    now = datetime.now(APP_TZ)
    start_hour = _current_shift(now)
    schedule = db.scalar(
        select(DutySchedule).where(DutySchedule.weekday == now.weekday(), DutySchedule.start_hour == start_hour)
    )
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前班次尚未配置值班班级")
    if not user.class_name or user.class_name != schedule.class_name:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"当前应由 {schedule.class_name} 值班")

    existing = db.scalar(
        select(DutyLog).where(
            DutyLog.shift_date == now.date(), DutyLog.start_hour == start_hour, DutyLog.user_id == user.id
        )
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
    return DutyLogResponse.model_validate(existing, from_attributes=True)


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
    item.handover_note = payload.note.strip()
    db.add(item)
    db.commit()
    db.refresh(item)
    return DutyLogResponse.model_validate(item, from_attributes=True)


@router.post("/rooms/{room_code}/violation")
def mark_room_violation(
    room_code: str,
    payload: ViolationRequest,
    _: Annotated[User, Depends(_duty_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    now = datetime.now(APP_TZ)
    booking = db.scalar(
        select(Booking).where(
            Booking.room_code == room_code.upper(),
            Booking.status.in_([BookingStatus.APPROVED, BookingStatus.ACTIVE]),
            Booking.start_time <= now,
            Booking.end_time > now,
        )
    )
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前房间没有系统记录中的在用预约")
    booking.is_violation = True
    booking.violation_reason = payload.reason.strip()
    db.add(booking)
    db.commit()
    return {"booking_id": booking.id, "room_code": booking.room_code, "marked": True}


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
    logs = db.scalars(
        select(DutyLog).where(DutyLog.shift_date >= week_start.date(), DutyLog.shift_date < week_end.date())
    ).all()
    violations = db.scalars(
        select(Booking).where(
            Booking.is_violation.is_(True), Booking.start_time >= week_start, Booking.start_time < week_end
        )
    ).all()

    return {
        "generated_at": now.isoformat(),
        "week_schedule": [
            {"weekday": x.weekday, "start_hour": x.start_hour, "end_hour": x.start_hour + 2, "class_name": x.class_name}
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
                "purpose": b.purpose,
                "status": b.status.value,
            }
            for b, u in bookings
        ],
        "weekly_summary": {
            "duty_checkins": len(logs),
            "bookings": db.scalar(select(func.count()).select_from(Booking).where(Booking.start_time >= week_start, Booking.start_time < week_end)) or 0,
            "violations": len(violations),
        },
    }
