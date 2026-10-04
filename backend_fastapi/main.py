"""FastAPI 程序入口。第二阶段接入预约 AI 审核、并发占房和定时任务。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from api.auth import router as auth_router
from api.booking import router as booking_router
from api.checkin import router as checkin_router
from api.upload_ocr import router as cleanup_router
from api.appeal import router as appeal_router
from api.duty import router as duty_router
from config import Base, SessionLocal, engine, settings
from core.scheduler import start_scheduler, stop_scheduler
from models.appeals import Appeal  # noqa: F401 - 导入以注册 SQLAlchemy metadata
from models.bookings import Booking, BookingSlotLock  # noqa: F401
from models.users import User, UserRole
from utils.schema import ensure_schema
from utils.security import hash_password


def bootstrap_admin() -> None:
    """可选的本地初始化管理员；没有配置环境变量时完全不执行。"""
    if not settings.bootstrap_admin_id or not settings.bootstrap_admin_password:
        return

    with SessionLocal() as db:
        exists = db.scalar(select(User).where(User.login_id == settings.bootstrap_admin_id))
        if exists:
            return
        db.add(
            User(
                login_id=settings.bootstrap_admin_id,
                name=settings.bootstrap_admin_name,
                role=UserRole.ADMIN,
                password_hash=hash_password(settings.bootstrap_admin_password),
                must_change_password=True,
            )
        )
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    bootstrap_admin()
    start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    version="0.6.0",
    lifespan=lifespan,
)

if settings.parsed_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.parsed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(booking_router, prefix=settings.api_prefix)
app.include_router(checkin_router, prefix=settings.api_prefix)
app.include_router(cleanup_router, prefix=settings.api_prefix)
app.include_router(appeal_router, prefix=settings.api_prefix)
app.include_router(duty_router, prefix=settings.api_prefix)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "backend_fastapi", "version": "0.6.0"}
