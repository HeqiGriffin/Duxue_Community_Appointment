"""离场现场照片上传与 OCR 容错核验。"""
from __future__ import annotations

import base64
import io
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_admin, require_password_changed
from config import get_db, settings
from models.bookings import Booking, BookingStatus
from models.users import User, UserStatus
from utils.time_calc import APP_TZ, cleanup_deadline, cleanup_window_start, ensure_local

router = APIRouter(prefix="/cleanup", tags=["cleanup"])
ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class CleanupUploadResponse(BaseModel):
    booking_id: int
    status: BookingStatus
    review_status: str
    ocr_text: str | None
    id_distance: int | None
    uploaded_at: datetime


class CleanupCloudUploadRequest(BaseModel):
    temp_url: str = Field(min_length=8, max_length=4096)
    camera_source: str = "camera"


class CleanupReviewRequest(BaseModel):
    action: Literal["pass", "reject"]
    comment: str = Field(min_length=1, max_length=2000)


class CleanupPendingItem(BaseModel):
    booking_id: int
    user_id: int
    login_id: str
    name: str
    room_code: str | None
    photo_url: str
    ocr_result: str | None
    review_status: str


class CleanupPhotoDataResponse(BaseModel):
    content_type: str
    base64_data: str


def _edit_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _extract_best_student_id(text: str, expected: str) -> tuple[str | None, int | None]:
    expected_digits = re.sub(r"\D", "", expected)
    if not expected_digits:
        return None, None
    candidates = re.findall(r"\d{5,20}", text)
    if not candidates:
        return None, None
    best = min(candidates, key=lambda x: _edit_distance(x, expected_digits))
    return best, _edit_distance(best, expected_digits)


def _call_ocr(image_bytes: bytes, filename: str, content_type: str) -> str | None:
    if not settings.ocr_api_url:
        return None
    headers = {}
    if settings.ocr_api_key:
        headers["Authorization"] = f"Bearer {settings.ocr_api_key}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                settings.ocr_api_url,
                headers=headers,
                files={"file": (filename, image_bytes, content_type)},
            )
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict):
            for key in ("text", "result", "ocr_text", "content"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value
            data = payload.get("data")
            if isinstance(data, dict):
                for key in ("text", "result", "ocr_text", "content"):
                    value = data.get(key)
                    if isinstance(value, str):
                        return value
        return json.dumps(payload, ensure_ascii=False)[:8000]
    except Exception:  # noqa: BLE001 - OCR 故障不应阻止学生按时提交照片
        return None


def _save_image(image_bytes: bytes, suffix: str, booking_id: int) -> str:
    upload_root = Path(settings.upload_dir).resolve()
    target_dir = upload_root / "cleanup" / datetime.now(APP_TZ).strftime("%Y%m%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"booking_{booking_id}_{uuid.uuid4().hex}{suffix}"
    target.write_bytes(image_bytes)
    return str(target)


def _validate_cleanup_window(booking: Booking) -> None:
    now = datetime.now(APP_TZ)
    window_start = cleanup_window_start(booking.end_time)
    deadline = cleanup_deadline(booking.end_time)
    if now < window_start:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="离场实拍将在预约结束前 30 分钟开放",
        )
    if now > deadline:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已超过离场实拍提交时限（预约结束后 30 分钟）",
        )


def _photo_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        suffix, "application/octet-stream"
    )


@router.get("/{booking_id}/photo-data", response_model=CleanupPhotoDataResponse)
def get_own_cleanup_photo_data(
    booking_id: int,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> CleanupPhotoDataResponse:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")
    if not booking.cleanup_photo_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未提交离场照片")
    path = Path(booking.cleanup_photo_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="离场照片文件不存在")
    # 小程序通过 AnyService 读取预览图；为避免原图过大导致网关响应超限，
    # 这里生成最长边 1280px 的 JPEG 预览，服务器仍保留原始上传文件。
    try:
        with Image.open(path) as image:
            image.thumbnail((1280, 1280))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
            preview = output.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="生成照片预览失败") from exc
    return CleanupPhotoDataResponse(
        content_type="image/jpeg",
        base64_data=base64.b64encode(preview).decode("ascii"),
    )


