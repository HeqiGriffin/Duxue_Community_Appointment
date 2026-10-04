"""房间能力、容量提示与确定性优先级规则。"""
from __future__ import annotations

from dataclasses import dataclass

ROOM_CATALOG: dict[str, dict[str, object]] = {
    "A101": {
        "capacity_hint": 10,
        "suitable": ["自习", "会议", "通用活动"],
        "description": "中小型通用空间",
    },
    "A102": {
        "capacity_hint": 6,
        "suitable": ["自习", "小型会议"],
        "description": "小型安静空间",
    },
    "A103": {
        "capacity_hint": None,
        "suitable": ["大型会议", "大型活动", "钢琴/音乐活动"],
        "description": "大型活动空间",
    },
    "A105": {
        "capacity_hint": 10,
        "suitable": ["会议", "自习", "通用活动"],
        "description": "10 人左右会议优先空间",
    },
    "B102": {
        "capacity_hint": None,
        "suitable": ["音乐练习"],
        "description": "音乐练习空间",
    },
}
ROOM_CODES = tuple(ROOM_CATALOG.keys())


@dataclass(slots=True)
class RoomChoiceIssue:
    reason: str
    guidance: str
    recommended_rooms: list[str]


def normalize_intent(intent_type: str | None) -> str:
    value = (intent_type or "").strip().lower()
    if any(k in value for k in ("meeting", "conference", "discussion", "seminar", "会议", "讨论")):
        return "meeting"
    if any(k in value for k in ("study", "review", "学习", "自习", "复习")):
        return "study"
    if any(k in value for k in ("music", "piano", "音乐", "钢琴", "乐器")):
        return "music"
    if any(k in value for k in ("large", "event", "activity", "大型", "活动", "排练")):
        return "large_event"
    return "other"


def priority_rooms(intent_type: str | None, people_count: int) -> list[str]:
    """返回确定性场景下的房间优先顺序。

    对没有足够明确规则的 other 不强行排序，交给 AI/人工判断。
    """
    intent = normalize_intent(intent_type)
    if intent == "meeting":
        if people_count <= 6:
            return ["A102", "A105", "A101", "A103"]
        if people_count <= 10:
            return ["A105", "A101", "A103"]
        return ["A103"]
    if intent == "study":
        if people_count <= 6:
            return ["A102", "A101", "A105"]
        if people_count <= 10:
            return ["A101", "A105"]
        return []
    if intent == "music":
        return ["B102", "A103"]
    if intent == "large_event":
        return ["A103"]
    return []


def validate_room_choice(
    *,
    intent_type: str | None,
    people_count: int,
    selected_room: str,
    available_rooms: list[str],
) -> RoomChoiceIssue | None:
    selected = selected_room.upper().strip()
    available = [x.upper().strip() for x in available_rooms]

    if selected not in ROOM_CODES:
        return RoomChoiceIssue(
            reason="所选房间不存在",
            guidance="请重新选择系统列出的可用房间。",
            recommended_rooms=[],
        )
    if selected not in available:
        return RoomChoiceIssue(
            reason=f"所选房间 {selected} 在该时段已被占用",
            guidance="请刷新空闲房间后重新选择。",
            recommended_rooms=[],
        )

    priority = priority_rooms(intent_type, people_count)
    if not priority:
        return None

    available_priority = [room for room in priority if room in available]
    if selected not in priority:
        return RoomChoiceIssue(
            reason=f"按当前用途和 {people_count} 人规模，{selected} 不是合适的优先房间",
            guidance=(
                f"当前更合适的空闲房间为：{'、'.join(available_priority)}。"
                if available_priority else "当前没有明确更合适的空闲房间，建议转人工确认。"
            ),
            recommended_rooms=available_priority,
        )

    if available_priority and selected != available_priority[0]:
        best = available_priority[0]
        return RoomChoiceIssue(
            reason=f"当前时段更优先的房间 {best} 仍空闲，不应优先占用 {selected}",
            guidance=f"请优先选择 {best}；若其后续被占用，再选择下一顺位房间。",
            recommended_rooms=available_priority,
        )
    return None
