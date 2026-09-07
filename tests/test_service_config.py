from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deploy.service_config import render_service


class ServiceConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app_dir = Path(self.temp.name) / "school & kit %i $HOME"
        self.app_dir.mkdir()
        python = self.app_dir / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        if os.name != "nt":
            python.symlink_to(sys.executable)
        else:
            python.write_text("python placeholder", encoding="utf-8")
        (self.app_dir / "wsgi.py").touch()
        self.env = self.app_dir / ".env"
        self.env.write_text("DETECTOR_MODE=mock\nTEACHER_PASSWORD=private-value\n", encoding="utf-8")

    def render(self, **options):
        return render_service(self.app_dir, "pi30304", "pi30304", **options)

    def test_mock_requires_explicit_option_and_does_not_modify_env(self):
        original = self.env.read_bytes()
        with self.assertRaisesRegex(ValueError, "--allow-mock"):
            self.render()
        unit = self.render(allow_mock=True)
        self.assertEqual(self.env.read_bytes(), original)
        self.assertIn("User=pi30304", unit)
        self.assertIn("kit %%i $HOME", unit)
        self.assertIn('ExecStart=:"', unit)
        self.assertNotIn("private-value", unit)
        self.assertNotIn("EnvironmentFile=", unit)
        self.assertNotIn("git pull", unit)

    def test_allow_mock_does_not_bypass_missing_yolo_model(self):
        self.env.write_text('DETECTOR_MODE="yolo" # camera\nYOLO_MODEL_PATH="models/my model.pt"\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "YOLO"):
            self.render(allow_mock=True)
        model = self.app_dir / "models/my model.pt"
        model.parent.mkdir()
        model.touch()
        self.assertIn("ExecStart=", self.render())

    def test_ncnn_directory_is_accepted(self):
        self.env.write_text("DETECTOR_MODE=yolo\nYOLO_MODEL_PATH=models/best_ncnn_model\n", encoding="utf-8")
        (self.app_dir / "models/best_ncnn_model").mkdir(parents=True)
        self.assertIn("ExecStart=", self.render())

    def test_root_or_unit_injection_is_rejected(self):
        for user in ("root", "pi\nExecStart=/bad"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                render_service(self.app_dir, user, "pi", allow_mock=True)

    def test_missing_entrypoint_is_rejected(self):
        (self.app_dir / "wsgi.py").unlink()
        with self.assertRaisesRegex(ValueError, "wsgi.py"):
            self.render(allow_mock=True)

    def test_missing_env_and_invalid_mode_are_rejected(self):
        self.env.write_text("DETECTOR_MODE=typo", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mock 또는 yolo"):
            self.render(allow_mock=True)
        self.env.unlink()
        with self.assertRaisesRegex(ValueError, ".env가 없습니다"):
            self.render(allow_mock=True)

    @unittest.skipUnless(os.name == "posix" and shutil.which("systemd-analyze"), "requires Linux systemd tools")
    def test_generated_unit_passes_systemd_verification(self):
        # No service is installed or started; use real Linux parsing in CI.
        unit_path = Path(self.temp.name) / "equipment-manager.service"
        unit_path.write_text(self.render(allow_mock=True), encoding="utf-8")
        result = subprocess.run(
            ["systemd-analyze", "verify", str(unit_path)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