@router.post("/{booking_id}", response_model=CleanupUploadResponse)
async def upload_cleanup_photo(
    booking_id: int,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
    photo: UploadFile = File(...),
    camera_source: str = Form(default="camera"),
) -> CleanupUploadResponse:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="预约不存在")
    if booking.status not in {BookingStatus.ACTIVE, BookingStatus.AWAITING_CLEANUP}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前预约状态不可提交离场照片")
    _validate_cleanup_window(booking)
    if camera_source != "camera":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="客户端必须使用实时相机拍摄")

    content_type = (photo.content_type or "").lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="仅支持 JPEG/PNG/WebP 图片")
    image_bytes = await photo.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(image_bytes) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="照片文件过大")
    try:
        Image.open(io.BytesIO(image_bytes)).verify()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="上传文件不是有效图片") from exc

    path = _save_image(image_bytes, ALLOWED_MIME[content_type], booking.id)
    ocr_text = _call_ocr(image_bytes, photo.filename or "cleanup.jpg", content_type)
    recognized, distance = _extract_best_student_id(ocr_text or "", user.login_id)

    if ocr_text is None:
        review_status = "manual_required"
        ocr_result = json.dumps({"status": "ocr_unavailable", "recognized": None}, ensure_ascii=False)
    elif distance is not None and distance <= 1:
        review_status = "auto_pass"
        ocr_result = json.dumps(
            {"status": "matched", "recognized": recognized, "distance": distance, "text": ocr_text[:5000]},
            ensure_ascii=False,
        )
    else:
        review_status = "manual_required"
        ocr_result = json.dumps(
            {"status": "mismatch", "recognized": recognized, "distance": distance, "text": ocr_text[:5000]},
            ensure_ascii=False,
        )

    now_utc = datetime.now(timezone.utc)
    booking.cleanup_photo_path = path
    booking.ocr_result = ocr_result
    booking.cleanup_review_status = review_status
    booking.checked_out_at = now_utc
    booking.cleanup_deadline_at = booking.cleanup_deadline_at or cleanup_deadline(booking.end_time)
    booking.status = BookingStatus.COMPLETED
    db.add(booking)
    db.commit()

    return CleanupUploadResponse(
        booking_id=booking.id,
        status=booking.status,
        review_status=review_status,
        ocr_text=ocr_text,
        id_distance=distance,
        uploaded_at=now_utc,
    )


