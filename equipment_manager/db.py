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
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA wal_autocheckpoint = 1000")
        g.db = connection
    return g.db


def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_app_database() -> None:
    db = get_db()
    journal_mode = db.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(journal_mode).lower() != "wal":
        current_app.logger.warning(
            "SQLite WAL mode was not enabled; current mode is %s",
            journal_mode,
        )
    schema_path = Path(__file__).with_name("schema.sql")
    db.executescript(schema_path.read_text(encoding="utf-8"))
    _migrate_equipment_loan_periods(db)
    _migrate_transaction_due_dates(db)
    _backfill_active_loans(db)

    count = db.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
    if count == 0:
        now = utc_now()
        quantity = current_app.config["DEFAULT_QUANTITY"]
        db.executemany(
            """
            INSERT INTO equipment(
                name, total_qty, available_qty, loan_period_days, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    name,
                    quantity,
                    quantity,
                    current_app.config["DEFAULT_LOAN_DAYS"],
                    now,
                    now,
                )
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


def _migrate_equipment_loan_periods(db: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in db.execute("PRAGMA table_info(equipment)")}
    if "loan_period_days" not in columns:
        db.execute(
            "ALTER TABLE equipment "
            "ADD COLUMN loan_period_days INTEGER NOT NULL DEFAULT 7"
        )
        db.execute(
            "UPDATE equipment SET loan_period_days = ?",
            (current_app.config["DEFAULT_LOAN_DAYS"],),
        )


def _migrate_transaction_due_dates(db: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in db.execute("PRAGMA table_info(transactions)").fetchall()
    }
    if "due_date" not in columns:
        db.execute("ALTER TABLE transactions ADD COLUMN due_date TEXT")


def _backfill_active_loans(db: sqlite3.Connection) -> None:
    transaction_count = int(db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
    active_loan_count = int(db.execute("SELECT COUNT(*) FROM active_loans").fetchone()[0])
    if transaction_count == 0 or active_loan_count > 0:
        return

    rows = db.execute(
        """
        SELECT id, student_id, equipment_id, action, quantity, created_at, due_date
        FROM transactions
        WHERE reversed_at IS NULL
        ORDER BY created_at, id
        """
    )
    for row in rows:
        quantity = int(row["quantity"])
        if row["action"] == "loan":
            db.execute(
                """
                INSERT INTO active_loans(
                    loan_transaction_id, student_id, equipment_id,
                    original_quantity, remaining_quantity, due_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["student_id"],
                    row["equipment_id"],
                    quantity,
                    quantity,
                    row["due_date"],
                    row["created_at"],
                ),
            )
            continue

        remaining = quantity
        loans = db.execute(
            """
            SELECT loan_transaction_id, remaining_quantity
            FROM active_loans
            WHERE student_id = ? AND equipment_id = ? AND remaining_quantity > 0
            ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date, created_at
            """,
            (row["student_id"], row["equipment_id"]),
        ).fetchall()
        for loan in loans:
            allocated = min(remaining, int(loan["remaining_quantity"]))
            if allocated <= 0:
                continue
            db.execute(
                """
                UPDATE active_loans
                SET remaining_quantity = remaining_quantity - ?
                WHERE loan_transaction_id = ?
                """,
                (allocated, loan["loan_transaction_id"]),
            )
            db.execute(
                """
                INSERT INTO return_allocations(
                    return_transaction_id, loan_transaction_id, quantity
                ) VALUES (?, ?, ?)
                """,
                (row["id"], loan["loan_transaction_id"], allocated),
            )
            remaining -= allocated
            if remaining == 0:
                break
        if remaining > 0:
            current_app.logger.warning(
                "Could not match %s legacy return item(s) for transaction %s",
                remaining,
                row["id"],
            )


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
