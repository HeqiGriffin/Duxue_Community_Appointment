"""后台定时任务：23:00 次日存疑兜底、预约状态推进、30 分钟未清扫冻结。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from api.booking import approve_booking_record
from config import SessionLocal
from models.bookings import AuditSource, Booking, BookingStatus
from models.users import User, UserStatus
from utils.time_calc import APP_TZ, cleanup_deadline, ensure_local

logger = logging.getLogger(__name__)
_scheduler_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None
_last_fallback_date = None


def approve_next_day_pending(now: datetime | None = None) -> dict[str, int]:
    """23:00 兜底：按提交顺序尝试通过所有次日“存疑”订单。

    若候选房间已经被更早通过订单占用，approve_booking_record 会把该单标为 invalidated，
    从而同时满足“批量兜底”与“先过先得”的物理资源约束。
    """
    current = ensure_local(now or datetime.now(APP_TZ))
    target_date = current.date() + timedelta(days=1)
    approved = invalidated = failed = 0

    with SessionLocal() as db:
        rows = db.scalars(
            select(Booking)
            .where(Booking.status == BookingStatus.PENDING_MANUAL)
            .order_by(Booking.created_at.asc())
        ).all()
        for booking in rows:
            if ensure_local(booking.start_time).date() != target_date:
                continue
            try:
                result = approve_booking_record(db, booking=booking, source=AuditSource.SCHEDULER)
                if result.status == BookingStatus.APPROVED:
                    approved += 1
                elif result.status == BookingStatus.INVALIDATED:
                    invalidated += 1
            except Exception:  # noqa: BLE001 - 单个订单不能阻塞整批兜底
                db.rollback()
                failed += 1
                logger.exception("23:00 兜底处理预约 %s 失败", booking.id)
    return {"approved": approved, "invalidated": invalidated, "failed": failed}


def advance_booking_states(now: datetime | None = None) -> dict[str, int]:
    """推进 APPROVED -> ACTIVE -> AWAITING_CLEANUP。"""
    current = ensure_local(now or datetime.now(APP_TZ))
    activated = awaiting_cleanup = 0

    with SessionLocal() as db:
        rows = db.scalars(
            select(Booking).where(Booking.status.in_([BookingStatus.APPROVED, BookingStatus.ACTIVE]))
        ).all()
        for booking in rows:
            start = ensure_local(booking.start_time)
            end = ensure_local(booking.end_time)
            if current >= end:
                booking.status = BookingStatus.AWAITING_CLEANUP
                booking.cleanup_deadline_at = cleanup_deadline(booking.end_time)
                awaiting_cleanup += 1
                db.add(booking)
            elif booking.status == BookingStatus.APPROVED and start <= current < end:
                booking.status = BookingStatus.ACTIVE
                activated += 1
                db.add(booking)
        db.commit()
    return {"activated": activated, "awaiting_cleanup": awaiting_cleanup}


def freeze_overdue_cleanup(now: datetime | None = None) -> dict[str, int]:
    """预约结束 30 分钟仍无现场照片：标记违规并冻结账号预约/签到权限。"""
    current = ensure_local(now or datetime.now(APP_TZ))
    frozen_users: set[int] = set()
    violated = 0

    with SessionLocal() as db:
        rows = db.scalars(
            select(Booking).where(
                Booking.status == BookingStatus.AWAITING_CLEANUP,
                Booking.cleanup_photo_path.is_(None),
                Booking.is_violation.is_(False),
            )
        ).all()
        for booking in rows:
            deadline = booking.cleanup_deadline_at or cleanup_deadline(booking.end_time)
            if current < ensure_local(deadline):
                continue

            booking.is_violation = True
            booking.cleanup_deadline_at = deadline
            violated += 1
            db.add(booking)

            user = db.get(User, booking.user_id)
            if user is not None and user.status != UserStatus.FROZEN:
                user.status = UserStatus.FROZEN
                user.frozen_at = datetime.now(timezone.utc)
                user.frozen_reason = f"预约 #{booking.id} 使用结束后 30 分钟内未完成现场清理实拍上传"
                db.add(user)
                frozen_users.add(user.id)
        db.commit()

    return {"violations": violated, "frozen_users": len(frozen_users)}


def maintenance_tick() -> dict[str, dict[str, int]]:
    states = advance_booking_states()
    freezes = freeze_overdue_cleanup()
    return {"states": states, "freezes": freezes}


async def _scheduler_loop() -> None:
    """轻量后台循环，避免为了两个任务额外依赖调度框架。"""
    global _last_fallback_date
    assert _stop_event is not None

    while not _stop_event.is_set():
        now = datetime.now(APP_TZ)
        try:
            # 数据库任务是同步函数，放线程中避免阻塞 FastAPI 事件循环。
            await asyncio.to_thread(maintenance_tick)
            if now.hour == 23 and _last_fallback_date != now.date():
                await asyncio.to_thread(approve_next_day_pending, now)
                _last_fallback_date = now.date()
        except Exception:  # noqa: BLE001
            logger.exception("后台预约定时任务执行失败")

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=60)
        except TimeoutError:
            pass


def start_scheduler() -> asyncio.Task[None]:
    global _scheduler_task, _stop_event
    if _scheduler_task is not None and not _scheduler_task.done():
        return _scheduler_task
    _stop_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="duxue-booking-scheduler")
    logger.info("预约定时任务已启动")
    return _scheduler_task


async def stop_scheduler() -> None:
    global _scheduler_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _scheduler_task is not None:
        try:
            await asyncio.wait_for(_scheduler_task, timeout=2)
        except TimeoutError:
            _scheduler_task.cancel()
        except asyncio.CancelledError:
            pass
    _scheduler_task = None
    _stop_event = None
