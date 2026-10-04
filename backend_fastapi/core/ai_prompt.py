"""AI 预约审核：用途理解 + 风险判断 + 房间选择校验。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

from config import settings
from core.room_policy import ROOM_CATALOG, ROOM_CODES, normalize_intent, priority_rooms, validate_room_choice

Decision = Literal["approve", "reject", "manual"]


@dataclass(slots=True)
class AIAuditResult:
    decision: Decision
    reason: str
    guidance: str | None
    intent_type: str
    candidate_rooms: list[str]
    daily_limit_minutes: int
    single_limit_minutes: int
    confidence: int
    raw_json: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _manual_result(reason: str, available_rooms: list[str] | None = None) -> AIAuditResult:
    rooms = [r for r in (available_rooms or list(ROOM_CODES)) if r in ROOM_CODES]
    return AIAuditResult(
        decision="manual",
        reason=reason,
        guidance=None,
        intent_type="uncertain",
        candidate_rooms=rooms or list(ROOM_CODES),
        daily_limit_minutes=24 * 60,
        single_limit_minutes=24 * 60,
        confidence=0,
    )


def _reject_result(
    reason: str,
    guidance: str,
    *,
    candidate_rooms: list[str] | None = None,
    intent_type: str = "uncertain",
    confidence: int = 100,
) -> AIAuditResult:
    return AIAuditResult(
        decision="reject",
        reason=reason,
        guidance=guidance,
        intent_type=intent_type,
        candidate_rooms=candidate_rooms or list(ROOM_CODES),
        daily_limit_minutes=24 * 60,
        single_limit_minutes=24 * 60,
        confidence=confidence,
    )


def _effective_purpose_length(text: str) -> int:
    return len(re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE))


def _system_prompt() -> str:
    room_text = json.dumps(ROOM_CATALOG, ensure_ascii=False)
    return f"""
你是笃学书院社区空间预约系统的审核器。用户会提交自然语言用途、人数、预约时间，
并且会从系统实时显示的空闲房间中主动选择一个房间。

你负责：意图识别、三级审核、动态时长建议，并判断用户选择的房间是否与用途/人数合理匹配。
房间实时是否空闲由后端硬规则再次校验，你不得假设被占用房间仍可使用。

必须严格返回一个 JSON 对象，不得输出 Markdown，不得夹带解释。字段：
{{
  "decision": "approve|reject|manual",
  "reason": "简洁中文理由",
  "guidance": "若 reject，给用户可执行的重填/改房建议；否则可为 null",
  "intent_type": "内部语义标签，例如 study/meeting/large_event/music/other",
  "candidate_rooms": ["A105", "A101"],
  "daily_limit_minutes": 720,
  "single_limit_minutes": 240,
  "confidence": 0-100
}}

