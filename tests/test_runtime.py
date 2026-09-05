from __future__ import annotations

import unittest

from flask import Flask

from equipment_manager.runtime import HeartbeatService


class HeartbeatServiceTestCase(unittest.TestCase):
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
