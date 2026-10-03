"""预约订单与房间时段锁模型。"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from config import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BookingStatus(str, enum.Enum):
    PENDING_AI = "pending_ai"
    PENDING_MANUAL = "pending_manual"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"  # 审批通过时已无可用房间/资源，自动失效
    ACTIVE = "active"
    AWAITING_CLEANUP = "awaiting_cleanup"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AuditSource(str, enum.Enum):
    AI = "ai"
    ADMIN = "admin"
    SCHEDULER = "scheduler"
    SUPER_BOOKING = "super_booking"


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_booking_room_time", "room_code", "start_time", "end_time"),
        Index("ix_booking_user_date", "user_id", "start_time"),
        Index("ix_booking_status_start", "status", "start_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

    # 前端只提交自然语言用途；intent_type 只是 AI 的内部标签，不暴露成固定场景选择。
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    people_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    intent_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # AI 给出按优先级排列的候选房间(JSON 数组字符串)，真正通过时再原子抢占。
    candidate_rooms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    room_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # 动态时长由 AI/规则给出，不使用旧版统一 4 小时上限。
    daily_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    single_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=32),
        default=BookingStatus.PENDING_AI,
        nullable=False,
        index=True,
    )

    ai_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    audit_source: Mapped[AuditSource | None] = mapped_column(
        Enum(AuditSource, native_enum=False, length=32), nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleanup_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleanup_photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ocr_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleanup_review_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    cleanup_review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_violation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    violation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class BookingSlotLock(Base):
    """30 分钟粒度的数据库占房锁。

    唯一约束保证同一房间、同一 slot 只能属于一个预约。即使两个审批请求并发到达，
    数据库也只允许一个事务成功，从根上实现“先过先得”。
    """

    __tablename__ = "booking_slot_locks"
    __table_args__ = (
        UniqueConstraint("room_code", "slot_start", name="uq_room_slot"),
        Index("ix_slot_booking", "booking_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    room_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
