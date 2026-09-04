from __future__ import annotations

import logging
import threading

from .db import set_device_status


logger = logging.getLogger(__name__)


class HeartbeatService:
    def __init__(self, app):
        self.app = app
        self.interval = max(5, int(app.config["HEARTBEAT_INTERVAL_SECONDS"]))
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="equipment-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                with self.app.app_context():
                    set_device_status()
            except Exception:
                logger.exception("Heartbeat update failed")
