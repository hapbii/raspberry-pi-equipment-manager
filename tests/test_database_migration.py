from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from equipment_manager import create_app
from equipment_manager.db import _backfill_active_loans, get_db


OLD_SCHEMA = """
CREATE TABLE equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    total_qty INTEGER NOT NULL, available_qty INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE scan_sessions (
    token TEXT PRIMARY KEY, equipment_id INTEGER NOT NULL, confidence REAL NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, consumed_at TEXT
);
CREATE TABLE transactions (
    id TEXT PRIMARY KEY, student_id TEXT NOT NULL, equipment_id INTEGER NOT NULL,
    action TEXT NOT NULL, quantity INTEGER NOT NULL, confidence REAL,
    scan_token TEXT, created_at TEXT NOT NULL, reversed_at TEXT, reversed_by TEXT
);
CREATE TABLE device_status (
    id INTEGER PRIMARY KEY, device_name TEXT NOT NULL, detector_mode TEXT NOT NULL,
    model_name TEXT, last_seen TEXT NOT NULL, last_error TEXT
);
"""


class DatabaseMigrationTestCase(unittest.TestCase):
    def test_legacy_return_reads_only_as_many_loans_as_needed(self):
        fetched = []

        class TrackingCursor(sqlite3.Cursor):
            def fetchall(self):
                rows = super().fetchall()
                fetched.append(len(rows))
                return rows

        class TrackingConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if "SELECT loan_transaction_id, remaining_quantity" in sql:
                    return self.cursor(factory=TrackingCursor).execute(sql, parameters)
                return super().execute(sql, parameters)

        with closing(sqlite3.connect(":memory:", factory=TrackingConnection)) as db:
            db.row_factory = sqlite3.Row
            db.executescript((Path(__file__).parents[1] / "equipment_manager/schema.sql").read_text(encoding="utf-8"))
            db.execute("""INSERT INTO equipment
                (id, name, total_qty, available_qty, created_at, updated_at)
                VALUES (1, 'meter', 100, 0, '2026-01-01', '2026-01-01')""")
            db.executemany("""INSERT INTO transactions
                (id, student_id, equipment_id, action, quantity, created_at)
                VALUES (?, '30304', 1, 'loan', 1, '2026-01-01')""",
                ((f"loan-{index:03}",) for index in range(100)))
            db.execute("""INSERT INTO transactions
                (id, student_id, equipment_id, action, quantity, created_at)
                VALUES ('return', '30304', 1, 'return', 1, '2026-01-02')""")
            _backfill_active_loans(db)
            self.assertEqual(fetched, [1])
            self.assertEqual(db.execute("SELECT SUM(remaining_quantity) FROM active_loans").fetchone()[0], 99)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM return_allocations").fetchone()[0], 1)

    def test_existing_transactions_are_preserved_and_backfilled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "old.db"
            with closing(sqlite3.connect(database)) as db:
                db.executescript(OLD_SCHEMA)
                now = "2026-01-01T00:00:00+00:00"
                db.execute(
                    "INSERT INTO equipment VALUES (1, '멀티미터', 5, 4, 1, ?, ?)",
                    (now, now),
                )
                db.execute(
                    "INSERT INTO transactions VALUES (?, ?, 1, 'loan', 2, NULL, NULL, ?, NULL, NULL)",
                    ("loan-old", "30304", now),
                )
                db.execute(
                    "INSERT INTO transactions VALUES (?, ?, 1, 'return', 1, NULL, NULL, ?, NULL, NULL)",
                    ("return-old", "30304", "2026-01-02T00:00:00+00:00"),
                )
                db.commit()

            app = create_app(
                {
                    "TESTING": True,
                    "DATABASE": str(database),
                    "SECRET_KEY": "migration-test",
                    "HEARTBEAT_ENABLED": False,
                    "DETECTOR_MODE": "mock",
                    "DEFAULT_LOAN_DAYS": 14,
                }
            )
            try:
                with app.app_context():
                    db = get_db()
                    columns = {
                        row[1] for row in db.execute("PRAGMA table_info(transactions)")
                    }
                    equipment_columns = {
                        row[1] for row in db.execute("PRAGMA table_info(equipment)")
                    }
                    active = db.execute(
                        "SELECT remaining_quantity, due_date FROM active_loans"
                    ).fetchone()
                    allocation = db.execute(
                        "SELECT quantity FROM return_allocations"
                    ).fetchone()
                    self.assertIn("due_date", columns)
                    self.assertIn("reason", columns)
                    self.assertEqual(db.execute("SELECT reason FROM transactions WHERE id = 'loan-old'").fetchone()[0], "")
                    self.assertIn("loan_period_days", equipment_columns)
                    self.assertEqual(
                        db.execute(
                            "SELECT loan_period_days FROM equipment WHERE id = 1"
                        ).fetchone()[0],
                        14,
                    )
                    self.assertEqual(active["remaining_quantity"], 1)
                    self.assertIsNone(active["due_date"])
                    self.assertEqual(allocation["quantity"], 1)
            finally:
                app.extensions["shutdown_services"]()

            second_app = create_app(
                {
                    "TESTING": True,
                    "DATABASE": str(database),
                    "SECRET_KEY": "migration-test-2",
                    "HEARTBEAT_ENABLED": False,
                    "DETECTOR_MODE": "mock",
                }
            )
            try:
                with second_app.app_context():
                    db = get_db()
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM active_loans").fetchone()[0],
                        1,
                    )
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM return_allocations").fetchone()[0],
                        1,
                    )
                    self.assertEqual(
                        db.execute(
                            "SELECT loan_period_days FROM equipment WHERE id = 1"
                        ).fetchone()[0],
                        14,
                    )
            finally:
                second_app.extensions["shutdown_services"]()


if __name__ == "__main__":
    unittest.main()
