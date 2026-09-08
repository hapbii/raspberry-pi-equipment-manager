from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from unittest.mock import patch

from waitress import create_server, wasyncore
from waitress.adjustments import Adjustments

import serve
from equipment_manager.deployment import WAITRESS_OPTIONS, validate_deployment


class DeploymentTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {
            "SECRET_KEY": "random-secret-for-validation-123456789",
            "DEVELOPER_USERNAME": "developer",
            "DEVELOPER_PASSWORD": "private-developer-password",
            "TEACHER_USERNAME": "선생님",
            "TEACHER_PASSWORD": "private-teacher-password",
            "STATION_AUTH_REQUIRED": True,
            "STATION_PIN": "482715",
            "DETECTOR_MODE": "mock",
            "YOLO_MODEL_PATH": "models/best.pt",
        }

    def test_mock_requires_opt_in_even_with_valid_credentials(self):
        with self.assertRaisesRegex(ValueError, "DETECTOR_MODE"):
            validate_deployment(self.config, self.root)
        validate_deployment(self.config, self.root, allow_mock=True)

    def test_unsafe_settings_are_rejected_without_disclosing_values(self):
        cases = {
            "SECRET_KEY": "dev-secret-change-before-school-use",
            "TEACHER_PASSWORD": "teacher1234",
            "DEVELOPER_PASSWORD": "short",
            "TEACHER_USERNAME": "developer",
            "STATION_PIN": "1234",
            "CSRF_ENABLED": False,
            "STATION_AUTH_REQUIRED": False,
            "DEBUG": True,
            "TESTING": True,
        }
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaises(ValueError) as caught:
                validate_deployment(self.config | {key: value}, self.root, allow_mock=True)
            self.assertIn(key, str(caught.exception))
            self.assertNotIn("private-developer-password", str(caught.exception))
            self.assertNotIn("private-teacher-password", str(caught.exception))

    def test_yolo_is_not_bypassed_by_preview_option(self):
        self.config["DETECTOR_MODE"] = "yolo"
        with self.assertRaisesRegex(ValueError, "YOLO_MODEL_PATH"):
            validate_deployment(self.config, self.root, allow_mock=True)
        model = self.root / "models/best.pt"
        model.parent.mkdir()
        model.touch()
        validate_deployment(self.config, self.root)

    def test_waitress_accepts_bounded_options(self):
        settings = Adjustments(**WAITRESS_OPTIONS)
        self.assertEqual(settings.threads, 2)
        self.assertEqual(settings.connection_limit, 32)
        self.assertEqual(settings.max_request_body_size, 1_000_000)
        self.assertFalse(settings.expose_tracebacks)

    def test_check_command_is_read_only_and_does_not_open_app(self):
        # Use a clean process so dotenv/Config do not inherit the test runner's cache.
        source_root = Path(__file__).resolve().parent.parent
        shutil.copy2(source_root / "serve.py", self.root / "serve.py")
        shutil.copytree(source_root / "equipment_manager", self.root / "equipment_manager",
                        ignore=shutil.ignore_patterns("__pycache__"))
        env_path = self.root / ".env"
        env_path.write_text("\n".join(f"{key}={value}" for key, value in self.config.items()), encoding="utf-8")
        original = env_path.read_bytes()
        env = {key: value for key, value in os.environ.items()
               if key not in self.config and key not in {"CSRF_ENABLED", "DATABASE", "ERROR_LOG_PATH"}}
        env["PYTHONIOENCODING"] = "utf-8"
        for extra, expected_code in (([], 1), (["--allow-mock"], 0)):
            result = subprocess.run(
                [sys.executable, str(self.root / "serve.py"), "--check", *extra],
                cwd=source_root, env=env, capture_output=True, encoding="utf-8", timeout=20,
            )
            self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
            self.assertNotIn(self.config["DEVELOPER_PASSWORD"], result.stdout + result.stderr)
        self.assertEqual(original, env_path.read_bytes())
        self.assertFalse((self.root / "instance").exists())

    def test_server_failure_closes_application_resources(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        (self.root / ".env").touch()
        previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, previous_cwd)
        app = Mock()
        cleanup = Mock()
        app.extensions = {"shutdown_services": cleanup}
        with patch.object(serve, "ROOT", self.root), patch.dict(os.environ), \
             patch("equipment_manager.config.Config", SimpleNamespace(**self.config)), \
             patch("equipment_manager.create_app", return_value=app) as factory, \
             patch("equipment_manager.web_server.run_web_server", side_effect=OSError("port busy")):
            with self.assertRaisesRegex(OSError, "port busy"):
                serve.main(["--allow-mock"])
        factory.assert_called_once_with({"DEBUG": False, "TESTING": False})
        cleanup.assert_called_once_with()

    def test_live_waitress_serves_login_with_csrf_and_remains_healthy(self):
        from equipment_manager import create_app

        app = create_app(self.config | {
            "DATABASE": str(self.root / "equipment.db"),
            "ERROR_LOG_PATH": str(self.root / "errors.log"),
            "HEARTBEAT_ENABLED": False,
            "CSRF_ENABLED": True,
            "TESTING": False,
            "DEBUG": False,
            "SESSION_COOKIE_SECURE": False,
        })
        self.addCleanup(app.extensions["shutdown_services"])
        channels = {}
        server = create_server(app, map=channels, **(WAITRESS_OPTIONS | {
            "host": "127.0.0.1", "port": 0, "asyncore_loop_timeout": 0.1,
        }))
        worker = threading.Thread(target=server.run, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{server.effective_port}"
            client = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
            with client.open(base + "/admin/login", timeout=5) as response:
                html = response.read().decode("utf-8")
            token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
            payload = urlencode({
                "username": self.config["TEACHER_USERNAME"],
                "password": self.config["TEACHER_PASSWORD"],
                "csrf_token": token,
            }).encode("utf-8")
            with client.open(Request(base + "/admin/login", data=payload), timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.url.endswith("/admin"))
            with client.open(base + "/healthz", timeout=5) as response:
                self.assertTrue(json.load(response)["ok"])
        finally:
            server.task_dispatcher.shutdown()
            wasyncore.close_all(map=channels)
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
