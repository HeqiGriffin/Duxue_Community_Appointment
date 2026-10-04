"""极小型兼容迁移：只处理本项目当前新增字段，避免覆盖现有 SQLite 数据。"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "bookings" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("bookings")}
            if "requested_room_code" not in columns:
                conn.execute(text("ALTER TABLE bookings ADD COLUMN requested_room_code VARCHAR(32)"))

        if "appeals" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("appeals")}
            if "appeal_type" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE appeals ADD COLUMN appeal_type VARCHAR(32) "
                        "NOT NULL DEFAULT 'ACCOUNT'"
                    )
                )
