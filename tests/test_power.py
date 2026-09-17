from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from equipment_manager import create_app
from equipment_manager.power import (
    POWER_TIMER, PROGRAM_STOP_TIMER, SYSTEMCTL, poweroff_available,
    program_stop_available, schedule_poweroff, schedule_program_stop,
)


class PowerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({
            "TESTING": True, "HEARTBEAT_ENABLED": False, "CSRF_ENABLED": False,
            "DETECTOR_MODE": "mock", "SECRET_KEY": "power-test-secret",
            "DATABASE": str(Path(self.temp.name) / "test.db"),
            "ERROR_LOG_PATH": str(Path(self.temp.name) / "errors.log"),
            "TEACHER_USERNAME": "teacher", "TEACHER_PASSWORD": "teacher-test-password",
            "DEVELOPER_USERNAME": "developer", "DEVELOPER_PASSWORD": "developer-test-password",
            "POWER_OFF_ENABLED": False,
            "SYSTEMD_SERVICE_MANAGED": False,
        })
        self.addCleanup(self.app.extensions["shutdown_services"])
        self.client = self.app.test_client()
        # Never allow tests to run a real system command, even on a Pi.
        runner = patch("equipment_manager.power.subprocess.run")
        self.run = runner.start()
        self.run.return_value.returncode = 0
        self.addCleanup(runner.stop)

    def login(self, role="developer"):
        self.client.post("/admin/login", data={"username": role, "password": f"{role}-test-password"})

    def post(self, **data):
        return self.client.post("/developer/poweroff", data={
            "confirmation": "poweroff", "password": "developer-test-password", **data,
        })

    def stop_program(self, **data):
        return self.client.post("/developer/program-stop", data={
            "confirmation": "program-stop", "password": "developer-test-password", **data,
        })

    def test_guest_teacher_and_student_cannot_access_or_shutdown(self):
        for role in (None, "teacher", "student"):
            with self.subTest(role=role):
                self.client = self.app.test_client()
                if role == "teacher":
                    self.login(role)
                elif role == "student":
                    with patch("equipment_manager.auth.PASSWORD_METHOD", "pbkdf2:sha256:1000"):
                        self.client.post("/register", data={"student_id": "30304", "name": "Student",
                            "password": "student-password", "password_confirm": "student-password"})
                    from equipment_manager.db import get_db
                    with self.app.app_context():
                        db = get_db()
                        with db:
                            db.execute("UPDATE student_accounts SET status='active'")
                    self.client.post("/login", data={"student_id": "30304", "password": "student-password"})
                self.assertEqual(self.client.get("/developer/poweroff").status_code, 302)
                self.assertEqual(self.post().status_code, 302)
                self.assertEqual(self.client.get("/developer/program-stop").status_code, 302)
                self.assertEqual(self.stop_program().status_code, 302)
                self.assertNotIn("/developer/program-stop", self.client.get("/").get_data(as_text=True))
                self.assertNotIn("/developer/poweroff", self.client.get("/").get_data(as_text=True))
        self.run.assert_not_called()

    def test_get_does_not_shutdown_and_disabled_post_fails(self):
        self.login()
        self.assertEqual(self.client.get("/developer/poweroff").status_code, 200)
        self.assertEqual(self.post().status_code, 503)
        self.run.assert_not_called()

    def test_password_confirmation_and_csrf_required(self):
        self.login()
        with patch("equipment_manager.routes.developer.poweroff_available", return_value=True):
            self.assertEqual(self.post(confirmation="").status_code, 400)
            self.assertEqual(self.post(password="wrong").status_code, 400)
            self.app.config["CSRF_ENABLED"] = True
            self.assertEqual(self.post().status_code, 302)
        self.run.assert_not_called()

    def test_success_uses_fixed_command_and_csrf(self):
        self.login()
        self.app.config["CSRF_ENABLED"] = True
        with self.client.session_transaction() as session:
            csrf = session["csrf_token"]
        with patch("equipment_manager.routes.developer.poweroff_available", return_value=True), \
             patch("equipment_manager.power.poweroff_available", return_value=True):
            self.assertEqual(self.client.get("/developer/poweroff").status_code, 200)
            self.run.assert_not_called()
            response = self.post(csrf_token=csrf, command="reboot", unit="evil.service")
        self.assertEqual(response.status_code, 202)
        self.assertIn("종료를 요청했습니다", response.get_data(as_text=True))
        self.run.assert_called_once_with(
            [SYSTEMCTL, "--no-ask-password", "start", POWER_TIMER],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5, check=False,
        )

    def test_repeated_bad_passwords_are_throttled(self):
        self.login()
        with patch("equipment_manager.routes.developer.poweroff_available", return_value=True):
            for _ in range(5):
                self.assertEqual(self.post(password="wrong").status_code, 400)
            self.assertEqual(self.post().status_code, 429)
        self.run.assert_not_called()

    def test_command_failures_never_claim_success(self):
        self.login()
        for failure in (PermissionError("denied"), subprocess.TimeoutExpired("systemctl", 5), None):
            with self.subTest(failure=failure), \
                 patch("equipment_manager.routes.developer.poweroff_available", return_value=True), \
                 patch("equipment_manager.power.poweroff_available", return_value=True):
                self.run.side_effect = failure
                self.run.return_value.returncode = 1
                response = self.post()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("종료를 요청했습니다", response.get_data(as_text=True))

    def test_availability_is_opt_in_linux_only_and_requires_installation(self):
        with self.app.app_context(), patch("equipment_manager.power.sys.platform", "linux"), \
             patch("equipment_manager.power.Path.is_dir", return_value=True), \
             patch("equipment_manager.power.Path.is_file", return_value=True):
            self.assertFalse(poweroff_available())
            with self.assertRaises(RuntimeError):
                schedule_poweroff()
            self.app.config["POWER_OFF_ENABLED"] = True
            self.assertTrue(poweroff_available())
            with patch("equipment_manager.power.sys.platform", "win32"):
                self.assertFalse(poweroff_available())
            with patch("equipment_manager.power.Path.is_file", return_value=False):
                self.assertFalse(poweroff_available())
        self.run.assert_not_called()

    def test_program_stop_requires_managed_service_and_installed_timer(self):
        with self.app.app_context(), patch("equipment_manager.power.sys.platform", "linux"), \
             patch("equipment_manager.power.Path.is_dir", return_value=True), \
             patch("equipment_manager.power.Path.is_file", return_value=True):
            self.app.config["POWER_OFF_ENABLED"] = True
            self.assertFalse(program_stop_available())
            with self.assertRaises(RuntimeError):
                schedule_program_stop()
            self.app.config["SYSTEMD_SERVICE_MANAGED"] = True
            self.assertTrue(program_stop_available())
            with patch("equipment_manager.power.Path.is_file", side_effect=lambda: False):
                self.assertFalse(program_stop_available())
            with patch("equipment_manager.power.sys.platform", "win32"):
                self.assertFalse(program_stop_available())
            self.app.config["POWER_OFF_ENABLED"] = False
            self.assertFalse(program_stop_available())
        self.run.assert_not_called()

    def test_program_stop_get_disabled_post_confirmation_password_and_csrf(self):
        self.login()
        self.assertEqual(self.client.get("/developer/program-stop").status_code, 200)
        self.assertEqual(self.stop_program().status_code, 503)
        with patch("equipment_manager.routes.developer.program_stop_available", return_value=True):
            self.assertEqual(self.client.get("/developer/program-stop").status_code, 200)
            self.assertEqual(self.stop_program(confirmation="poweroff").status_code, 400)
            self.assertEqual(self.stop_program(password="wrong").status_code, 400)
            self.app.config["CSRF_ENABLED"] = True
            self.assertEqual(self.stop_program().status_code, 302)
        self.run.assert_not_called()

    def test_program_stop_uses_only_fixed_timer_and_displays_recovery(self):
        self.login()
        self.app.config["CSRF_ENABLED"] = True
        with self.client.session_transaction() as session:
            csrf = session["csrf_token"]
        with patch("equipment_manager.routes.developer.program_stop_available", return_value=True), \
             patch("equipment_manager.power.program_stop_available", return_value=True):
            response = self.stop_program(csrf_token=csrf, unit=POWER_TIMER, command="poweroff")
        self.assertEqual(response.status_code, 202)
        self.assertIn("sudo systemctl start equipment-manager.service", response.get_data(as_text=True))
        self.run.assert_called_once_with(
            [SYSTEMCTL, "--no-ask-password", "start", PROGRAM_STOP_TIMER],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5, check=False,
        )

    def test_stop_and_poweroff_share_password_retry_limit(self):
        self.login()
        with patch("equipment_manager.routes.developer.program_stop_available", return_value=True), \
             patch("equipment_manager.routes.developer.poweroff_available", return_value=True):
            for _ in range(5):
                self.assertEqual(self.stop_program(password="wrong").status_code, 400)
            self.assertEqual(self.post().status_code, 429)
            self.assertEqual(self.stop_program().status_code, 429)
        self.run.assert_not_called()

    def test_program_stop_command_failures_do_not_claim_success(self):
        self.login()
        for failure in (PermissionError("denied"), subprocess.TimeoutExpired("systemctl", 5), None):
            with self.subTest(failure=failure), \
                 patch("equipment_manager.routes.developer.program_stop_available", return_value=True), \
                 patch("equipment_manager.power.program_stop_available", return_value=True):
                self.run.side_effect = failure
                self.run.return_value.returncode = 1
                response = self.stop_program()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("프로그램 종료를 요청했습니다", response.get_data(as_text=True))

    def test_developer_sees_both_buttons_but_old_install_has_no_stop_button(self):
        self.login()
        with patch("equipment_manager.routes.developer.program_stop_available", return_value=True), \
             patch("equipment_manager.routes.developer.poweroff_available", return_value=True):
            html = self.client.get("/developer").get_data(as_text=True)
            self.assertIn('href="/developer/program-stop"', html)
            self.assertIn('href="/developer/poweroff"', html)
        with patch("equipment_manager.routes.developer.program_stop_available", return_value=False):
            self.assertNotIn('href="/developer/program-stop"', self.client.get("/developer").get_data(as_text=True))
        self.run.assert_not_called()
