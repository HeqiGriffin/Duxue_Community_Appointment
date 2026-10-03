"""AI 预约审核与房间推荐。

最终方案要求：前端只填写自然语言用途，由 AI 做“秒批 / 打回 / 存疑转交”三级分流，
同时输出候选房间与动态时长。这里兼容 OpenAI 风格的 /chat/completions 接口。
若 AI 未配置或调用失败，系统不会擅自自动放行，而是安全地转人工审核。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

from config import settings

Decision = Literal["approve", "reject", "manual"]

# 房间信息来自当前方案/参考需求中已经出现的空间。固定“场景按钮”已取消，下面仅作为
# AI 分配资源时的能力提示，不会要求用户先选类别。
ROOM_CATALOG: dict[str, dict[str, object]] = {
    "A101": {"capacity_hint": 10, "suitable": ["自习", "会议", "通用活动"]},
    "A102": {"capacity_hint": 6, "suitable": ["自习", "小型会议"]},
    "A103": {"capacity_hint": None, "suitable": ["大型活动", "钢琴/音乐活动"]},
    "A105": {"capacity_hint": 10, "suitable": ["会议", "自习", "通用活动"]},
    "B102": {"capacity_hint": None, "suitable": ["音乐练习"]},
}
ROOM_CODES = tuple(ROOM_CATALOG.keys())


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


def _manual_result(reason: str) -> AIAuditResult:
    return AIAuditResult(
        decision="manual",
        reason=reason,
        guidance=None,
        intent_type="uncertain",
        candidate_rooms=list(ROOM_CODES),
        # 未得到可靠 AI 结论时不给出旧版 4h 限制；使用 24h 作为技术上限，最终由人工审批。
        daily_limit_minutes=24 * 60,
        single_limit_minutes=24 * 60,
        confidence=0,
    )


def _system_prompt() -> str:
    room_text = json.dumps(ROOM_CATALOG, ensure_ascii=False)
    return f"""
你是笃学书院社区空间预约系统的审核器。用户不会选择固定场景，只会提交自然语言用途、人数和时间。
你的任务是同时完成：意图识别、三级审核、候选房间排序、动态时长建议。

必须严格返回一个 JSON 对象，不得输出 Markdown，不得夹带解释。字段：
{{
  "decision": "approve|reject|manual",
  "reason": "简洁中文理由",
  "guidance": "若 reject，给用户可执行的重填建议；否则可为 null",
  "intent_type": "内部语义标签，例如 study/meeting/large_event/music/other",
  "candidate_rooms": ["A102", "A101"],
  "daily_limit_minutes": 720,
  "single_limit_minutes": 240,
  "confidence": 0-100
}}

审核规则：
1. 合情合理、用途明确、没有明显违规风险：approve。
2. 明显乱码、恶意/违规用途、几乎没有有效信息且无法判断真实用途：reject，并给出重填建议。
3. 模棱两可、特殊用途、风险边界不明确、你无法可靠判断：manual，交管理员处理。
4. 不要因为旧版固定场景而拒绝用户；最终方案已取消前端固定场景分类。
5. 时长采用动态策略，不得套用统一 4 小时上限。自习类可以按需求放宽到每日 12 小时；其他用途按实际合理性给出限制。
6. 所有时长必须为 30 分钟的整数倍，daily_limit_minutes 与 single_limit_minutes 均在 30..1440 之间。
7. candidate_rooms 必须只从以下房间中选择，按推荐优先级排列：{room_text}
8. 人数明显超过某房间 capacity_hint 时，不应优先推荐该房间；capacity_hint 为 null 表示这里没有可靠人数上限信息，不要自行虚构。
9. confidence 是你对本次判断的把握度；低把握时优先 manual，不要冒险秒批。
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

    # 低置信度即使模型声称 approve，也转人工，避免模型不确定时错误放行。
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


def audit_booking_with_ai(*, purpose: str, people_count: int, start_iso: str, end_iso: str) -> AIAuditResult:
    """调用 AI 完成三级分流。

    AI 配置缺失/超时/格式异常时一律转人工，不让第三方服务故障演变成自动放行。
    """
    if not settings.ai_api_key or not settings.ai_base_url or not settings.ai_model:
        return _manual_result("AI 服务未配置，已自动转人工审核")

    user_payload = {
        "purpose": purpose.strip(),
        "people_count": people_count,
        "start_time": start_iso,
        "end_time": end_iso,
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
        with httpx.Client(timeout=15.0) as client:
            response = client.post(_chat_completions_url(settings.ai_base_url), headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("AI content 不是字符串")
        data = _extract_json(content)
        return _normalize_result(data, json.dumps(data, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - 外部 AI 故障必须安全降级
        return _manual_result(f"AI 审核暂不可用，已转人工：{type(exc).__name__}")
