"""全局配置与数据库连接。

第一阶段仅使用环境变量，不把数据库密码、AI Key、i大工 Cookie 等敏感信息写进代码。
默认数据库为 SQLite，部署时可通过 DATABASE_URL 切换为 MySQL/PostgreSQL。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "笃学书院社区空间预约管理系统")
    app_env: str = os.getenv("APP_ENV", "development")
    api_prefix: str = os.getenv("API_PREFIX", "/api")

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./duxue_appointment.db")

    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-me-before-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "720"))

    # 值班电脑识别：优先使用浏览器保存的专属 Token；固定 IP 仅作为可选补充。
    duty_terminal_token: str = os.getenv("DUTY_TERMINAL_TOKEN", "")
    duty_terminal_ips: str = os.getenv("DUTY_TERMINAL_IPS", "")

    # 第二阶段会实际使用这些配置。
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_base_url: str = os.getenv("AI_BASE_URL", "")
    ai_model: str = os.getenv("AI_MODEL", "")
    idut_cookie: str = os.getenv("IDUT_COOKIE", "")
    # i大工动态二维码实际接口由部署环境注入；不把抓包地址或 Cookie 写死在仓库。
    idut_qr_url: str = os.getenv("IDUT_QR_URL", "")
    idut_referer: str = os.getenv("IDUT_REFERER", "https://card.m.dlut.edu.cn/")
    idut_user_agent: str = os.getenv(
        "IDUT_USER_AGENT",
        "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
    )

    # OCR 可接学校已有 OCR、云 OCR 或自建兼容服务。未配置时照片仍会收件，但转人工核验。
    ocr_api_url: str = os.getenv("OCR_API_URL", "")
    ocr_api_key: str = os.getenv("OCR_API_KEY", "")
    upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))

    # 可选：首次启动时自动写入一个管理员白名单账号，方便本地联调。
    bootstrap_admin_id: str = os.getenv("BOOTSTRAP_ADMIN_ID", "")
    bootstrap_admin_name: str = os.getenv("BOOTSTRAP_ADMIN_NAME", "系统管理员")
    bootstrap_admin_password: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")

    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

    @property
    def parsed_duty_terminal_ips(self) -> set[str]:
        return {item.strip() for item in self.duty_terminal_ips.split(",") if item.strip()}

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


settings = Settings()


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
