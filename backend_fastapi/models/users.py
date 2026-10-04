"""用户白名单模型：仅学生/管理员两种角色，无公开注册入口。"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from config import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    STUDENT = "student"
    ADMIN = "admin"


class UserStatus(str, enum.Enum):
    NORMAL = "normal"
    FROZEN = "frozen"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    class_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16),
        default=UserRole.STUDENT,
        nullable=False,
        index=True,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, length=16),
        default=UserStatus.NORMAL,
        nullable=False,
        index=True,
    )

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    frozen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class DutySchedule(Base):
    """每周固定值班排班：8:00-22:00，每两小时一班。"""

    __tablename__ = "duty_schedules"
    __table_args__ = (UniqueConstraint("weekday", "start_hour", name="uq_duty_weekday_start"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # Monday=0
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    class_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class DutyLog(Base):
    """值班工位登录后的实名签到记录。"""

    __tablename__ = "duty_logs"
    __table_args__ = (UniqueConstraint("shift_date", "start_hour", "user_id", name="uq_duty_shift_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    class_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_class: Mapped[str] = mapped_column(String(128), nullable=False)
    checkin_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    handover_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    handover_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DutyPatrol(Base):
    """两小时值班中的定时巡视任务。每班固定两次：开班后 30 / 90 分钟。"""

    __tablename__ = "duty_patrols"
    __table_args__ = (UniqueConstraint("duty_log_id", "sequence", name="uq_duty_patrol_sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    duty_log_id: Mapped[int] = mapped_column(ForeignKey("duty_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    booking_match_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hygiene_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    safety_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    order_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    facility_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    issue_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
