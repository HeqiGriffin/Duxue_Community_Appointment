"""极小型兼容迁移：仅补充当前版本新增字段，不覆盖已有 SQLite 数据。"""
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
            if "usage_mode" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE bookings ADD COLUMN usage_mode VARCHAR(16) "
                        "NOT NULL DEFAULT 'exclusive'"
                    )
                )
                # 尽量识别旧版自习预约，避免升级后被误判为独占。
                conn.execute(
                    text(
                        "UPDATE bookings SET usage_mode='study' "
                        "WHERE lower(coalesce(intent_type,'')) LIKE '%study%' "
                        "OR purpose LIKE '%自习%' OR purpose LIKE '%复习%' "
                        "OR purpose LIKE '%学习%' OR purpose LIKE '%备考%'"
                    )
                )

        if "appeals" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("appeals")}
            if "appeal_type" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE appeals ADD COLUMN appeal_type VARCHAR(32) "
                        "NOT NULL DEFAULT 'ACCOUNT'"
                    )
                )

        if "duty_logs" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("duty_logs")}
            if "handover_at" not in columns:
                conn.execute(text("ALTER TABLE duty_logs ADD COLUMN handover_at DATETIME"))

        # v0.5 时代的自习预约曾创建独占 slot lock。升级后自习允许共享，必须清掉这些旧锁。
        refreshed_tables = set(inspect(engine).get_table_names())
        if "booking_slot_locks" in refreshed_tables and "bookings" in refreshed_tables:
            booking_columns = {c["name"] for c in inspect(engine).get_columns("bookings")}
            if "usage_mode" in booking_columns:
                conn.execute(
                    text(
                        "DELETE FROM booking_slot_locks "
                        "WHERE booking_id IN (SELECT id FROM bookings WHERE usage_mode='study')"
                    )
                )
