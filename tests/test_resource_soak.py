"""Repeat web workflows using a temporary DB, never .env or physical hardware."""
from __future__ import annotations

import argparse
import gc
import json
import logging
import sys
import tempfile
import threading
import unittest
import weakref
from collections import deque
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from equipment_manager import create_app
from equipment_manager.auth import cleanup_expired_auth
from equipment_manager.db import get_db
from equipment_manager.system_metrics import current_rss_mb


def run_web_soak(cycles: int, warmup: int = 50) -> dict:
    logger = logging.getLogger("equipment_manager")
    handlers_before = list(logger.handlers)
    threads_before = threading.active_count()
    samples = deque(maxlen=6)
    with tempfile.TemporaryDirectory(prefix="equipment-web-soak-") as directory:
        app = create_app({
            "TESTING": True, "HEARTBEAT_ENABLED": False, "DETECTOR_MODE": "mock",
            "GPIO_ENABLED": False, "SECRET_KEY": "isolated-resource-test",
            "CSRF_ENABLED": False, "DUPLICATE_WINDOW_SECONDS": 0,
            "DATABASE": str(Path(directory) / "test.db"),
            "ERROR_LOG_PATH": str(Path(directory) / "errors.log"),
            "DEFAULT_EQUIPMENT": ["Resource test equipment"], "DEFAULT_QUANTITY": 10,
            "DEFAULT_LOAN_DAYS": 7,
            "TEACHER_USERNAME": "resource-test-teacher", "TEACHER_PASSWORD": "resource-test-password",
            "DEVELOPER_USERNAME": "resource-test-developer", "DEVELOPER_PASSWORD": "unused-test-password",
        })
        reference = weakref.ref(app)
        client = app.test_client()

        def post_json(path, payload):
            with client.post(path, json=payload) as response:
                data = response.get_json()
                if response.status_code != 200 or not data["ok"]:
                    raise AssertionError((path, response.status_code, data))
                return data

        def cycle():
            for action in ("loan", "return"):
                scan = post_json("/api/scans", {"mock_equipment_id": 1})["scan"]
                post_json("/api/transactions", {
                    "scan_token": scan["token"], "student_id": "resource-test-student",
                    "action": action, "quantity": 1, "reason": "Resource regression check",
                })
            for path in ("/admin", "/api/status", "/admin/export.csv"):
                with client.get(path) as response:
                    if response.status_code != 200:
                        raise AssertionError((path, response.status_code))
            with app.app_context():
                cleanup_expired_auth()
            app.extensions["error_log_store"].snapshot()

        try:
            with client.post("/admin/login", data={
                "username": "resource-test-teacher", "password": "resource-test-password",
            }) as response:
                if response.status_code != 302:
                    raise AssertionError("Test login failed")
            for _ in range(warmup):
                cycle()
            gc.collect()
            baseline = current_rss_mb()
            for index in range(cycles):
                cycle()
                if (index + 1) % max(1, cycles // 5) == 0:
                    samples.append(current_rss_mb())
            final = current_rss_mb()
            with app.app_context():
                db = get_db()
                transaction_count = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
                balance = db.execute("SELECT SUM(remaining_quantity) FROM active_loans").fetchone()[0]
                integrity_ok = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                integrity_ok = integrity_ok and not db.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            app.extensions["shutdown_services"]()
        client = app = None
        gc.collect()
        return {
            "cycles": cycles, "warmup_cycles": warmup,
            "baseline_rss_mb": baseline, "rss_samples_mb": list(samples), "final_rss_mb": final,
            "transactions": transaction_count, "outstanding_quantity": balance,
            "database_integrity_ok": integrity_ok,
            "thread_count_before": threads_before, "thread_count_after": threading.active_count(),
            "log_handlers_restored": logger.handlers == handlers_before,
            "application_released": reference() is None,
        }


class WebResourceSoakTest(unittest.TestCase):
    def test_repeated_requests_release_application_handlers_and_balances(self):
        report = run_web_soak(cycles=30, warmup=5)
        self.assertTrue(report["application_released"])
        self.assertTrue(report["log_handlers_restored"])
        self.assertTrue(report["database_integrity_ok"])
        self.assertEqual(report["transactions"], 70)
        self.assertEqual(report["outstanding_quantity"], 0)
        self.assertEqual(report["thread_count_after"], report["thread_count_before"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=50)
    args = parser.parse_args()
    if args.cycles < 1 or args.warmup < 0:
        parser.error("cycles must be positive and warmup must be nonnegative")
    report = run_web_soak(args.cycles, args.warmup)
    print(json.dumps(report, indent=2))
    if not (
        report["application_released"] and report["log_handlers_restored"]
        and report["database_integrity_ok"] and report["outstanding_quantity"] == 0
        and report["transactions"] == 2 * (args.cycles + args.warmup)
        and report["thread_count_after"] == report["thread_count_before"]
    ):
        raise SystemExit(1)
