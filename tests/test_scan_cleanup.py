from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from equipment_manager import create_app
from equipment_manager.db import cleanup_expired_scan_sessions, get_db
from equipment_manager.inventory import (
    commit_transaction, create_scan_session, delete_transaction_record,
    reverse_transaction,
)


class ScanCleanupTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = create_app({
            "TESTING": True, "HEARTBEAT_ENABLED": False, "DETECTOR_MODE": "mock",
            "DATABASE": str(Path(directory.name) / "test.db"),
            "ERROR_LOG_PATH": str(Path(directory.name) / "errors.log"),
            "DEFAULT_EQUIPMENT": ["meter"], "DEFAULT_QUANTITY": 3,
            "DUPLICATE_WINDOW_SECONDS": 0,
        })
        self.addCleanup(self.app.extensions["shutdown_services"])
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        self.db = get_db()
        self.equipment_id = self.db.execute("SELECT id FROM equipment").fetchone()[0]
        self.old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")

    def scan(self):
        return create_scan_session(self.equipment_id, 0.9)["token"]

    def age(self, token):
        self.db.execute(
            "UPDATE scan_sessions SET expires_at = ?, consumed_at = ? WHERE token = ?",
            (self.old, self.old, token),
        )
        self.db.commit()

    def linked_loan(self):
        token = self.scan()
        transaction = commit_transaction(token, "30304", "loan", 1, "class")
        return token, transaction.transaction_id

    def assert_integrity(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_heartbeat_preserves_linked_sessions_and_removes_only_old_orphans(self):
        linked, transaction_id = self.linked_loan()
        orphan = self.scan()
        fresh = self.scan()
        before = tuple(self.db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone())
        self.age(linked)
        self.age(orphan)
        self.assertEqual(cleanup_expired_scan_sessions(), 1)
        self.assertEqual(cleanup_expired_scan_sessions(), 0)
        tokens = {row[0] for row in self.db.execute("SELECT token FROM scan_sessions")}
        self.assertEqual(tokens, {linked, fresh})
        self.assertEqual(tuple(self.db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()), before)
        self.assertEqual(self.db.execute("SELECT remaining_quantity FROM active_loans").fetchone()[0], 1)
        self.assert_integrity()

    def test_new_scan_and_return_work_after_previous_loan_session_expires(self):
        linked, _ = self.linked_loan()
        orphan = self.scan()
        self.age(linked)
        self.age(orphan)
        return_token = self.scan()
        commit_transaction(return_token, "30304", "return", 1)
        self.age(return_token)
        self.assertEqual(cleanup_expired_scan_sessions(), 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT remaining_quantity FROM active_loans").fetchone()[0], 0)
        self.assertIsNone(self.db.execute("SELECT token FROM scan_sessions WHERE token = ?", (orphan,)).fetchone())
        self.assert_integrity()

    def test_reversed_history_keeps_token_until_record_is_explicitly_deleted(self):
        token, transaction_id = self.linked_loan()
        reverse_transaction(transaction_id, "developer")
        self.age(token)
        self.assertEqual(cleanup_expired_scan_sessions(), 0)
        delete_transaction_record(transaction_id)
        self.assertEqual(cleanup_expired_scan_sessions(), 1)
        self.assert_integrity()

    def test_retention_window_keeps_recently_expired_sessions(self):
        token = self.scan()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        self.db.execute("UPDATE scan_sessions SET expires_at = ? WHERE token = ?", (recent, token))
        self.db.commit()
        self.assertEqual(cleanup_expired_scan_sessions(), 0)
        self.assertEqual(cleanup_expired_scan_sessions(retention_hours=0), 1)
        self.assert_integrity()


if __name__ == "__main__":
    unittest.main()
