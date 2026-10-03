"""预约时间工具。

注意：这里不再实现旧需求中的“统一每日 4 小时上限”。最终方案要求由 AI/规则层
按用途动态决定可预约时长，因此本文件只提供通用时间计算能力。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Asia/Shanghai")
SLOT_MINUTES = 30
FALLBACK_HOUR = 23
CLEANUP_GRACE_MINUTES = 30


def ensure_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(APP_TZ)


def validate_booking_range(start: datetime, end: datetime) -> None:
    start_local = ensure_local(start)
    end_local = ensure_local(end)
    if end_local <= start_local:
        raise ValueError("结束时间必须晚于开始时间")
    if start_local.minute not in (0, 30) or end_local.minute not in (0, 30):
        raise ValueError("预约时间必须按 30 分钟分段")
    if start_local.second or end_local.second or start_local.microsecond or end_local.microsecond:
        raise ValueError("预约时间不能包含秒或微秒")


def duration_minutes(start: datetime, end: datetime) -> int:
    validate_booking_range(start, end)
    delta = ensure_local(end) - ensure_local(start)
    return int(delta.total_seconds() // 60)


def cleanup_deadline(end: datetime) -> datetime:
    return ensure_local(end) + timedelta(minutes=CLEANUP_GRACE_MINUTES)


def fallback_cutoff(day: date) -> datetime:
    """返回指定日期 23:00 的兜底节点。"""
    return datetime.combine(day, time(hour=FALLBACK_HOUR), tzinfo=APP_TZ)


def is_next_day_booking(booking_start: datetime, now: datetime | None = None) -> bool:
    current = ensure_local(now or datetime.now(APP_TZ))
    return ensure_local(booking_start).date() == (current.date() + timedelta(days=1))


def iter_half_hour_slots(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    validate_booking_range(start, end)
    cursor = ensure_local(start)
    target = ensure_local(end)
    slots: list[tuple[datetime, datetime]] = []
    while cursor < target:
        next_cursor = cursor + timedelta(minutes=SLOT_MINUTES)
        slots.append((cursor, next_cursor))
        cursor = next_cursor
    return slots
