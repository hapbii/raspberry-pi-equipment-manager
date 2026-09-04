from __future__ import annotations

import logging
import threading

from .db import cleanup_expired_scan_sessions, set_device_status
from .system_metrics import current_rss_mb


logger = logging.getLogger(__name__)


class HeartbeatService:
    def __init__(self, app):
        self.app = app
        self.interval = max(5, int(app.config["HEARTBEAT_INTERVAL_SECONDS"]))
        self.memory_warning_mb = int(app.config["MEMORY_WARNING_MB"])
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
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=min(5, self.interval + 1))

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                with self.app.app_context():
                    set_device_status()
                    cleanup_expired_scan_sessions()
                rss = current_rss_mb()
                if rss is not None and rss >= self.memory_warning_mb:
                    logger.warning(
                        "Process RSS is high: %.1f MB (warning threshold: %s MB)",
                        rss,
                        self.memory_warning_mb,
                    )
            except Exception:
                logger.exception("Heartbeat update failed")
