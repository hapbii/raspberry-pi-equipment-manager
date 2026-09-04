from __future__ import annotations

import tempfile
import unittest
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
                "STATION_PIN": "2468",
                "ADMIN_PASSWORD": "test-admin",
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
        response = self.client.post("/admin/login", data={"password": "test-admin"})
        self.assertEqual(response.status_code, 302)

    def first_equipment(self):
        return self.client.get("/api/status").get_json()["inventory"][0]

    def scan(self, equipment_id):
        response = self.client.post("/api/scans", json={"mock_equipment_id": equipment_id})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["scan"]["token"]

    def transact(self, token, student_id="30304", action="loan", quantity=1):
        return self.client.post(
            "/api/transactions",
            json={
                "scan_token": token,
                "student_id": student_id,
                "action": action,
                "quantity": quantity,
            },
        )

    def test_dashboard_and_health_are_public(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        health = self.client.get("/healthz").get_json()
        self.assertEqual(health["ok"], True)
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
