from __future__ import annotations

import unittest
import threading
import gc
import weakref
from unittest.mock import patch

from flask import Flask, has_app_context

from equipment_manager.runtime import HeartbeatService


class HeartbeatServiceTestCase(unittest.TestCase):
    def test_retained_maintenance_logs_do_not_keep_buffers_or_disposed_apps(self):
        references, calls = [], []

        class Buffer:
            def __init__(self):
                self.pixels = bytearray(640 * 480 * 3)

        def failing_task():
            buffer = Buffer()
            references.append(weakref.ref(buffer))
            raise RuntimeError("maintenance failed")

        def next_task():
            self.assertTrue(has_app_context())
            calls.append(True)

        with patch("equipment_manager.runtime.set_device_status", failing_task), patch(
            "equipment_manager.runtime.cleanup_expired_scan_sessions", next_task
        ), patch("equipment_manager.runtime.cleanup_expired_auth", next_task), self.assertLogs(
            "equipment_manager.runtime", level="ERROR"
        ) as captured:
            for _ in range(100):
                app = Flask(__name__)
                references.append(weakref.ref(app))
                HeartbeatService._maintain(app)
                app = None
        gc.collect()
        # Keep raw LogRecord.exc_info alive, as a buffered handler would.
        self.assertEqual(len(captured.records), 100)
        self.assertEqual(len(calls), 200)
        self.assertFalse(has_app_context())
        self.assertTrue(all(reference() is None for reference in references))

    def test_cleanup_failure_does_not_skip_other_jobs_or_retain_context(self):
        from flask import has_app_context
        app = Flask(__name__)
        calls = []

        def status():
            self.assertTrue(has_app_context())
            calls.append("status")

        def scans():
            self.assertTrue(has_app_context())
            calls.append("scans")
            raise RuntimeError("scan cleanup failure")

        def auth():
            self.assertTrue(has_app_context())
            calls.append("auth")

        with patch("equipment_manager.runtime.set_device_status", status), patch(
            "equipment_manager.runtime.cleanup_expired_scan_sessions", scans
        ), patch("equipment_manager.runtime.cleanup_expired_auth", auth), self.assertLogs(
            "equipment_manager.runtime", level="ERROR"
        ):
            HeartbeatService._maintain(app)
        self.assertEqual(calls, ["status", "scans", "auth"])
        self.assertFalse(has_app_context())

    def test_delayed_worker_exit_releases_app_after_stop_timeout(self):
        app = Flask(__name__)
        app.config.update(HEARTBEAT_INTERVAL_SECONDS=5, MEMORY_WARNING_MB=1200)
        service = HeartbeatService(app)
        entered, finish = threading.Event(), threading.Event()

        def blocked_loop():
            entered.set()
            finish.wait(2)

        with patch.object(service, "_run_loop", side_effect=blocked_loop):
            service.start()
            try:
                self.assertTrue(entered.wait(1))
                with patch.object(service._thread, "join"):
                    service.stop()
                self.assertIsNotNone(service._app)
            finally:
                finish.set()
                service._thread.join(2)
        self.assertFalse(service._thread.is_alive())
        self.assertIsNone(service._app)

    def test_stop_joins_worker_and_releases_app_reference(self):
        app = Flask(__name__)
        app.config.update(
            HEARTBEAT_INTERVAL_SECONDS=5,
            MEMORY_WARNING_MB=1200,
        )
        heartbeat = HeartbeatService(app)

        heartbeat.start()
        heartbeat.stop()

        self.assertFalse(heartbeat._thread.is_alive())
        self.assertIsNone(heartbeat._app)


if __name__ == "__main__":
    unittest.main()
