"""房间实时占用与自习共享调剂规则。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import RLock

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.room_policy import ROOM_CATALOG, ROOM_CODES, normalize_intent
from models.bookings import Booking, BookingStatus
from utils.time_calc import ensure_local, iter_half_hour_slots

STUDY_ROOMS = ("A102", "A101")  # 优先把自习集中到较小的 A102，再启用 A101。
BOOKING_OCCUPANCY_STATUSES = {
    BookingStatus.APPROVED,
    BookingStatus.ACTIVE,
    BookingStatus.AWAITING_CLEANUP,
}
ROOM_ALLOCATION_MUTEX = RLock()


@dataclass(slots=True)
class RoomState:
    room_code: str
    occupancy_mode: str  # free | study_shared | exclusive
    available: bool
    study_people: int
    study_booking_count: int
    remaining_capacity: int | None
    state_text: str


def booking_usage_mode(booking: Booking) -> str:
    value = (getattr(booking, "usage_mode", None) or "").strip().lower()
    if value in {"study", "exclusive"}:
        return value
    # 兼容旧数据库记录。
    if normalize_intent(booking.intent_type) == "study":
        return "study"
    purpose = (booking.purpose or "").lower()
    if any(k in purpose for k in ("自习", "复习", "学习", "备考")):
        return "study"
    return "exclusive"


def _overlapping_bookings(
    db: Session,
    *,
    start_time,
    end_time,
    exclude_booking_id: int | None = None,
) -> list[Booking]:
    stmt = select(Booking).where(
        Booking.status.in_(BOOKING_OCCUPANCY_STATUSES),
        Booking.room_code.is_not(None),
        Booking.start_time < end_time,
        Booking.end_time > start_time,
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    return list(db.scalars(stmt).all())


def _study_peak_people(rows: list[Booking], *, start_time, end_time) -> int:
    """返回所选范围内任一 30 分钟 slot 的最大自习人数。"""
    peak = 0
    for slot_start, slot_end in iter_half_hour_slots(start_time, end_time):
        total = 0
        for booking in rows:
            if booking_usage_mode(booking) != "study":
                continue
            if ensure_local(booking.start_time) < ensure_local(slot_end) and ensure_local(booking.end_time) > ensure_local(slot_start):
                total += max(1, int(booking.people_count or 1))
        peak = max(peak, total)
    return peak


def room_states(
    db: Session,
    *,
    start_time,
    end_time,
    usage_mode: str,
    people_count: int = 1,
    exclude_booking_id: int | None = None,
) -> tuple[list[RoomState], str | None, str | None]:
    """返回当前预约方式下各房间可用状态及自习调剂建议。"""
    usage_mode = (usage_mode or "exclusive").strip().lower()
    people_count = max(1, int(people_count or 1))
    rows = _overlapping_bookings(
        db,
        start_time=start_time,
        end_time=end_time,
        exclude_booking_id=exclude_booking_id,
    )
    by_room: dict[str, list[Booking]] = defaultdict(list)
    for booking in rows:
        if booking.room_code in ROOM_CODES:
            by_room[booking.room_code].append(booking)

    states: list[RoomState] = []
    study_candidates: list[tuple[str, int, int]] = []  # room, current_people, remaining

    for room_code in ROOM_CODES:
        room_rows = by_room.get(room_code, [])
        has_exclusive = any(booking_usage_mode(b) != "study" for b in room_rows)
        study_rows = [b for b in room_rows if booking_usage_mode(b) == "study"]
        study_people = _study_peak_people(study_rows, start_time=start_time, end_time=end_time)
        capacity = ROOM_CATALOG[room_code].get("capacity_hint")
        remaining = (int(capacity) - study_people) if isinstance(capacity, int) else None

        if usage_mode == "study":
            if room_code not in STUDY_ROOMS:
                state = RoomState(
                    room_code=room_code,
                    occupancy_mode="exclusive" if room_rows else "free",
                    available=False,
                    study_people=study_people,
                    study_booking_count=len(study_rows),
                    remaining_capacity=remaining,
                    state_text="自习统一安排至 A101 / A102",
                )
            elif has_exclusive:
                state = RoomState(
                    room_code=room_code,
                    occupancy_mode="exclusive",
                    available=False,
                    study_people=study_people,
                    study_booking_count=len(study_rows),
                    remaining_capacity=remaining,
                    state_text="已有非自习预约，占用期间不可加入自习",
                )
            elif remaining is not None and remaining < people_count:
                state = RoomState(
                    room_code=room_code,
                    occupancy_mode="study_shared" if study_rows else "free",
                    available=False,
                    study_people=study_people,
                    study_booking_count=len(study_rows),
                    remaining_capacity=max(0, remaining),
                    state_text=f"自习座位不足，仅余 {max(0, remaining)} 人容量",
                )
            else:
                if study_rows:
                    text = f"已有自习，可继续约；约剩余 {max(0, remaining or 0)} 人容量"
                    mode = "study_shared"
                else:
                    text = "当前空闲，可用于自习共享"
                    mode = "free"
                state = RoomState(
                    room_code=room_code,
                    occupancy_mode=mode,
                    available=True,
                    study_people=study_people,
                    study_booking_count=len(study_rows),
                    remaining_capacity=remaining,
                    state_text=text,
                )
                study_candidates.append((room_code, study_people, remaining if remaining is not None else 10_000))
        else:
            if study_rows:
                state = RoomState(
                    room_code=room_code,
                    occupancy_mode="study_shared",
                    available=False,
                    study_people=study_people,
                    study_booking_count=len(study_rows),
                    remaining_capacity=remaining,
                    state_text="已有自习，仅自习可继续预约；其他用途暂时封闭",
                )
            elif has_exclusive:
                state = RoomState(
                    room_code=room_code,
                    occupancy_mode="exclusive",
                    available=False,
                    study_people=0,
                    study_booking_count=0,
                    remaining_capacity=remaining,
                    state_text="该时段已有非自习预约",
                )
            else:
                state = RoomState(
                    room_code=room_code,
                    occupancy_mode="free",
                    available=True,
                    study_people=0,
                    study_booking_count=0,
                    remaining_capacity=remaining,
                    state_text="空闲，可预约",
                )
        states.append(state)

    recommended = None
    note = None
    if usage_mode == "study" and study_candidates:
        # 先继续填已有自习的房间；若都为空，优先较小的 A102，再启用 A101。
        with_existing = [x for x in study_candidates if x[1] > 0]
        if with_existing:
            with_existing.sort(key=lambda x: (-x[1], STUDY_ROOMS.index(x[0])))
            recommended = with_existing[0][0]
            note = f"为减少空间浪费，系统建议继续集中到 {recommended} 自习。"
        else:
            ordered = sorted(study_candidates, key=lambda x: STUDY_ROOMS.index(x[0]))
            recommended = ordered[0][0]
            note = f"当前两个自习房均可用，系统优先启用 {recommended}，满载后再启用另一间。"

    return states, recommended, note


def available_room_codes(
    db: Session,
    *,
    start_time,
    end_time,
    usage_mode: str,
    people_count: int = 1,
    exclude_booking_id: int | None = None,
) -> list[str]:
    states, _, _ = room_states(
        db,
        start_time=start_time,
        end_time=end_time,
        usage_mode=usage_mode,
        people_count=people_count,
        exclude_booking_id=exclude_booking_id,
    )
    return [x.room_code for x in states if x.available]


def recommended_study_room(
    db: Session,
    *,
    start_time,
    end_time,
    people_count: int,
    exclude_booking_id: int | None = None,
) -> str | None:
    _, recommended, _ = room_states(
        db,
        start_time=start_time,
        end_time=end_time,
        usage_mode="study",
        people_count=people_count,
        exclude_booking_id=exclude_booking_id,
    )
    return recommended
