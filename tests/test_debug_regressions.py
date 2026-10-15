from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from equipment_manager import create_app
from equipment_manager.db import get_db
from equipment_manager.deployment import validate_deployment
from equipment_manager.readiness import recognition_status


class DebugRegressionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = create_app({
            "TESTING": True, "HEARTBEAT_ENABLED": False, "CSRF_ENABLED": False,
            "DETECTOR_MODE": "mock", "GPIO_ENABLED": False,
            "DATABASE": str(Path(directory.name) / "test.db"),
            "ERROR_LOG_PATH": str(Path(directory.name) / "errors.log"),
            "SECRET_KEY": "debug-test-secret", "DEFAULT_EQUIPMENT": ["meter"],
            "DEFAULT_QUANTITY": 3, "DUPLICATE_WINDOW_SECONDS": 0,
            "TEACHER_USERNAME": "teacher", "TEACHER_PASSWORD": "test-password",
        })
        self.addCleanup(self.app.extensions["shutdown_services"])
        self.client = self.app.test_client()
        response = self.client.post("/admin/login", data={
            "username": "teacher", "password": "test-password",
        })
        self.assertEqual(response.status_code, 302)

    def test_malformed_scan_tokens_are_rejected_without_changing_stock(self):
        scan = self.client.post("/api/scans", json={"mock_equipment_id": 1}).get_json()["scan"]
        for token in ("\ud800", "x" * 2000, None, [], "not-a-token"):
            with self.subTest(token_type=type(token).__name__):
                response = self.client.post("/api/transactions", json={
                    "scan_token": token, "student_id": "30304", "action": "loan",
                    "quantity": 1, "reason": "class",
                })
                self.assertEqual(response.status_code, 422)
                self.assertFalse(response.get_json()["ok"])
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT available_qty FROM equipment").fetchone()[0], 3)
            self.assertEqual(get_db().execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0)
        response = self.client.post("/api/transactions", json={
            "scan_token": scan["token"], "student_id": "30304", "action": "loan",
            "quantity": 1, "reason": "class",
        })
        self.assertEqual(response.status_code, 200)

    def test_unrepresentable_route_ids_return_404_instead_of_database_errors(self):
        for identifier in (0, 2**63, 10**100):
            paths = (
                ("post", f"/admin/equipment/{identifier}"),
                ("post", f"/admin/equipment/{identifier}/remove"),
                ("post", f"/admin/students/{identifier}/approve"),
                ("get", f"/admin/students/{identifier}/password"),
                ("post", f"/admin/students/{identifier}/password"),
            )
            for method, path in paths:
                with self.subTest(method=method, path=path):
                    response = getattr(self.client, method)(path, data={
                        "total_qty": "3", "available_qty": "3", "loan_period_days": "7",
                    })
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_dashboard_initial_html_has_correct_zero_stock_badge(self):
        with self.app.app_context():
            db = get_db()
            with db:
                db.execute("UPDATE equipment SET total_qty = 0, available_qty = 0")
        text = self.client.get("/").get_data(as_text=True)
        self.assertRegex(text, r'class="availability-badge empty">대여 불가</span>')
        with self.app.app_context():
            db = get_db()
            with db:
                db.execute("UPDATE equipment SET total_qty = 3, available_qty = 3")
        text = self.client.get("/").get_data(as_text=True)
        self.assertRegex(text, r'class="availability-badge">사용 가능</span>')

    def test_home_relative_model_path_agrees_between_readiness_and_detector(self):
        with tempfile.TemporaryDirectory(prefix="equipment-model-path-", dir=Path.home()) as directory:
            model = Path(directory) / "best.pt"
            model.touch()
            configured = "~/" + model.relative_to(Path.home()).as_posix()
            app = create_app({
                "TESTING": True, "HEARTBEAT_ENABLED": False, "DETECTOR_MODE": "yolo",
                "YOLO_MODEL_PATH": configured,
                "DATABASE": self.app.config["DATABASE"],
                "ERROR_LOG_PATH": str(Path(directory) / "errors.log"),
            })
            try:
                with app.app_context():
                    self.assertTrue(recognition_status()["can_scan"])
                detector = app.extensions["detection_service"]._detector
                self.assertEqual(detector.model_path, model)
                validate_deployment({
                    "SECRET_KEY": "deployment-test-secret-value-123456789",
                    "DEVELOPER_USERNAME": "developer", "DEVELOPER_PASSWORD": "test-developer-password",
                    "TEACHER_USERNAME": "teacher", "TEACHER_PASSWORD": "test-teacher-password",
                    "DETECTOR_MODE": "yolo", "YOLO_MODEL_PATH": configured,
                }, Path(directory))
            finally:
                app.extensions["shutdown_services"]()


if __name__ == "__main__":
    unittest.main()
