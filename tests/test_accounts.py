from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from equipment_manager import create_app
from equipment_manager.db import get_db
from equipment_manager.auth import take_attempt


class AccountsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({
            "TESTING": True, "HEARTBEAT_ENABLED": False, "CSRF_ENABLED": False,
            "DETECTOR_MODE": "mock", "SECRET_KEY": "accounts-test-secret",
            "DATABASE": str(Path(self.temp.name) / "test.db"),
            "ERROR_LOG_PATH": str(Path(self.temp.name) / "errors.log"),
            "TEACHER_USERNAME": "teacher", "TEACHER_PASSWORD": "teacher-test-password",
            "DEVELOPER_USERNAME": "developer", "DEVELOPER_PASSWORD": "developer-test-password",
            "DUPLICATE_WINDOW_SECONDS": 0,
        })
        self.addCleanup(self.app.extensions["shutdown_services"])
        self.client = self.app.test_client()
        self.staff = self.app.test_client()
        self.staff.post("/admin/login", data={"username": "teacher", "password": "teacher-test-password"})
        patcher = patch("equipment_manager.auth.PASSWORD_METHOD", "pbkdf2:sha256:1000")
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, student_id="30304", client=None):
        response = (client or self.client).post("/register", data={
            "student_id": student_id, "name": "학생" + student_id,
            "password": "student-test-password", "password_confirm": "student-test-password",
            "role": "developer", "status": "active",
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            return dict(get_db().execute("SELECT * FROM student_accounts WHERE student_id = ?", (student_id,)).fetchone())

    def activate(self, student_id="30304", client=None):
        account = self.register(student_id, client)
        response = self.staff.post(f"/admin/students/{account['id']}/approve")
        self.assertEqual(response.status_code, 302)
        response = (client or self.client).post("/login", data={"student_id": student_id, "password": "student-test-password"})
        self.assertEqual(response.status_code, 302)
        return account

    def scan(self, client=None):
        response = (client or self.client).post("/api/scans", json={"mock_equipment_id": 1})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["scan"]["token"]

    def transact(self, token, client=None, **extra):
        return (client or self.client).post("/api/transactions", json={
            "scan_token": token, "student_id": "99999", "action": "loan", "quantity": 1,
            "reason": "private student reason", **extra,
        })

    def test_signup_is_pending_hashed_and_cannot_create_admin(self):
        account = self.register()
        self.assertEqual(account["status"], "pending")
        self.assertNotEqual(account["password_hash"], "student-test-password")
        self.assertTrue(account["password_hash"].startswith("pbkdf2:"))
        self.assertEqual(self.client.post("/login", data={"student_id": "30304", "password": "student-test-password"}).status_code, 200)
        self.assertEqual(self.client.get("/scan").status_code, 302)
        self.assertEqual(self.client.post("/api/scans", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/transactions", json={}).status_code, 401)
        self.assertEqual(self.client.post(f"/admin/students/{account['id']}/approve").status_code, 302)
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT status FROM student_accounts").fetchone()[0], "pending")

    def test_student_identity_is_bound_and_own_history_is_private(self):
        self.activate()
        other = self.app.test_client()
        self.activate("30305", other)
        response = self.transact(self.scan())
        self.assertEqual(response.status_code, 200, response.get_json())
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT student_id FROM transactions").fetchone()[0], "30304")
        self.assertIn("private student reason", self.client.get("/my-loans").get_data(as_text=True))
        self.assertNotIn("private student reason", other.get("/my-loans?student_id=30304").get_data(as_text=True))
        self.assertEqual(self.transact(self.scan(), action="return", reason="").status_code, 200)
        html = self.client.get("/scan").get_data(as_text=True)
        self.assertIn('value="30304" readonly', html)
        self.assertNotIn("station-pin-dialog", html)

    def test_other_account_cannot_consume_scan_token(self):
        self.activate()
        other = self.app.test_client()
        self.activate("30305", other)
        token = self.scan()
        self.assertEqual(self.transact(token, other).status_code, 422)
        self.assertEqual(self.transact(token).status_code, 200)
        self.assertEqual(self.transact(token).status_code, 422)

    def test_student_cannot_use_admin_or_developer_features(self):
        self.activate()
        for path in ("/admin", "/developer", "/admin/students", "/admin/export.csv"):
            self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.client.post("/developer/recognition-check").status_code, 302)

    def test_disable_revokes_sessions_even_after_reapproval(self):
        account = self.activate()
        cookie = self.client.get_cookie("session").value
        self.staff.post(f"/admin/students/{account['id']}/disable")
        self.staff.post(f"/admin/students/{account['id']}/approve")
        self.client.set_cookie("session", cookie)
        self.assertEqual(self.client.get("/scan").status_code, 302)

    def test_logout_revokes_cookie_replay(self):
        self.activate()
        cookie = self.client.get_cookie("session").value
        self.client.post("/logout")
        self.client.set_cookie("session", cookie)
        self.assertEqual(self.client.get("/scan").status_code, 302)

    def test_idle_expiry_and_background_polling(self):
        self.activate()
        with self.app.app_context():
            db = get_db()
            then = int(time.time()) - 100
            db.execute("UPDATE auth_sessions SET last_seen = ? WHERE role = 'student'", (then,))
            db.commit()
        self.client.get("/api/status")
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT last_seen FROM auth_sessions WHERE role = 'student'").fetchone()[0], then)
        with patch("equipment_manager.auth.time.time", return_value=then + self.app.config["AUTH_IDLE_SECONDS"] + 1):
            self.assertEqual(self.client.post("/api/transactions", json={}).status_code, 401)

    def test_absolute_session_expiry(self):
        self.activate()
        with self.app.app_context():
            db = get_db()
            db.execute("UPDATE auth_sessions SET expires_at = 0 WHERE role = 'student'")
            db.commit()
        self.assertEqual(self.client.get("/scan").status_code, 302)

    def test_env_password_change_invalidates_admin_session(self):
        self.app.config["TEACHER_PASSWORD"] = "updated-teacher-password"
        self.assertEqual(self.staff.get("/admin").status_code, 302)

    def test_expired_login_returns_401_even_with_old_csrf_token(self):
        self.activate()
        with self.client.session_transaction() as state:
            csrf = state["csrf_token"]
        self.app.config["CSRF_ENABLED"] = True
        with self.app.app_context():
            db = get_db()
            db.execute("UPDATE auth_sessions SET expires_at = 0 WHERE role = 'student'")
            db.commit()
        response = self.client.post("/api/transactions", json={}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "login_required")

    def test_admin_login_is_rate_limited_and_mock_production_cannot_lend(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/admin/login", data={"username": "developer", "password": "wrong"}).status_code, 200)
        self.assertEqual(self.client.post("/admin/login", data={"username": "developer", "password": "developer-test-password"}).status_code, 429)
        self.app.config["TESTING"] = False
        self.assertEqual(self.staff.post("/api/scans", json={"mock_equipment_id": 1}).status_code, 422)

    def test_student_password_change_revokes_all_sessions(self):
        self.activate()
        other = self.app.test_client()
        other.post("/login", data={"student_id": "30304", "password": "student-test-password"})
        response = self.client.post("/account/password", data={"old_password": "student-test-password",
            "password": "replacement-test-password", "password_confirm": "replacement-test-password"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(other.get("/scan").status_code, 302)
        self.assertEqual(self.client.get("/scan").status_code, 302)
        self.assertEqual(self.client.post("/login", data={"student_id": "30304", "password": "replacement-test-password"}).status_code, 302)

    def test_login_rate_limit_and_recovery(self):
        self.activate()
        self.client.post("/logout")
        for _ in range(5):
            self.assertEqual(self.client.post("/login", data={"student_id": "30304", "password": "wrong"}).status_code, 200)
        response = self.client.post("/login", data={"student_id": "30304", "password": "student-test-password"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        with patch("equipment_manager.auth.time.time", return_value=time.time() + 301):
            self.assertEqual(self.client.post("/login", data={"student_id": "30304", "password": "student-test-password"}).status_code, 302)

    def test_duplicate_registration_does_not_replace_credentials(self):
        account = self.register()
        response = self.client.post("/register", data={"student_id": "30304", "name": "다른 사람", "password": "different-password", "password_confirm": "different-password"})
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT password_hash FROM student_accounts").fetchone()[0], account["password_hash"])

    def test_only_staff_can_reset_password_and_sessions_are_revoked(self):
        account = self.activate()
        path = f"/admin/students/{account['id']}/password"
        payload = {"password": "staff-reset-password", "password_confirm": "staff-reset-password"}
        self.assertEqual(self.client.post(path, data=payload).status_code, 302)
        self.assertEqual(self.client.get("/scan").status_code, 200)
        self.assertEqual(self.staff.post(path, data=payload).status_code, 302)
        self.assertEqual(self.client.get("/scan").status_code, 302)
        self.assertEqual(self.client.post("/login", data={"student_id": "30304", "password": "staff-reset-password"}).status_code, 302)

    def test_signup_login_approval_logout_require_csrf(self):
        account = self.register()
        self.app.config["CSRF_ENABLED"] = True
        for path in ("/register", "/login", "/logout", f"/admin/students/{account['id']}/approve"):
            response = self.staff.post(path)
            self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT status FROM student_accounts").fetchone()[0], "pending")

    def test_throttle_storage_has_hard_cap_and_prunes_expired_entries(self):
        with self.app.app_context():
            db = get_db()
            now = int(time.time())
            db.executemany("INSERT INTO auth_attempts VALUES (?, 1, ?)",
                           [(hashlib.sha256(str(i).encode()).hexdigest(), now + 300) for i in range(4096)])
            db.commit()
            from equipment_manager.auth import RateLimited
            with self.assertRaises(RateLimited):
                take_attempt("new", "identity")
            with patch("equipment_manager.auth.time.time", return_value=now + 301):
                take_attempt("new", "identity")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM auth_attempts").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
