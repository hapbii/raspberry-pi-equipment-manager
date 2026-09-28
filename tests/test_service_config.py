from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deploy.service_config import render_poweroff_rule, render_service, render_update_rule, render_update_service


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
        (self.app_dir / "serve.py").touch()
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
        self.assertIn('serve.py" --allow-mock', unit)
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
        unit = self.render(allow_mock=True)
        self.assertIn("ExecStart=", unit)
        self.assertNotIn("--allow-mock", unit)

    def test_ncnn_directory_is_accepted(self):
        self.env.write_text("DETECTOR_MODE=yolo\nYOLO_MODEL_PATH=models/best_ncnn_model\n", encoding="utf-8")
        (self.app_dir / "models/best_ncnn_model").mkdir(parents=True)
        self.assertIn("ExecStart=", self.render())

    def test_root_or_unit_injection_is_rejected(self):
        for user in ("root", "pi\nExecStart=/bad"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                render_service(self.app_dir, user, "pi", allow_mock=True)

    def test_missing_entrypoint_is_rejected(self):
        (self.app_dir / "serve.py").unlink()
        with self.assertRaisesRegex(ValueError, "serve.py"):
            self.render(allow_mock=True)

    def test_poweroff_requires_explicit_install_option_and_preserves_sandbox(self):
        self.assertIn("Environment=POWER_OFF_ENABLED=false", self.render(allow_mock=True))
        unit = self.render(allow_mock=True, enable_poweroff=True)
        self.assertIn("Environment=POWER_OFF_ENABLED=true", unit)
        self.assertIn("Environment=SYSTEMD_SERVICE_MANAGED=true", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("TimeoutStopSec=45", unit)
        rule = render_poweroff_rule("pi30304")
        self.assertIn('subject.user === "pi30304"', rule)
        self.assertNotIn("__USER__", rule)
        for user in ("root", 'pi" || true || "', "pi\nroot"):
            with self.assertRaises(ValueError):
                render_poweroff_rule(user)

    @unittest.skipUnless(os.name == "posix" and shutil.which("systemd-analyze"), "requires Linux systemd tools")
    def test_poweroff_units_parse_without_starting_any_service(self):
        source = Path(__file__).resolve().parents[1] / "deploy"
        paths = []
        for name in ("equipment-manager-poweroff.timer", "equipment-manager-poweroff.service",
                     "equipment-manager-stop.timer", "equipment-manager-stop.service"):
            target = Path(self.temp.name) / name
            shutil.copyfile(source / name, target)
            self.assertNotIn("[Install]", target.read_text().split("#")[0])
            paths.append(str(target))
        result = subprocess.run(["systemd-analyze", "verify", *paths], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_program_stop_is_repeatable_and_only_stops_the_app(self):
        source = Path(__file__).resolve().parents[1] / "deploy"
        timer = (source / "equipment-manager-stop.timer").read_text(encoding="utf-8")
        service = (source / "equipment-manager-stop.service").read_text(encoding="utf-8")
        self.assertIn("RemainAfterElapse=no", timer)
        self.assertIn("OnActiveSec=10s", timer)
        self.assertIn("ExecStart=/usr/bin/systemctl stop equipment-manager.service", service)
        self.assertNotIn("poweroff", service)
        self.assertNotIn("disable", service)
        self.assertNotIn("[Install]", service)

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

    def test_update_install_is_independent_and_runner_is_outside_checkout(self):
        self.assertIn("Environment=PROGRAM_UPDATE_ENABLED=false", self.render(allow_mock=True))
        self.assertIn("Environment=PROGRAM_UPDATE_ENABLED=true", self.render(allow_mock=True, enable_update=True))
        self.assertIn("Environment=POWER_OFF_ENABLED=false", self.render(allow_mock=True, enable_update=True))
        unit = render_update_service(self.app_dir, "pi30304", "pi30304", allow_mock=True)
        self.assertIn("ExecStart=:/usr/bin/python3 -I /usr/local/lib/equipment-manager/update_runner.py", unit)
        self.assertIn("kit %%i $HOME", unit)
        self.assertIn("--user pi30304 --allow-mock", unit)
        self.assertIn("ExecStopPost=/usr/bin/systemctl start equipment-manager.service", unit)
        self.assertNotIn("__APP_DIR__", unit)
        self.assertNotIn("private-value", unit)
        self.assertNotIn("[Install]", unit)
        rule = render_update_rule("pi30304")
        self.assertIn('subject.user === "pi30304"', rule)
        self.assertIn('equipment-manager-update.timer', rule)
        with self.assertRaises(ValueError):
            render_update_rule("root")

    @unittest.skipUnless(os.name == "posix" and shutil.which("systemd-analyze"), "requires Linux systemd tools")
    def test_update_units_parse_without_starting_any_service(self):
        service = Path(self.temp.name) / "equipment-manager-update.service"
        service.write_text(render_update_service(self.app_dir, "pi30304", "pi30304", allow_mock=True))
        timer = Path(self.temp.name) / "equipment-manager-update.timer"
        shutil.copyfile(Path(__file__).resolve().parents[1] / "deploy" / timer.name, timer)
        result = subprocess.run(["systemd-analyze", "verify", str(service), str(timer)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