@router.post("/{booking_id}/cloud", response_model=CleanupUploadResponse)
def upload_cleanup_photo_cloud(
    booking_id: int,
    payload: CleanupCloudUploadRequest,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[Session, Depends(get_db)],
) -> CleanupUploadResponse:
    """接收 CloudBase 云存储临时 URL，并保存为正式离场照片。"""

    booking = db.get(Booking, booking_id)

    if booking is None or booking.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="预约不存在",
        )

    if booking.status not in {
        BookingStatus.ACTIVE,
        BookingStatus.AWAITING_CLEANUP,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前预约状态不可提交离场照片",
        )

    _validate_cleanup_window(booking)

    if payload.camera_source != "camera":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="客户端必须使用实时相机拍摄",
        )

    # 只允许腾讯云存储 HTTPS 临时地址，避免任意 URL / SSRF。
    parsed = urlparse(payload.temp_url)
    host = (parsed.hostname or "").lower()

    allowed_host = (
        host.endswith(".tcb.qcloud.la")
        or host.endswith(".myqcloud.com")
    )

    if parsed.scheme != "https" or not allowed_host:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="不是受信任的 CloudBase 临时文件地址",
        )

    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0, connect=5.0),
            follow_redirects=True,
        ) as client:
            response = client.get(payload.temp_url)
            response.raise_for_status()
            image_bytes = response.content
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="读取云端临时照片失败",
        ) from exc

    max_bytes = settings.max_upload_mb * 1024 * 1024

    if len(image_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="照片文件过大",
        )

    # 不信任 URL 后缀或 Content-Type，直接读取真实图片格式。
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image_format = (image.format or "").upper()
        image.verify()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="云端文件不是有效图片",
        ) from exc

    image_types = {
        "JPEG": ("image/jpeg", ".jpg"),
        "PNG": ("image/png", ".png"),
        "WEBP": ("image/webp", ".webp"),
    }

    detected = image_types.get(image_format)

    if detected is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 JPEG/PNG/WebP 图片",
        )

    content_type, suffix = detected

    path = _save_image(
        image_bytes,
        suffix,
        booking.id,
    )

    ocr_text = _call_ocr(
        image_bytes,
        f"cleanup{suffix}",
        content_type,
    )

    recognized, distance = _extract_best_student_id(
        ocr_text or "",
        user.login_id,
    )

    if ocr_text is None:
        review_status = "manual_required"
        ocr_result = json.dumps(
            {
                "status": "ocr_unavailable",
                "recognized": None,
            },
            ensure_ascii=False,
        )

    elif distance is not None and distance <= 1:
        review_status = "auto_pass"
        ocr_result = json.dumps(
            {
                "status": "matched",
                "recognized": recognized,
                "distance": distance,
                "text": ocr_text[:5000],
            },
            ensure_ascii=False,
        )

    else:
        review_status = "manual_required"
        ocr_result = json.dumps(
            {
                "status": "mismatch",
                "recognized": recognized,
                "distance": distance,
                "text": ocr_text[:5000],
            },
            ensure_ascii=False,
        )

    now_utc = datetime.now(timezone.utc)

    booking.cleanup_photo_path = path
    booking.ocr_result = ocr_result
    booking.cleanup_review_status = review_status
    booking.checked_out_at = now_utc

    booking.cleanup_deadline_at = (
        booking.cleanup_deadline_at
        or cleanup_deadline(booking.end_time)
    )

    # 上传成功立即完成闭环并解除下一次预约限制。
    # 管理员后续审核不合格时再冻结。
    booking.status = BookingStatus.COMPLETED

    db.add(booking)
    db.commit()
    db.refresh(booking)

    return CleanupUploadResponse(
        booking_id=booking.id,
        status=booking.status,
        review_status=review_status,
        ocr_text=ocr_text,
        id_distance=distance,
        uploaded_at=now_utc,
    )


@router.get("/admin/pending", response_model=list[CleanupPendingItem])
def cleanup_pending(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[CleanupPendingItem]:
    rows = db.execute(
        select(Booking, User)
        .join(User, User.id == Booking.user_id)
        .where(Booking.cleanup_review_status == "manual_required")
        .order_by(Booking.checked_out_at.asc())
    ).all()
    return [
        CleanupPendingItem(
            booking_id=b.id,
            user_id=u.id,
            login_id=u.login_id,
            name=u.name,
            room_code=b.room_code,
            photo_url=f"/api/cleanup/admin/{b.id}/photo",
            ocr_result=b.ocr_result,
            review_status=b.cleanup_review_status or "manual_required",
        )
        for b, u in rows
    ]


@router.get("/admin/{booking_id}/photo")
def get_cleanup_photo(
    booking_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    booking = db.get(Booking, booking_id)
    if booking is None or not booking.cleanup_photo_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="清扫照片不存在")
    path = Path(booking.cleanup_photo_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="清扫照片文件不存在")
    return FileResponse(path)


@router.post("/admin/{booking_id}/review", response_model=CleanupUploadResponse)
def review_cleanup(
    booking_id: int,
    payload: CleanupReviewRequest,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> CleanupUploadResponse:
    booking = db.get(Booking, booking_id)
    if booking is None or not booking.cleanup_photo_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待核验照片不存在")

    if payload.action == "pass":
        booking.cleanup_review_status = "admin_pass"
        booking.cleanup_review_note = payload.comment
    else:
        booking.cleanup_review_status = "admin_reject"
        booking.cleanup_review_note = payload.comment
        booking.is_violation = True
        booking.violation_reason = payload.comment
        user = db.get(User, booking.user_id)
        if user is not None:
            user.status = UserStatus.FROZEN
            user.frozen_at = datetime.now(timezone.utc)
            user.frozen_reason = f"预约 #{booking.id} 离场清理核验不合格：{payload.comment}"
            db.add(user)
    db.add(booking)
    db.commit()
    return CleanupUploadResponse(
        booking_id=booking.id,
        status=booking.status,
        review_status=booking.cleanup_review_status or "",
        ocr_text=None,
        id_distance=None,
        uploaded_at=booking.checked_out_at or datetime.now(timezone.utc),
    )
