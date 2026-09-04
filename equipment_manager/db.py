from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app, g


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        database_path = Path(current_app.config["DATABASE"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        g.db = connection
    return g.db


def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_app_database() -> None:
    db = get_db()
    schema_path = Path(__file__).with_name("schema.sql")
    db.executescript(schema_path.read_text(encoding="utf-8"))

    count = db.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
    if count == 0:
        now = utc_now()
        quantity = current_app.config["DEFAULT_QUANTITY"]
        db.executemany(
            """
            INSERT INTO equipment(name, total_qty, available_qty, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (name, quantity, quantity, now, now)
                for name in current_app.config["DEFAULT_EQUIPMENT"]
            ],
        )

    model_path = Path(current_app.config["YOLO_MODEL_PATH"])
    db.execute(
        """
        INSERT INTO device_status(id, device_name, detector_mode, model_name, last_seen, last_error)
        VALUES (1, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
            device_name = excluded.device_name,
            detector_mode = excluded.detector_mode,
            model_name = excluded.model_name,
            last_seen = excluded.last_seen
        """,
        (
            current_app.config["DEVICE_NAME"],
            current_app.config["DETECTOR_MODE"],
            model_path.name,
            utc_now(),
        ),
    )
    db.commit()


_UNCHANGED = object()


def set_device_status(error: str | None | object = _UNCHANGED) -> None:
    db = get_db()
    if error is _UNCHANGED:
        db.execute("UPDATE device_status SET last_seen = ? WHERE id = 1", (utc_now(),))
    else:
        safe_error = None if error is None else str(error)[:500]
        db.execute(
            "UPDATE device_status SET last_seen = ?, last_error = ? WHERE id = 1",
            (utc_now(), safe_error),
        )
    db.commit()


def cleanup_expired_scan_sessions(retention_hours: int = 24) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).isoformat(
        timespec="seconds"
    )
    db = get_db()
    result = db.execute(
        "DELETE FROM scan_sessions WHERE expires_at < ? OR consumed_at < ?",
        (cutoff, cutoff),
    )
    db.commit()
    return result.rowcount
