"""i大工门禁代理：仅在有效预约时段内代取动态二维码。"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import require_normal_account
from config import get_db, settings
from models.bookings import Booking, BookingStatus
from models.users import User
from utils.time_calc import APP_TZ, ensure_local

router = APIRouter(prefix="/door", tags=["door"])


class DoorQrResponse(BaseModel):
    booking_id: int
    room_code: str
    content_type: str
    qr_base64: str
    fetched_at: datetime


def _validate_base64(candidate: str) -> tuple[str, str] | None:
    value = candidate.strip().replace("\\/", "/")
    content_type = "image/png"
    if value.startswith("data:image/"):
        match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.+)", value, flags=re.S)
        if not match:
            return None
        content_type = match.group(1)
        value = match.group(2)
    value = re.sub(r"\s+", "", value)
    if len(value) < 80:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:  # noqa: BLE001
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        content_type = "image/jpeg"
    elif raw[:4] in {b"RIFF"}:
        content_type = "image/webp"
    elif not content_type.startswith("image/"):
        return None
    return content_type, value


def extract_qr_base64(text: str) -> tuple[str, str]:
    """兼容抓包中出现过的 HTML hidden input、data URI 与 JSON 字段。"""
    patterns = [
        r'''(?:id|name)=["'](?:qrcode|qrCode|paycode)["'][^>]*value=["']([^"']+)["']''',
        r'''value=["']([^"']+)["'][^>]*(?:id|name)=["'](?:qrcode|qrCode|paycode)["']''',
        r'''src=["'](data:image/[^"']+;base64,[^"']+)["']''',
        r'''["'](?:qrcode|qrCode|qr_code|paycode|image)["']\s*:\s*["']([^"']+)["']''',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            valid = _validate_base64(match.group(1))
            if valid:
                return valid

    # 最后兜底：寻找足够长、看起来像 PNG/JPEG Base64 的连续串。
    for match in re.finditer(r"(?:iVBORw0KGgo|/9j/)[A-Za-z0-9+/=]{100,}", text):
        valid = _validate_base64(match.group(0))
        if valid:
            return valid
    raise ValueError("响应中未找到可用的二维码 Base64")


def fetch_idut_qr() -> tuple[str, str]:
    if not settings.idut_qr_url or not settings.idut_cookie:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="门禁代理尚未配置 IDUT_QR_URL / IDUT_COOKIE",
        )
    headers = {
        "Cookie": settings.idut_cookie,
        "User-Agent": settings.idut_user_agent,
        "Referer": settings.idut_referer,
        "Accept": "application/json,text/html,*/*",
    }
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            response = client.get(settings.idut_qr_url, headers=headers)
            response.raise_for_status()
            return extract_qr_base64(response.text)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"i大工动态二维码获取失败：{type(exc).__name__}",
        ) from exc


@router.post("/{booking_id}/checkin", response_model=DoorQrResponse)
def checkin_and_get_qr(
    booking_id: int,
    user: Annotated[User, Depends(require_normal_account)],
    db: Annotated[Session, Depends(get_db)],
) -> DoorQrResponse:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")
    if booking.status not in {BookingStatus.APPROVED, BookingStatus.ACTIVE}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前预约状态不可签到开门")
    if not booking.room_code:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="预约尚未分配房间")

    now = datetime.now(APP_TZ)
    if not (ensure_local(booking.start_time) <= now < ensure_local(booking.end_time)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅可在预约有效时段内签到开门")

    content_type, qr_base64 = fetch_idut_qr()
    if booking.checked_in_at is None:
        booking.checked_in_at = datetime.now(timezone.utc)
    booking.status = BookingStatus.ACTIVE
    db.add(booking)
    db.commit()

    return DoorQrResponse(
        booking_id=booking.id,
        room_code=booking.room_code,
        content_type=content_type,
        qr_base64=qr_base64,
        fetched_at=datetime.now(timezone.utc),
    )
