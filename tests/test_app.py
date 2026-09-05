from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from equipment_manager import create_app


class EquipmentManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = str(Path(self.temp_dir.name) / "test.db")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": database,
                "SECRET_KEY": "test-secret",
                "CSRF_ENABLED": False,
                "HEARTBEAT_ENABLED": False,
                "DETECTOR_MODE": "mock",
                "DEFAULT_EQUIPMENT": ["멀티미터", "아두이노"],
                "DEFAULT_QUANTITY": 3,
                "STATION_AUTH_REQUIRED": True,
                "STATION_PIN": "2468",
                "TEACHER_USERNAME": "teacher",
                "TEACHER_PASSWORD": "test-teacher",
                "DEVELOPER_USERNAME": "developer",
                "DEVELOPER_PASSWORD": "test-developer",
                "DUPLICATE_WINDOW_SECONDS": 0,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["shutdown_services"]()
        self.temp_dir.cleanup()

    def login_station(self):
        response = self.client.post("/station/login", data={"pin": "2468"})
        self.assertEqual(response.status_code, 302)

    def login_admin(self):
        response = self.client.post(
            "/admin/login",
            data={"username": "teacher", "password": "test-teacher"},
        )
        self.assertEqual(response.status_code, 302)

    def login_developer(self):
        response = self.client.post(
            "/admin/login",
            data={"username": "developer", "password": "test-developer"},
        )
        self.assertEqual(response.status_code, 302)

    def first_equipment(self):
        return self.client.get("/api/status").get_json()["inventory"][0]

    def scan(self, equipment_id):
        response = self.client.post("/api/scans", json={"mock_equipment_id": equipment_id})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["scan"]["token"]

    def transact(
        self,
        token,
        student_id="30304",
        action="loan",
        quantity=1,
        due_date=None,
    ):
        return self.client.post(
            "/api/transactions",
            json={
                "scan_token": token,
                "student_id": student_id,
                "action": action,
                "quantity": quantity,
                "due_date": due_date,
            },
        )

    def test_dashboard_and_health_are_public(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        health = self.client.get("/healthz").get_json()
        self.assertEqual(health["ok"], True)
        self.assertEqual(health["database"]["engine"], "sqlite")
        self.assertEqual(health["database"]["journal_mode"], "wal")
        self.assertGreater(health["memory_rss_mb"], 0)
        self.assertIn("busy", health["inference"])
        css_response = self.client.get("/static/style.css")
        js_response = self.client.get("/static/app.js")
        self.assertEqual(css_response.status_code, 200)
        self.assertEqual(js_response.status_code, 200)
        css_response.close()
        js_response.close()
        payload = self.client.get("/api/status").get_json()
        self.assertEqual(len(payload["inventory"]), 2)
        self.assertNotIn("student_id", str(payload))

    def test_scan_requires_station_login(self):
        response = self.client.post("/api/scans", json={"mock_equipment_id": 1})
        self.assertEqual(response.status_code, 401)

    def test_scan_is_open_when_station_auth_is_disabled(self):
        self.app.config["STATION_AUTH_REQUIRED"] = False
        self.assertEqual(self.client.get("/scan").status_code, 200)
        response = self.client.post("/api/scans", json={"mock_equipment_id": 1})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_admin_requires_matching_username_and_password(self):
        rejected = self.client.post(
            "/admin/login",
            data={"username": "wrong", "password": "test-teacher"},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertIn("아이디 또는 비밀번호", rejected.get_data(as_text=True))
        with self.client.session_transaction() as current_session:
            self.assertIsNone(current_session.get("admin_role"))

        self.login_admin()
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session.get("admin_role"), "teacher")

    def test_teacher_cannot_open_developer_page(self):
        self.login_admin()
        response = self.client.get("/developer")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/admin"))

    def test_anonymous_user_is_sent_to_login_from_developer_page(self):
        response = self.client.get("/developer")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/admin/login"))

    def test_developer_has_full_access(self):
        self.login_developer()
        developer_page = self.client.get("/developer")
        self.assertEqual(developer_page.status_code, 200)
        developer_html = developer_page.get_data(as_text=True)
        self.assertIn("시스템 진단", developer_html)
        self.assertNotIn("test-developer", developer_html)
        self.assertNotIn("test-teacher", developer_html)
        self.assertEqual(self.client.get("/admin").status_code, 200)

        # Developer access bypasses the optional station PIN.
        scan = self.client.post("/api/scans", json={"mock_equipment_id": 1})
        self.assertEqual(scan.status_code, 200, scan.get_json())

        self.client.post("/admin/logout")
        after_logout = self.client.get("/developer")
        self.assertEqual(after_logout.status_code, 302)
        self.assertTrue(after_logout.location.endswith("/admin/login"))

    def test_csrf_protects_login_post(self):
        self.app.config["CSRF_ENABLED"] = True
        self.client.get("/station/login")
        rejected = self.client.post("/station/login", data={"pin": "2468"})
        self.assertEqual(rejected.status_code, 302)
        with self.client.session_transaction() as current_session:
            self.assertFalse(current_session.get("station_authenticated", False))
            token = current_session["csrf_token"]
        accepted = self.client.post(
            "/station/login",
            data={"pin": "2468", "csrf_token": token},
        )
        self.assertEqual(accepted.status_code, 302)
        with self.client.session_transaction() as current_session:
            self.assertTrue(current_session.get("station_authenticated", False))

    def test_loan_and_return_flow(self):
        self.login_station()
        item = self.first_equipment()
        loan = self.transact(self.scan(item["id"]), quantity=2)
        self.assertEqual(loan.status_code, 200, loan.get_json())
        self.assertEqual(loan.get_json()["transaction"]["available_qty"], 1)

        returned = self.transact(self.scan(item["id"]), action="return", quantity=1)
        self.assertEqual(returned.status_code, 200, returned.get_json())
        self.assertEqual(returned.get_json()["transaction"]["available_qty"], 2)

    def test_scan_token_is_single_use(self):
        self.login_station()
        token = self.scan(self.first_equipment()["id"])
        self.assertEqual(self.transact(token).status_code, 200)
        second = self.transact(token, student_id="30305")
        self.assertEqual(second.status_code, 422)
        self.assertIn("이미 처리된", second.get_json()["error"])

    def test_cannot_loan_more_than_available(self):
        self.login_station()
        response = self.transact(self.scan(self.first_equipment()["id"]), quantity=4)
        self.assertEqual(response.status_code, 422)
        self.assertIn("부족", response.get_json()["error"])

    def test_cannot_return_more_than_student_borrowed(self):
        self.login_station()
        response = self.transact(
            self.scan(self.first_equipment()["id"]),
            student_id="30399",
            action="return",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("미반납", response.get_json()["error"])

    def test_overdue_student_cannot_borrow_until_every_overdue_item_is_returned(self):
        self.login_station()
        first, second = self.client.get("/api/status").get_json()["inventory"]
        tomorrow = (datetime.now().astimezone().date() + timedelta(days=1)).isoformat()
        loan = self.transact(
            self.scan(first["id"]),
            student_id="30999",
            quantity=2,
            due_date=tomorrow,
        )
        self.assertEqual(loan.status_code, 200, loan.get_json())
        self.assertEqual(loan.get_json()["transaction"]["due_date"], tomorrow)

        yesterday = (datetime.now().astimezone().date() - timedelta(days=1)).isoformat()
        with self.app.app_context():
            from equipment_manager.db import get_db

            db = get_db()
            db.execute(
                "UPDATE active_loans SET due_date = ? WHERE student_id = ?",
                (yesterday, "30999"),
            )
            db.commit()

        scans_before = self.client.get("/healthz").get_json()["inference"]["scan_count"]
        early_block = self.client.post(
            "/api/scans",
            json={
                "mock_equipment_id": second["id"],
                "student_id": "30999",
                "action": "loan",
            },
        )
        self.assertEqual(early_block.status_code, 422)
        self.assertIn("연체", early_block.get_json()["error"])
        scans_after = self.client.get("/healthz").get_json()["inference"]["scan_count"]
        self.assertEqual(scans_before, scans_after)

        self.login_admin()
        admin_page = self.client.get("/admin")
        self.assertIn("연체·대여 제한", admin_page.get_data(as_text=True))
        self.assertIn(yesterday, admin_page.get_data(as_text=True))

        blocked_token = self.scan(second["id"])
        blocked = self.transact(blocked_token, student_id="30999", due_date=tomorrow)
        self.assertEqual(blocked.status_code, 422)
        self.assertIn("연체", blocked.get_json()["error"])

        partial_return = self.transact(
            self.scan(first["id"]), student_id="30999", action="return", quantity=1
        )
        self.assertEqual(partial_return.status_code, 200, partial_return.get_json())
        still_blocked = self.transact(blocked_token, student_id="30999", due_date=tomorrow)
        self.assertEqual(still_blocked.status_code, 422)

        final_return = self.transact(
            self.scan(first["id"]), student_id="30999", action="return", quantity=1
        )
        self.assertEqual(final_return.status_code, 200, final_return.get_json())
        allowed = self.transact(blocked_token, student_id="30999", due_date=tomorrow)
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

    def test_due_date_must_be_within_configured_range(self):
        self.login_station()
        item = self.first_equipment()
        today = datetime.now().astimezone().date()
        past = self.transact(
            self.scan(item["id"]),
            due_date=(today - timedelta(days=1)).isoformat(),
        )
        self.assertEqual(past.status_code, 422)
        self.assertIn("오늘보다 이전", past.get_json()["error"])

        too_far = self.transact(
            self.scan(item["id"]),
            due_date=(today + timedelta(days=91)).isoformat(),
        )
        self.assertEqual(too_far.status_code, 422)
        self.assertIn("최대", too_far.get_json()["error"])

    def test_admin_can_reverse_transaction(self):
        self.login_station()
        item = self.first_equipment()
        loan = self.transact(self.scan(item["id"])).get_json()["transaction"]
        self.login_admin()
        response = self.client.post(f"/admin/transactions/{loan['transaction_id']}/reverse")
        self.assertEqual(response.status_code, 302)
        restored = next(
            row for row in self.client.get("/api/status").get_json()["inventory"]
            if row["id"] == item["id"]
        )
        self.assertEqual(restored["available_qty"], restored["total_qty"])

    def test_admin_reversals_keep_active_loan_allocations_consistent(self):
        self.login_station()
        item = self.first_equipment()
        loan = self.transact(
            self.scan(item["id"]), student_id="30777", quantity=2
        ).get_json()["transaction"]
        returned = self.transact(
            self.scan(item["id"]),
            student_id="30777",
            action="return",
            quantity=1,
        ).get_json()["transaction"]
        self.login_admin()

        cannot_reverse_loan = self.client.post(
            f"/admin/transactions/{loan['transaction_id']}/reverse",
            follow_redirects=True,
        )
        self.assertIn("반납된 대여는 취소할 수 없습니다", cannot_reverse_loan.get_data(as_text=True))

        self.client.post(
            f"/admin/transactions/{returned['transaction_id']}/reverse"
        )
        self.client.post(f"/admin/transactions/{loan['transaction_id']}/reverse")
        restored = next(
            row
            for row in self.client.get("/api/status").get_json()["inventory"]
            if row["id"] == item["id"]
        )
        self.assertEqual(restored["available_qty"], restored["total_qty"])

    def test_admin_shows_outstanding_and_can_search(self):
        self.login_station()
        item = self.first_equipment()
        self.transact(self.scan(item["id"]), student_id="30304")
        self.login_admin()
        page = self.client.get("/admin?q=30304")
        self.assertEqual(page.status_code, 200)
        self.assertIn("30304", page.get_data(as_text=True))
        self.assertIn("현재 미반납", page.get_data(as_text=True))

    def test_admin_can_add_equipment_and_export_csv(self):
        self.login_admin()
        response = self.client.post(
            "/admin/equipment",
            data={"name": "오실로스코프", "total_qty": 2},
        )
        self.assertEqual(response.status_code, 302)
        names = [row["name"] for row in self.client.get("/api/status").get_json()["inventory"]]
        self.assertIn("오실로스코프", names)
        export = self.client.get("/admin/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.content_type)

    def test_admin_rejects_invalid_inventory_counts(self):
        self.login_admin()
        item = self.first_equipment()
        self.client.post(
            f"/admin/equipment/{item['id']}",
            data={"total_qty": 1, "available_qty": 2},
        )
        unchanged = next(
            row for row in self.client.get("/api/status").get_json()["inventory"]
            if row["id"] == item["id"]
        )
        self.assertEqual(unchanged["total_qty"], 3)
        self.assertEqual(unchanged["available_qty"], 3)


if __name__ == "__main__":
    unittest.main()
