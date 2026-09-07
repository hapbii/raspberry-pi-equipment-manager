from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from equipment_manager import create_app
from equipment_manager.vision import DetectionError


class EquipmentManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = str(Path(self.temp_dir.name) / "test.db")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": database,
                "ERROR_LOG_PATH": str(Path(self.temp_dir.name) / "errors.log"),
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
        station_pin="2468",
    ):
        payload = {
            "scan_token": token,
            "student_id": student_id,
            "action": action,
            "quantity": quantity,
            "due_date": due_date,
        }
        if station_pin is not None:
            payload["station_pin"] = station_pin
        return self.client.post(
            "/api/transactions",
            json=payload,
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
        self.assertEqual(payload["inventory"][0]["loan_period_days"], 7)
        self.assertNotIn("student_id", str(payload))

    def test_shutdown_releases_long_lived_service_references(self):
        detection_service = self.app.extensions["detection_service"]

        self.app.extensions["shutdown_services"]()

        self.assertNotIn("detection_service", self.app.extensions)
        self.assertNotIn("heartbeat_service", self.app.extensions)
        self.assertNotIn("error_log_store", self.app.extensions)
        self.assertTrue(detection_service.status()["closed"])
        self.assertIsNone(detection_service._detector)

    def test_scan_is_open_and_final_transaction_requires_station_pin(self):
        page = self.client.get("/scan")
        self.assertEqual(page.status_code, 200)
        page_html = page.get_data(as_text=True)
        self.assertIn("최종 처리 시 PIN 확인", page_html)
        self.assertIn('id="station-pin-dialog"', page_html)
        self.assertIn('data-pin-required="true"', page_html)
        self.assertNotIn("2468", page_html)

        legacy_login = self.client.get("/station/login")
        self.assertEqual(legacy_login.status_code, 302)
        self.assertTrue(legacy_login.location.endswith("/scan"))

        token = self.scan(self.first_equipment()["id"])
        missing = self.transact(token, station_pin=None)
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing.get_json()["code"], "station_pin_invalid")

        incorrect = self.transact(token, station_pin="000000")
        self.assertEqual(incorrect.status_code, 403)
        self.assertIn("PIN이 올바르지", incorrect.get_json()["error"])

        accepted = self.transact(token)
        self.assertEqual(accepted.status_code, 200, accepted.get_json())

    def test_scan_is_open_when_station_auth_is_disabled(self):
        self.app.config["STATION_AUTH_REQUIRED"] = False
        self.assertEqual(self.client.get("/scan").status_code, 200)
        token = self.scan(self.first_equipment()["id"])
        response = self.transact(token, station_pin=None)
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_public_pages_do_not_display_default_password_banner(self):
        self.app.config.update(
            DEVELOPER_PASSWORD="developer1234", TEACHER_PASSWORD="teacher1234",
            STATION_PIN="1234",
        )
        for path in ("/", "/scan", "/admin/login"):
            with self.subTest(path=path):
                page = self.client.get(path)
                self.assertEqual(page.status_code, 200)
                html = page.get_data(as_text=True)
                self.assertNotIn("개발용 기본 계정 비밀번호", html)
                self.assertNotIn("security-warning", html)

    def test_teacher_still_requires_pin_for_loan_and_return(self):
        self.login_admin()
        self.assertIn('data-pin-required="true"', self.client.get("/scan").get_data(as_text=True))
        for action in ("loan", "return"):
            with self.subTest(action=action):
                equipment = self.first_equipment()
                token = self.scan(equipment["id"])
                for pin in (None, "wrong"):
                    rejected = self.transact(token, action=action, station_pin=pin)
                    self.assertEqual(rejected.status_code, 403)
                    self.assertEqual(self.first_equipment()["available_qty"], equipment["available_qty"])
                accepted = self.transact(token, action=action)
                self.assertEqual(accepted.status_code, 200, accepted.get_json())

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

    def test_unicode_credentials_and_invalid_unicode_tokens_do_not_raise(self):
        self.app.config.update(TEACHER_USERNAME="선생님", TEACHER_PASSWORD="직접설정한비밀번호123!")
        rejected = self.client.post("/admin/login", data={"username": "다른사람", "password": "틀린값"})
        self.assertEqual(rejected.status_code, 200)
        accepted = self.client.post("/admin/login", data={"username": "선생님", "password": "직접설정한비밀번호123!"})
        self.assertEqual(accepted.status_code, 302)
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session.get("admin_role"), "teacher")
        invalid_pin = self.client.post("/api/transactions", json={"station_pin": "잘못된PIN"})
        self.assertEqual(invalid_pin.status_code, 403)
        malformed_pin = self.client.post("/api/transactions", json={"station_pin": "\ud800"})
        self.assertEqual(malformed_pin.status_code, 403)
        self.app.config["CSRF_ENABLED"] = True
        invalid_csrf = self.client.post("/admin/login", data={"csrf_token": "한글토큰"})
        self.assertEqual(invalid_csrf.status_code, 302)
        self.assertEqual(self.client.get("/healthz").status_code, 200)

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
        self.assertEqual(self.client.get("/").status_code, 200)
        scan_page = self.client.get("/scan")
        self.assertEqual(scan_page.status_code, 200)
        self.assertIn('data-pin-required="false"', scan_page.get_data(as_text=True))

        # Developer access bypasses the final station PIN confirmation.
        scan = self.client.post("/api/scans", json={"mock_equipment_id": 1})
        self.assertEqual(scan.status_code, 200, scan.get_json())
        transaction = self.transact(
            scan.get_json()["scan"]["token"],
            station_pin=None,
        )
        self.assertEqual(transaction.status_code, 200, transaction.get_json())
        returned = self.transact(self.scan(1), action="return", station_pin=None)
        self.assertEqual(returned.status_code, 200, returned.get_json())

        self.client.post("/admin/logout")
        after_logout = self.client.get("/developer")
        self.assertEqual(after_logout.status_code, 302)
        self.assertTrue(after_logout.location.endswith("/admin/login"))
        self.assertIn('data-pin-required="true"', self.client.get("/scan").get_data(as_text=True))

    def test_only_developer_can_view_and_clear_error_logs(self):
        marker = "camera-test-error-4821"
        error_log_path = Path(self.app.config["ERROR_LOG_PATH"])
        detection_service = self.app.extensions["detection_service"]
        with patch.object(
            detection_service,
            "detect",
            side_effect=DetectionError(marker),
        ):
            failed_scan = self.client.post(
                "/api/scans",
                json={"mock_equipment_id": self.first_equipment()["id"]},
            )
        self.assertEqual(failed_scan.status_code, 422)
        self.assertTrue(error_log_path.is_file())

        self.login_admin()
        rejected = self.client.post("/developer/error-logs/clear")
        self.assertEqual(rejected.status_code, 302)
        self.assertTrue(rejected.location.endswith("/admin"))
        self.assertIn(marker, error_log_path.read_text(encoding="utf-8"))

        self.client.post("/admin/logout")
        self.login_developer()
        developer_page = self.client.get("/developer").get_data(as_text=True)
        self.assertIn("최근 오류 로그", developer_page)
        self.assertIn(marker, developer_page)

        cleared = self.client.post(
            "/developer/error-logs/clear", follow_redirects=True
        )
        cleared_html = cleared.get_data(as_text=True)
        self.assertIn("오류 로그를 모두 삭제했습니다.", cleared_html)
        self.assertIn("기록된 오류가 없습니다.", cleared_html)
        self.assertFalse(error_log_path.exists())

    def test_csrf_protects_scan_post(self):
        self.app.config["CSRF_ENABLED"] = True
        self.client.get("/scan")
        rejected = self.client.post("/api/scans", json={"mock_equipment_id": 1})
        self.assertEqual(rejected.status_code, 400)
        with self.client.session_transaction() as current_session:
            token = current_session["csrf_token"]
        accepted = self.client.post(
            "/api/scans",
            json={"mock_equipment_id": 1},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(accepted.status_code, 200, accepted.get_json())

    def test_loan_and_return_flow(self):
        item = self.first_equipment()
        loan = self.transact(self.scan(item["id"]), quantity=2)
        self.assertEqual(loan.status_code, 200, loan.get_json())
        self.assertEqual(loan.get_json()["transaction"]["available_qty"], 1)

        returned = self.transact(self.scan(item["id"]), action="return", quantity=1)
        self.assertEqual(returned.status_code, 200, returned.get_json())
        self.assertEqual(returned.get_json()["transaction"]["available_qty"], 2)

    def test_scan_token_is_single_use(self):
        token = self.scan(self.first_equipment()["id"])
        self.assertEqual(self.transact(token).status_code, 200)
        second = self.transact(token, student_id="30305")
        self.assertEqual(second.status_code, 422)
        self.assertIn("이미 처리된", second.get_json()["error"])

    def test_cannot_loan_more_than_available(self):
        response = self.transact(self.scan(self.first_equipment()["id"]), quantity=4)
        self.assertEqual(response.status_code, 422)
        self.assertIn("부족", response.get_json()["error"])

    def test_cannot_return_more_than_student_borrowed(self):
        response = self.transact(
            self.scan(self.first_equipment()["id"]),
            student_id="30399",
            action="return",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("미반납", response.get_json()["error"])

    def test_overdue_student_cannot_borrow_until_every_overdue_item_is_returned(self):
        first, second = self.client.get("/api/status").get_json()["inventory"]
        self.login_admin()
        configured = self.client.post(
            f"/admin/equipment/{first['id']}",
            data={
                "total_qty": first["total_qty"],
                "available_qty": first["available_qty"],
                "loan_period_days": 1,
            },
        )
        self.assertEqual(configured.status_code, 302)
        tomorrow = (datetime.now().astimezone().date() + timedelta(days=1)).isoformat()
        loan = self.transact(
            self.scan(first["id"]),
            student_id="30999",
            quantity=2,
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
        blocked = self.transact(blocked_token, student_id="30999")
        self.assertEqual(blocked.status_code, 422)
        self.assertIn("연체", blocked.get_json()["error"])

        partial_return = self.transact(
            self.scan(first["id"]), student_id="30999", action="return", quantity=1
        )
        self.assertEqual(partial_return.status_code, 200, partial_return.get_json())
        still_blocked = self.transact(blocked_token, student_id="30999")
        self.assertEqual(still_blocked.status_code, 422)

        final_return = self.transact(
            self.scan(first["id"]), student_id="30999", action="return", quantity=1
        )
        self.assertEqual(final_return.status_code, 200, final_return.get_json())
        allowed = self.transact(blocked_token, student_id="30999")
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

    def test_admin_controls_each_equipment_loan_period(self):
        self.login_admin()
        admin_html = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('name="loan_period_days"', admin_html)
        scan_html = self.client.get("/scan").get_data(as_text=True)
        self.assertNotIn('id="due-date"', scan_html)
        self.assertNotIn("예: 30304", scan_html)
        self.assertNotIn("관리자가 기자재별로 지정", scan_html)
        self.assertNotIn("여러 프레임의 결과", scan_html)
        item = self.first_equipment()
        updated = self.client.post(
            f"/admin/equipment/{item['id']}",
            data={
                "total_qty": item["total_qty"],
                "available_qty": item["available_qty"],
                "loan_period_days": 14,
            },
        )
        self.assertEqual(updated.status_code, 302)
        current = self.first_equipment()
        self.assertEqual(current["loan_period_days"], 14)

        today = datetime.now().astimezone().date()
        scan_response = self.client.post(
            "/api/scans", json={"mock_equipment_id": item["id"]}
        )
        scan = scan_response.get_json()["scan"]
        expected_due_date = (today + timedelta(days=14)).isoformat()
        self.assertEqual(scan["loan_period_days"], 14)
        self.assertEqual(scan["due_date"], expected_due_date)

        loan = self.transact(
            scan["token"],
            due_date=(today + timedelta(days=1)).isoformat(),
        )
        self.assertEqual(loan.status_code, 200, loan.get_json())
        self.assertEqual(loan.get_json()["transaction"]["due_date"], expected_due_date)

        changed_again = self.client.post(
            f"/admin/equipment/{item['id']}",
            data={
                "total_qty": item["total_qty"],
                "available_qty": item["available_qty"] - 1,
                "loan_period_days": 3,
            },
        )
        self.assertEqual(changed_again.status_code, 302)
        with self.app.app_context():
            from equipment_manager.db import get_db

            stored_due_date = get_db().execute(
                "SELECT due_date FROM active_loans WHERE student_id = ?",
                ("30304",),
            ).fetchone()[0]
        self.assertEqual(stored_due_date, expected_due_date)

        next_loan = self.transact(
            self.scan(item["id"]),
            student_id="30305",
        )
        self.assertEqual(
            next_loan.get_json()["transaction"]["due_date"],
            (today + timedelta(days=3)).isoformat(),
        )

        rejected = self.client.post(
            f"/admin/equipment/{item['id']}",
            data={
                "total_qty": item["total_qty"],
                "available_qty": item["available_qty"] - 2,
                "loan_period_days": 91,
            },
            follow_redirects=True,
        )
        self.assertIn("0~90일", rejected.get_data(as_text=True))
        self.assertEqual(self.first_equipment()["loan_period_days"], 3)

    def test_admin_can_reverse_transaction(self):
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
            data={"name": "오실로스코프", "total_qty": 2, "loan_period_days": 21},
        )
        self.assertEqual(response.status_code, 302)
        names = [row["name"] for row in self.client.get("/api/status").get_json()["inventory"]]
        self.assertIn("오실로스코프", names)
        added = next(
            row for row in self.client.get("/api/status").get_json()["inventory"]
            if row["name"] == "오실로스코프"
        )
        self.assertEqual(added["loan_period_days"], 21)
        export = self.client.get("/admin/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.content_type)

    def test_admin_rejects_invalid_inventory_counts(self):
        self.login_admin()
        item = self.first_equipment()
        self.client.post(
            f"/admin/equipment/{item['id']}",
            data={"total_qty": 1, "available_qty": 2, "loan_period_days": 7},
        )
        unchanged = next(
            row for row in self.client.get("/api/status").get_json()["inventory"]
            if row["id"] == item["id"]
        )
        self.assertEqual(unchanged["total_qty"], 3)
        self.assertEqual(unchanged["available_qty"], 3)

    def test_teacher_and_developer_can_remove_and_restore_equipment(self):
        first, second = self.client.get("/api/status").get_json()["inventory"]
        stale_scan_token = self.scan(first["id"])

        self.login_admin()
        removed_by_teacher = self.client.post(
            f"/admin/equipment/{first['id']}/remove",
            follow_redirects=True,
        )
        self.assertIn("기자재 종류를 제거했습니다", removed_by_teacher.get_data(as_text=True))
        inventory = self.client.get("/api/status").get_json()["inventory"]
        self.assertNotIn(first["id"], [row["id"] for row in inventory])

        stale_transaction = self.transact(stale_scan_token)
        self.assertEqual(stale_transaction.status_code, 422)
        self.assertIn("유효하지 않은", stale_transaction.get_json()["error"])

        restored = self.client.post(
            "/admin/equipment",
            data={
                "name": first["name"],
                "total_qty": 5,
                "loan_period_days": 10,
            },
        )
        self.assertEqual(restored.status_code, 302)
        restored_item = next(
            row for row in self.client.get("/api/status").get_json()["inventory"]
            if row["name"] == first["name"]
        )
        self.assertEqual(restored_item["id"], first["id"])
        self.assertEqual(restored_item["total_qty"], 5)
        stale_after_restore = self.transact(stale_scan_token, student_id="30305")
        self.assertEqual(stale_after_restore.status_code, 422)

        self.login_developer()
        removed_by_developer = self.client.post(
            f"/admin/equipment/{second['id']}/remove",
            follow_redirects=True,
        )
        self.assertIn("기자재 종류를 제거했습니다", removed_by_developer.get_data(as_text=True))

    def test_equipment_with_outstanding_loan_cannot_be_removed(self):
        item = self.first_equipment()
        loan = self.transact(self.scan(item["id"]), student_id="30888")
        self.assertEqual(loan.status_code, 200, loan.get_json())

        self.login_admin()
        rejected = self.client.post(
            f"/admin/equipment/{item['id']}/remove",
            follow_redirects=True,
        )
        self.assertIn("미반납 수량 1개", rejected.get_data(as_text=True))
        self.assertIn(
            item["id"],
            [
                row["id"]
                for row in self.client.get("/api/status").get_json()["inventory"]
            ],
        )

    def test_only_developer_can_delete_cancelled_transaction_record(self):
        item = self.first_equipment()
        transaction = self.transact(
            self.scan(item["id"]),
            student_id="30701",
        ).get_json()["transaction"]
        transaction_id = transaction["transaction_id"]

        self.login_admin()
        denied = self.client.post(f"/admin/transactions/{transaction_id}/delete")
        self.assertEqual(denied.status_code, 302)
        self.assertTrue(denied.location.endswith("/admin"))

        self.login_developer()
        not_cancelled = self.client.post(
            f"/admin/transactions/{transaction_id}/delete",
            follow_redirects=True,
        )
        self.assertIn("먼저 취소", not_cancelled.get_data(as_text=True))

        self.login_admin()
        self.client.post(f"/admin/transactions/{transaction_id}/reverse")
        teacher_page = self.client.get("/admin").get_data(as_text=True)
        self.assertNotIn(
            f"/admin/transactions/{transaction_id}/delete",
            teacher_page,
        )

        self.login_developer()
        developer_page = self.client.get("/admin").get_data(as_text=True)
        self.assertIn(
            f"/admin/transactions/{transaction_id}/delete",
            developer_page,
        )
        deleted = self.client.post(
            f"/admin/transactions/{transaction_id}/delete",
            follow_redirects=True,
        )
        self.assertIn("영구 삭제했습니다", deleted.get_data(as_text=True))

        with self.app.app_context():
            from equipment_manager.db import get_db

            self.assertIsNone(
                get_db().execute(
                    "SELECT id FROM transactions WHERE id = ?",
                    (transaction_id,),
                ).fetchone()
            )
        restored = next(
            row for row in self.client.get("/api/status").get_json()["inventory"]
            if row["id"] == item["id"]
        )
        self.assertEqual(restored["available_qty"], restored["total_qty"])


if __name__ == "__main__":
    unittest.main()
