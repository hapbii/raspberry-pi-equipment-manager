from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from equipment_manager import create_app
from equipment_manager.db import get_db
from equipment_manager.inventory import list_outstanding, outstanding_summary


class OutstandingPagingTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = create_app({
            "TESTING": True, "HEARTBEAT_ENABLED": False, "DETECTOR_MODE": "mock",
            "SECRET_KEY": "paging-test", "CSRF_ENABLED": False,
            "DATABASE": str(Path(temp.name) / "test.db"),
            "ERROR_LOG_PATH": str(Path(temp.name) / "errors.log"),
            "TEACHER_USERNAME": "teacher", "TEACHER_PASSWORD": "paging-password",
        })
        self.addCleanup(self.app.extensions["shutdown_services"])
        with self.app.app_context():
            db = get_db()
            with db:
                # Same student may have several loans: totals must count all
                # quantities but overdue students must only be counted once.
                db.executemany("""INSERT INTO transactions
                    (id, student_id, equipment_id, action, quantity, created_at, due_date)
                    VALUES (?, ?, 1, 'loan', 1, '2020-01-01', '2020-01-02')""",
                    ((str(i), f"student-{i // 2:04d}") for i in range(410)))
                db.execute("""INSERT INTO active_loans SELECT id, student_id, equipment_id,
                    quantity, quantity, due_date, created_at FROM transactions""")

    def test_large_listing_is_bounded_but_summary_counts_every_loan(self):
        with self.app.app_context():
            self.assertEqual(len(list_outstanding()), 100)
            self.assertEqual(len(list_outstanding(100000)), 101)
            first = list_outstanding(100)
            second = list_outstanding(100, 100)
            last = list_outstanding(100, 200)
            self.assertEqual(len(last), 5)
            self.assertEqual(len({row["student_id"] for row in first + second + last}), 205)
            self.assertTrue(all(row["quantity"] == 2 for row in first + second + last))
            self.assertEqual(outstanding_summary(), {"quantity": 410, "overdue_student_count": 205})

    def test_navigation_preserves_search_and_displays_correct_totals(self):
        client = self.app.test_client()
        client.post("/admin/login", data={"username": "teacher", "password": "paging-password"})
        first = client.get("/admin?q=missing&loans_page=1").get_data(as_text=True)
        self.assertEqual(first.count('<tr class="overdue-row">'), 100)
        self.assertIn('<strong>410</strong>', first)
        self.assertIn('<strong>205</strong>', first)
        self.assertIn('loans_page=2', first)
        self.assertIn('q=missing', first)
        last = client.get("/admin?loans_page=3").get_data(as_text=True)
        self.assertEqual(last.count('<tr class="overdue-row">'), 5)
        self.assertNotIn('loans_page=4', last)
        for invalid in ("-1", "bad", "0"):
            page = client.get(f"/admin?loans_page={invalid}").get_data(as_text=True)
            self.assertEqual(page.count('<tr class="overdue-row">'), 100)
