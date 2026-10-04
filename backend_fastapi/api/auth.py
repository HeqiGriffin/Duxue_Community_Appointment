"""白名单鉴权、双角色识别与终端模式判定。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_db, settings
from models.users import User, UserRole, UserStatus
from utils.security import create_access_token, decode_access_token, hash_password, secure_equals, validate_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    login_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    login_id: str
    name: str
    role: UserRole
    account_status: UserStatus
    mode: Literal["regular", "admin", "duty"]
    must_change_password: bool
    can_book: bool
    can_checkin: bool




class AdminUserItem(BaseModel):
    id: int
    login_id: str
    name: str
    class_name: str | None
    phone: str | None
    role: UserRole
    account_status: UserStatus
    is_active: bool
    must_change_password: bool
    frozen_reason: str | None
    frozen_at: datetime | None


class AdminUserStatusRequest(BaseModel):
    action: Literal["freeze", "unfreeze"]
    reason: str | None = Field(default=None, max_length=2000)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=2)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        try:
            validate_password(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return value


class MeResponse(BaseModel):
    user_id: int
    login_id: str
    name: str
    role: UserRole
    account_status: UserStatus
    mode: Literal["regular", "admin", "duty"]
    must_change_password: bool
    can_book: bool
    can_checkin: bool


def _is_duty_terminal(request: Request, terminal_token: str | None) -> bool:
    if terminal_token and settings.duty_terminal_token:
        if secure_equals(terminal_token, settings.duty_terminal_token):
            return True

    if request.client and request.client.host in settings.parsed_duty_terminal_ips:
        return True
    return False


def resolve_mode(user: User, request: Request, terminal_token: str | None) -> Literal["regular", "admin", "duty"]:
    if user.role == UserRole.ADMIN:
        return "admin"
    if _is_duty_terminal(request, terminal_token):
        return "duty"
    return "regular"


def _capabilities(user: User) -> tuple[bool, bool]:
    allowed = user.is_active and user.status == UserStatus.NORMAL and not user.must_change_password
    return allowed, allowed


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在或已停用")
    return user


def require_password_changed(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="首次登录必须先修改密码")
    return user


def require_normal_account(user: Annotated[User, Depends(require_password_changed)]) -> User:
    if user.status == UserStatus.FROZEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已冻结，请先提交线上申诉")
    return user


def require_admin(user: Annotated[User, Depends(require_password_changed)]) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可访问")
    return user


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_duty_terminal_token: Annotated[str | None, Header(alias="X-Duty-Terminal-Token")] = None,
) -> LoginResponse:
    user = db.scalar(select(User).where(User.login_id == payload.login_id))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")

    token = create_access_token(
        user_id=user.id,
        login_id=user.login_id,
        role=user.role.value,
        must_change_password=user.must_change_password,
    )
    mode = resolve_mode(user, request, x_duty_terminal_token)
    can_book, can_checkin = _capabilities(user)
    return LoginResponse(
        access_token=token,
        user_id=user.id,
        login_id=user.login_id,
        name=user.name,
        role=user.role,
        account_status=user.status,
        mode=mode,
        must_change_password=user.must_change_password,
        can_book=can_book,
        can_checkin=can_checkin,
    )


@router.post("/change-password", response_model=LoginResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    x_duty_terminal_token: Annotated[str | None, Header(alias="X-Duty-Terminal-Token")] = None,
) -> LoginResponse:
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码错误")
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与原密码相同")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=user.id,
        login_id=user.login_id,
        role=user.role.value,
        must_change_password=False,
    )
    mode = resolve_mode(user, request, x_duty_terminal_token)
    can_book, can_checkin = _capabilities(user)
    return LoginResponse(
        access_token=token,
        user_id=user.id,
        login_id=user.login_id,
        name=user.name,
        role=user.role,
        account_status=user.status,
        mode=mode,
        must_change_password=False,
        can_book=can_book,
        can_checkin=can_checkin,
    )


@router.get("/me", response_model=MeResponse)
def me(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    x_duty_terminal_token: Annotated[str | None, Header(alias="X-Duty-Terminal-Token")] = None,
) -> MeResponse:
    mode = resolve_mode(user, request, x_duty_terminal_token)
    can_book, can_checkin = _capabilities(user)
    return MeResponse(
        user_id=user.id,
        login_id=user.login_id,
        name=user.name,
        role=user.role,
        account_status=user.status,
        mode=mode,
        must_change_password=user.must_change_password,
        can_book=can_book,
        can_checkin=can_checkin,
    )


@router.get("/terminal-status")
def terminal_status(
    request: Request,
    _: Annotated[User, Depends(require_password_changed)],
    x_duty_terminal_token: Annotated[str | None, Header(alias="X-Duty-Terminal-Token")] = None,
) -> dict[str, bool]:
    """供管理员在值班电脑上验证浏览器是否已绑定值班终端 Token。"""
    return {"is_duty_terminal": _is_duty_terminal(request, x_duty_terminal_token)}


@router.get("/admin/users", response_model=list[AdminUserItem])
def admin_users(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str | None, Query(max_length=128)] = None,
    role: Annotated[str | None, Query()] = None,
    account_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[AdminUserItem]:
    stmt = select(User)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(
            (User.login_id.ilike(keyword))
            | (User.name.ilike(keyword))
            | (User.class_name.ilike(keyword))
        )
    if role:
        try:
            stmt = stmt.where(User.role == UserRole(role))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知用户角色") from exc
    if account_status:
        try:
            stmt = stmt.where(User.status == UserStatus(account_status))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未知账号状态") from exc

    rows = db.scalars(stmt.order_by(User.role.desc(), User.login_id.asc()).limit(limit)).all()
    return [
        AdminUserItem(
            id=x.id,
            login_id=x.login_id,
            name=x.name,
            class_name=x.class_name,
            phone=x.phone,
            role=x.role,
            account_status=x.status,
            is_active=x.is_active,
            must_change_password=x.must_change_password,
            frozen_reason=x.frozen_reason,
            frozen_at=x.frozen_at,
        )
        for x in rows
    ]


@router.post("/admin/users/{user_id}/status", response_model=AdminUserItem)
def admin_set_user_status(
    user_id: int,
    payload: AdminUserStatusRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> AdminUserItem:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if target.role == UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="管理员账号状态不可通过该接口修改")
    if payload.action == "freeze":
        reason = (payload.reason or "管理员手动冻结").strip()
        target.status = UserStatus.FROZEN
        target.frozen_reason = reason
        target.frozen_at = datetime.now(timezone.utc)
    else:
        target.status = UserStatus.NORMAL
        target.frozen_reason = None
        target.frozen_at = None
    db.add(target)
    db.commit()
    db.refresh(target)
    return AdminUserItem(
        id=target.id,
        login_id=target.login_id,
        name=target.name,
        class_name=target.class_name,
        phone=target.phone,
        role=target.role,
        account_status=target.status,
        is_active=target.is_active,
        must_change_password=target.must_change_password,
        frozen_reason=target.frozen_reason,
        frozen_at=target.frozen_at,
    )