审核规则：
1. 用途必须具体到足以判断真实需求。只有“开会”“自习”“讨论”“排练”“活动”等极短、缺少目的/内容的信息，必须 reject，提示补充具体用途。
2. 合情合理、用途明确、没有明显违规风险且房间选择合理：approve。
3. 明显乱码、恶意、违法违规、饮酒等不适合社区空间的用途：reject。
4. 模棱两可、特殊用途、风险边界不明确、无法可靠判断：manual。
5. 最终方案不要求固定场景按钮，不要因为用户没有预选场景而拒绝。
6. 时长动态判断，不使用统一 4 小时上限。自习类按合理需求可放宽到每日 12 小时；其他用途按实际合理性判断。
7. 时长必须为 30 分钟整数倍，daily_limit_minutes 与 single_limit_minutes 均在 30..1440 之间。
8. candidate_rooms 只能来自：{room_text}。应结合用途、人数、用户选择和当前空闲房间排序。
9. usage_mode=study 表示“自习共享”：只允许 A101/A102，且同一时段可与其他自习者共享；这种情况下不要因为房间已有自习而判冲突，后端会按座位容量和集中调剂规则最终分配。
10. usage_mode=exclusive 表示“非自习独占”：若用途本质上是自习，应 reject 并提示改用自习共享；若房间已有自习，则该房间对非自习用途封闭。
11. 会议确定性优先级：1-6 人优先 A102；7-10 人优先 A105，其次 A101；超过 10 人优先 A103。若更高优先级且适合的房间当前仍空闲，却选择较低优先级房间，应 reject。
12. 例如：10 人开会且 A105 空闲时选择 A103，应 reject；若适合人数规模的更优房间已占用，可使用下一顺位；20 人或 70 人以上会议选择 A103 属于合理方向。
13. confidence 表示判断把握度；低把握时优先 manual，不要冒险秒批。
""".strip()


def _normalize_minutes(value: object, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(30, min(24 * 60, number))
    return max(30, (number // 30) * 30)


def _extract_json(text: str) -> dict[str, object]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("AI 返回内容中没有 JSON 对象")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("AI 返回 JSON 不是对象")
    return parsed


def _normalize_result(data: dict[str, object], raw_json: str) -> AIAuditResult:
    decision = str(data.get("decision", "manual")).strip().lower()
    if decision not in {"approve", "reject", "manual"}:
        decision = "manual"

    raw_rooms = data.get("candidate_rooms")
    rooms: list[str] = []
    if isinstance(raw_rooms, list):
        for item in raw_rooms:
            code = str(item).upper().strip()
            if code in ROOM_CATALOG and code not in rooms:
                rooms.append(code)
    if not rooms:
        rooms = list(ROOM_CODES)

    try:
        confidence = int(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))

    reason = str(data.get("reason") or "AI 未给出明确理由").strip()[:2000]
    guidance_value = data.get("guidance")
    guidance = str(guidance_value).strip()[:2000] if guidance_value else None
    intent_type = str(data.get("intent_type") or "other").strip()[:64]

    if decision == "approve" and confidence < 60:
        decision = "manual"
        reason = f"AI 置信度较低（{confidence}），已转人工：{reason}"

    return AIAuditResult(
        decision=decision,  # type: ignore[arg-type]
        reason=reason,
        guidance=guidance,
        intent_type=intent_type,
        candidate_rooms=rooms,
        daily_limit_minutes=_normalize_minutes(data.get("daily_limit_minutes"), 12 * 60),
        single_limit_minutes=_normalize_minutes(data.get("single_limit_minutes"), 12 * 60),
        confidence=confidence,
        raw_json=raw_json[:12000],
    )


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def audit_booking_with_ai(
    *,
    purpose: str,
    people_count: int,
    start_iso: str,
    end_iso: str,
    selected_room: str,
    available_rooms: list[str],
    usage_mode: str = "exclusive",
) -> AIAuditResult:
    """调用 AI 完成三级分流，并由确定性规则复核房间选择。"""
    purpose = purpose.strip()
    selected_room = selected_room.upper().strip()
    available_rooms = [r for r in available_rooms if r in ROOM_CODES]
    usage_mode = "study" if usage_mode == "study" else "exclusive"

    # 先做确定性质量门槛，确保“开会”这类过短理由不会被模型偶然放行。
    if _effective_purpose_length(purpose) < 6:
        return _reject_result(
            "申请理由过于简单，无法判断真实用途",
            "请补充具体事项，例如会议主题、活动内容或学习任务后重新提交。",
            candidate_rooms=available_rooms,
        )

    if selected_room not in available_rooms:
        return _reject_result(
            f"所选房间 {selected_room} 在该时段已被占用",
            "请刷新当前时段的空闲房间后重新选择。",
            candidate_rooms=available_rooms,
        )

    if not settings.ai_api_key or not settings.ai_base_url or not settings.ai_model:
        return _manual_result("AI 服务未配置，已自动转人工审核", available_rooms)

    user_payload = {
        "purpose": purpose,
        "people_count": people_count,
        "start_time": start_iso,
        "end_time": end_iso,
        "selected_room": selected_room,
        "available_rooms": available_rooms,
        "usage_mode": usage_mode,
    }
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.ai_model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
            response = client.post(_chat_completions_url(settings.ai_base_url), headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("AI content 不是字符串")
        data = _extract_json(content)
        result = _normalize_result(data, json.dumps(data, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        return _manual_result(f"AI 审核暂不可用，已转人工：{type(exc).__name__}", available_rooms)

    normalized_intent = normalize_intent(result.intent_type)
    if usage_mode == "study":
        if normalized_intent != "study":
            return _reject_result(
                "所选预约方式为“自习共享”，但申请理由并非明确自习用途",
                "若是自习，请补充具体学习/复习任务；若为会议、活动等用途，请改选“非自习独占”。",
                candidate_rooms=[r for r in available_rooms if r in {"A101", "A102"}],
                intent_type=result.intent_type,
                confidence=max(result.confidence, 90),
            )
        result.candidate_rooms = [r for r in ("A102", "A101") if r in available_rooms]
        return result

    if normalized_intent == "study":
        return _reject_result(
            "自习用途应使用“自习共享”预约方式",
            "请返回预约页选择“自习共享”，系统会将自习同学集中调剂到 A101/A102。",
            candidate_rooms=[r for r in ("A102", "A101") if r in available_rooms],
            intent_type=result.intent_type,
            confidence=max(result.confidence, 90),
        )

    # 非自习继续执行房间优先级硬校验。
    issue = validate_room_choice(
        intent_type=result.intent_type,
        people_count=people_count,
        selected_room=selected_room,
        available_rooms=available_rooms,
    )
    if issue is not None:
        return _reject_result(
            issue.reason,
            issue.guidance,
            candidate_rooms=issue.recommended_rooms or result.candidate_rooms,
            intent_type=result.intent_type,
            confidence=max(result.confidence, 90),
        )

    priority = priority_rooms(result.intent_type, people_count)
    if priority:
        result.candidate_rooms = [r for r in priority if r in available_rooms] or result.candidate_rooms
    else:
        result.candidate_rooms = [r for r in result.candidate_rooms if r in available_rooms] or available_rooms
    return result
