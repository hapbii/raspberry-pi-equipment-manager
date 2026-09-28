from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import update_runner
from equipment_manager import updates


@unittest.skipUnless(shutil.which("git"), "requires Git")
class UpdateRunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "upstream"
        self.source.mkdir()
        self.git(self.source, "init", "-b", "main")
        (self.source / ".gitignore").write_text(".env\ninstance/\n.venv/\nbackups/\n")
        (self.source / "version.txt").write_text("old")
        self.commit(self.source)
        self.app_dir = self.root / "school & kit %i $HOME"
        self.git(self.root, "clone", str(self.source), str(self.app_dir))
        (self.app_dir / ".env").write_text("preserve settings")
        (self.app_dir / "instance").mkdir()
        (self.app_dir / "instance/equipment.db").write_bytes(b"preserve database")
        (self.source / "version.txt").write_text("new")
        self.commit(self.source)
        self.commands = []
        self.events = []
        self.fail_on = None
        self.state_file = self.root / "status.json"
        for target, kwargs in (
            ("deploy.update_runner.STATUS", {"new": self.state_file}),
            ("deploy.update_runner.run_command", {"side_effect": self.command}),
            ("deploy.update_runner.time.sleep", {"side_effect": lambda seconds: self.events.append(f"sleep {seconds}")}),
            ("deploy.update_runner.wait_for_web", {"side_effect": lambda: self.events.append("health")}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def git(self, cwd, *args):
        return subprocess.run([shutil.which("git"), *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, cwd):
        self.git(cwd, "add", ".")
        self.git(cwd, "-c", "user.name=Update Test", "-c", "user.email=test@example.invalid",
                 "commit", "-m", "fixture")

    def command(self, args, *, cwd=None, timeout=60):
        self.commands.append(args)
        if args[0] == "/usr/bin/systemctl":
            action = args[1]
            self.events.append(action)
            if self.fail_on == action:
                raise RuntimeError("injected systemd failure")
            return ""
        self.assertEqual(args[:5], ["/usr/sbin/runuser", "-u", "pi30304", "--", "/usr/bin/env"])
        self.assertIn("GIT_TERMINAL_PROMPT=0", args)
        command = args[7:]
        if command[0] == "/usr/bin/git":
            if command[1] == "pull":
                self.events.append("pull")
                self.assertEqual(command[1:], ["pull", "--ff-only", "origin", "main"])
                if self.fail_on == "pull":
                    raise subprocess.TimeoutExpired(command, timeout)
            return self.git(cwd, *command[1:])
        if command[1].endswith("backup_db.py"):
            self.events.append("backup")
            if self.fail_on == "backup":
                raise RuntimeError("injected backup failure")
        elif command[1].endswith("serve.py"):
            self.events.append("check")
            self.assertEqual(command[2:], ["--check", "--allow-mock"])
            if self.fail_on == "check":
                raise RuntimeError("injected configuration failure")
        else:
            self.fail(f"Unexpected command {command!r}")
        return ""

    def run_update(self):
        return update_runner.update(self.app_dir, "pi30304", allow_mock=True)

    def report(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def test_real_git_fast_forward_restart_order_and_preserved_runtime_data(self):
        self.assertEqual(self.run_update(), 0)
        self.assertEqual(self.events, ["stop", "sleep 2", "backup", "pull", "check", "sleep 2", "start", "health"])
        self.assertEqual((self.app_dir / "version.txt").read_text(), "new")
        self.assertEqual((self.app_dir / ".env").read_text(), "preserve settings")
        self.assertEqual((self.app_dir / "instance/equipment.db").read_bytes(), b"preserve database")
        self.assertEqual(self.report()["state"], "success")
        self.assertEqual(self.report()["after"], self.git(self.source, "rev-parse", "HEAD"))
        self.assertNotEqual(self.report()["before"], self.report()["after"])

    def test_dirty_checkout_and_wrong_branch_do_not_stop_server(self):
        for condition in ("dirty", "branch"):
            with self.subTest(condition=condition):
                if condition == "dirty":
                    (self.app_dir / "version.txt").write_text("user changes")
                else:
                    (self.app_dir / "version.txt").write_text("old")
                    self.git(self.app_dir, "switch", "-c", "work")
                self.assertEqual(self.run_update(), 1)
                self.assertEqual(self.events, [])
                self.assertEqual(self.report()["state"], "failed")

    def test_diverged_git_history_is_preserved_and_server_restarts(self):
        (self.app_dir / "local.txt").write_text("local work")
        self.commit(self.app_dir)
        before = self.git(self.app_dir, "rev-parse", "HEAD")
        self.assertEqual(self.run_update(), 1)
        self.assertEqual(self.git(self.app_dir, "rev-parse", "HEAD"), before)
        self.assertEqual((self.app_dir / "local.txt").read_text(), "local work")
        self.assertEqual(self.events[-2:], ["start", "health"])
        self.assertEqual(self.report()["state"], "failed")

    def test_local_commits_ahead_of_remote_are_not_reported_as_updated(self):
        self.git(self.app_dir, "pull", "--ff-only", "origin", "main")
        (self.app_dir / "local.txt").write_text("unpublished work")
        self.commit(self.app_dir)
        before = self.git(self.app_dir, "rev-parse", "HEAD")
        self.assertEqual(self.run_update(), 1)
        self.assertEqual(self.report()["state"], "failed")
        self.assertEqual(self.git(self.app_dir, "rev-parse", "HEAD"), before)
        self.assertEqual(self.events[-2:], ["start", "health"])

    def test_timeout_backup_and_validation_failures_recover_without_claiming_success(self):
        for stage in ("pull", "backup", "check", "stop"):
            with self.subTest(stage=stage):
                self.fail_on = stage
                self.events.clear()
                self.assertEqual(self.run_update(), 1)
                self.assertEqual(self.events[-2:], ["start", "health"])
                self.assertEqual(self.report()["state"], "failed")
                if stage in {"backup", "stop"}:
                    self.assertNotIn("pull", self.events)

    def test_start_failure_reports_need_for_ssh_recovery(self):
        self.fail_on = "start"
        self.assertEqual(self.run_update(), 1)
        self.assertEqual(self.report()["state"], "failed")
        self.assertIn("복구도 확인하지 못했습니다", self.report()["message"])


class UpdateStatusTestCase(unittest.TestCase):
    def test_missing_corrupt_or_unexpected_status_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            status = Path(folder) / "status.json"
            with patch.object(updates, "UPDATE_STATUS", status):
                self.assertIsNone(updates.update_status())
                for text in ("{", "[]", '{"state":"invalid"}'):
                    status.write_text(text)
                    self.assertIsNone(updates.update_status())
                status.write_text('{"state":"success","message":"complete"}')
                self.assertEqual(updates.update_status()["message"], "complete")
