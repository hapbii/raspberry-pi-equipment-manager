from __future__ import annotations

import unittest
import threading
from unittest.mock import patch

from flask import Flask

from equipment_manager.runtime import HeartbeatService


class HeartbeatServiceTestCase(unittest.TestCase):
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
