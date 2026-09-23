from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from equipment_manager import create_app
from equipment_manager.db import get_db
from equipment_manager.inventory import (
    create_scan_session, commit_transaction, list_inventory, reverse_transaction,
    update_equipment, InventoryError,
)


class EquipmentBatchTest(unittest.TestCase):
    def test_cancel_restores_quantity_and_admin_cannot_reintroduce_phantom_loan(self):
        with self.app.app_context():
            update_equipment(1, 9, 9, 7)
            token = create_scan_session(1, .99)["token"]
            tx = commit_transaction(token, "30304", "loan", 1, "lesson")
            self.assertEqual(tx.available_qty, 8)
            reverse_transaction(tx.transaction_id)
            item = next(row for row in list_inventory() if row["id"] == 1)
            self.assertEqual((item["total_qty"], item["available_qty"], item["loaned_qty"]), (9, 9, 0))
            with self.assertRaises(InventoryError):
                update_equipment(1, 9, 8, 7)
            self.assertFalse(get_db().in_transaction)
        self.login()
        items = [item for item in self.items() if item["id"] == 1]
        items[0]["available_qty"] = 8
        self.assertEqual(self.post(items).status_code, 400)
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT available_qty FROM equipment WHERE id=1").fetchone()[0], 9)

    def test_display_uses_real_loans_and_explicit_repair_preserves_history(self):
        with self.app.app_context():
            db = get_db()
            with db:
                db.execute("UPDATE equipment SET total_qty=9,available_qty=8 WHERE id=1")
            item = next(row for row in list_inventory() if row["id"] == 1)
            self.assertEqual(item["loaned_qty"], 0)
            self.assertEqual(item["expected_available_qty"], 9)
            self.assertTrue(item["quantity_mismatch"])
            update_equipment(1, 9, 9, 7)
            item = next(row for row in list_inventory() if row["id"] == 1)
            self.assertFalse(item["quantity_mismatch"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0)

    def test_counts_cannot_erase_real_loans_and_batch_is_atomic(self):
        self.login()
        self.transact(1)
        with self.app.app_context():
            for total, available in ((0, 0), (3, 3), (10000, 9999)):
                with self.assertRaises(InventoryError):
                    update_equipment(1, total, available, 7)
        items = self.items()
        for item in items:
            item["total_qty"] += 1
            item["available_qty"] += 1
        items[-1]["available_qty"] -= 1
        before = self.inventory()
        self.assertEqual(self.post(items).status_code, 400)
        self.assertEqual(self.inventory(), before)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = create_app({
            "TESTING": True, "HEARTBEAT_ENABLED": False, "CSRF_ENABLED": False,
            "SECRET_KEY": "batch-test-secret", "DETECTOR_MODE": "mock",
            "DATABASE": str(Path(temp.name) / "db.sqlite"),
            "ERROR_LOG_PATH": str(Path(temp.name) / "errors.log"),
            "DEFAULT_EQUIPMENT": ["Raspberry Pi", "Arduino", "Multimeter"], "DEFAULT_QUANTITY": 3,
            "TEACHER_USERNAME": "teacher", "TEACHER_PASSWORD": "teacher-test-password",
            "DEVELOPER_USERNAME": "developer", "DEVELOPER_PASSWORD": "developer-test-password",
            "DUPLICATE_WINDOW_SECONDS": 0,
        })
        self.addCleanup(self.app.extensions["shutdown_services"])
        self.client = self.app.test_client()

    def login(self, role="teacher"):
        self.client.post("/admin/login", data={"username": role, "password": f"{role}-test-password"})

    def inventory(self):
        with self.app.app_context():
            return list_inventory()

    def items(self):
        return [dict(id=row["id"], expected=row, total_qty=row["total_qty"],
                     available_qty=row["available_qty"], loan_period_days=row["loan_period_days"])
                for row in self.inventory()]

    def post(self, items, action="update", **kwargs):
        return self.client.post("/api/admin/equipment/batch", json={"action": action, "items": items}, **kwargs)

    def transact(self, equipment_id, action="loan"):
        with self.app.app_context():
            scan = create_scan_session(equipment_id, .99)
            commit_transaction(scan["token"], "30304", action, 1, reason="lesson")

    def test_teacher_and_developer_save_two_distinct_values_and_leave_third(self):
        for role in ("teacher", "developer"):
            self.login(role)
            items = self.items()
            third = self.inventory()[2]
            for item, delta in zip(items[:2], (1, 2)):
                item["total_qty"] += delta
                item["available_qty"] += delta
            response = self.post(items[:2])
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual([row["total_qty"] for row in self.inventory()[:2]], [i["total_qty"] for i in items[:2]])
            self.assertEqual(self.inventory()[2], third)

    def test_guest_student_and_csrf_cannot_modify(self):
        items = self.items()
        self.assertEqual(self.post(items).status_code, 401)
        with patch("equipment_manager.auth.PASSWORD_METHOD", "pbkdf2:sha256:1000"):
            self.client.post("/register", data={"student_id": "30304", "name": "Student",
                "password": "student-test-password", "password_confirm": "student-test-password"})
        with self.app.app_context():
            db = get_db()
            with db:
                db.execute("UPDATE student_accounts SET status='active'")
        self.client.post("/login", data={"student_id": "30304", "password": "student-test-password"})
        self.assertEqual(self.post(items).status_code, 401)
        self.login()
        self.app.config["CSRF_ENABLED"] = True
        self.assertEqual(self.post(items).status_code, 400)
        with self.client.session_transaction() as session:
            csrf = session["csrf_token"]
        self.assertEqual(self.post(items, headers={"X-CSRF-Token": csrf}).status_code, 200)

    def test_invalid_requests_never_partially_save(self):
        self.login()
        original = self.inventory()
        for key, value in [("available_qty", 9999), ("total_qty", -1), ("total_qty", 10000),
                           ("total_qty", 1.5), ("total_qty", True), ("loan_period_days", 9999),
                           ("expected", None), ("id", []), ("available_qty", "2")]:
            items = self.items()
            items[0]["total_qty"] = 8
            items[1][key] = value
            self.assertEqual(self.post(items).status_code, 400, (key, value))
            self.assertEqual(self.inventory(), original)
        for body in (None, [], {"action": [], "items": []}, {"action": "update", "items": [None]}):
            self.assertEqual(self.client.post("/api/admin/equipment/batch", json=body).status_code, 400)
        self.assertEqual(self.post([]).status_code, 400)
        self.assertEqual(self.post([self.items()[0]] * 101).status_code, 400)
        self.assertEqual(self.post([self.items()[0]] * 2).status_code, 400)

    def test_stale_loan_or_admin_edit_rolls_back_prior_row(self):
        self.login()
        items = self.items()
        items[0]["total_qty"] += 1
        self.transact(items[1]["id"])
        original = self.inventory()
        self.assertEqual(self.post(items[:2]).status_code, 400)
        self.assertEqual(self.inventory(), original)
        fresh = self.items()
        fresh[1]["loan_period_days"] += 1
        self.assertEqual(self.post(fresh[1:2]).status_code, 200)
        self.assertEqual(self.post(fresh).status_code, 400)

    def test_missing_or_deleted_item_rolls_back_all_updates(self):
        self.login()
        items = self.items()
        original = self.inventory()
        items[0]["total_qty"] += 1
        items[1]["id"] = 9999
        self.assertEqual(self.post(items).status_code, 400)
        self.assertEqual(self.inventory(), original)

    def test_bulk_remove_with_loan_rolls_back_rows_and_scan_cleanup(self):
        self.login()
        items = self.items()
        with self.app.app_context():
            scan = create_scan_session(items[0]["id"], .99)
        self.transact(items[1]["id"])
        items = self.items()  # Fresh snapshot: removal fails on outstanding loan, not stale values.
        self.assertEqual(self.post(items[:2], "remove").status_code, 400)
        self.assertEqual(len(self.inventory()), 3)
        with self.app.app_context():
            self.assertIsNotNone(get_db().execute("SELECT token FROM scan_sessions WHERE token=?", (scan["token"],)).fetchone())

    def test_bulk_remove_preserves_transactions_and_linked_scans(self):
        self.login()
        first = self.items()[0]["id"]
        self.transact(first)
        self.transact(first, "return")
        with self.app.app_context():
            create_scan_session(first, .99)
        self.assertEqual(self.post(self.items()[:2], "remove").status_code, 200)
        self.assertEqual(len(self.inventory()), 1)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM scan_sessions").fetchone()[0], 2)
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_unexpected_error_rolls_back_prior_mutations(self):
        self.login()
        items = self.items()
        original = self.inventory()
        from equipment_manager.inventory import _deactivate_equipment
        calls = 0
        def fail_second(db, item_id, now):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated storage failure")
            _deactivate_equipment(db, item_id, now)
        with patch("equipment_manager.equipment_settings._deactivate_equipment", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.post(items, "remove")
        self.assertEqual(self.inventory(), original)

    def test_interrupt_rolls_back_inside_same_context_before_connection_close(self):
        from equipment_manager.equipment_settings import change_selected_equipment
        from equipment_manager.inventory import _deactivate_equipment
        items = self.items()
        original = self.inventory()
        calls = 0

        def interrupt_second(db, item_id, now):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            _deactivate_equipment(db, item_id, now)

        with self.app.app_context(), patch(
            "equipment_manager.equipment_settings._deactivate_equipment", interrupt_second
        ):
            with self.assertRaises(KeyboardInterrupt):
                change_selected_equipment("remove", items)
            self.assertFalse(get_db().in_transaction)
            self.assertEqual(list_inventory(), original)
