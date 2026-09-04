from __future__ import annotations

import gc
import logging
import threading
from dataclasses import replace
from time import perf_counter

from flask import current_app

from ..system_metrics import current_rss_mb
from .detector import YoloDetector, build_detector
from .types import Detection, DetectionError, PreflightResult


logger = logging.getLogger(__name__)


class DetectionService:
    def __init__(self, detector, gc_interval_scans: int = 20):
        self.detector = detector
        self.gc_interval_scans = max(1, gc_interval_scans)
        self._lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._attempt_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._busy_rejections = 0
        self._closed = False
        self.last_duration_ms: int | None = None
        self.last_error: str | None = None

    def detect(self, category_hint: str | None = None) -> Detection:
        if self._closed:
            raise DetectionError("객체 인식 서비스가 종료되었습니다.")
        if not self._lock.acquire(blocking=False):
            with self._metrics_lock:
                self._busy_rejections += 1
            raise DetectionError("현재 다른 인식 작업을 처리 중입니다. 잠시 후 다시 시도해 주세요.")
        started = perf_counter()
        succeeded = False
        try:
            with self._metrics_lock:
                self._attempt_count += 1
            if self._closed:
                raise DetectionError("객체 인식 서비스가 종료되었습니다.")
            detection = self.detector.detect(category_hint)
            succeeded = True
            duration_ms = round((perf_counter() - started) * 1000)
            return replace(
                detection,
                duration_ms=duration_ms,
                memory_rss_mb=current_rss_mb(),
            )
        except Exception as exc:
            with self._metrics_lock:
                self.last_error = str(exc)[:500]
            raise
        finally:
            duration_ms = round((perf_counter() - started) * 1000)
            with self._metrics_lock:
                self.last_duration_ms = duration_ms
                if succeeded:
                    self._success_count += 1
                    self.last_error = None
                else:
                    self._failure_count += 1
                should_collect = (
                    self._attempt_count > 0
                    and self._attempt_count % self.gc_interval_scans == 0
                )
            if should_collect:
                gc.collect()
            self._lock.release()

    def preflight(self) -> PreflightResult:
        if not isinstance(self.detector, YoloDetector):
            raise DetectionError("실제 YOLO 모드에서만 사전 점검을 실행할 수 있습니다.")
        with self._lock:
            if self._closed:
                raise DetectionError("객체 인식 서비스가 종료되었습니다.")
            return self.detector.preflight()

    def status(self) -> dict:
        with self._metrics_lock:
            return {
                "scan_count": self._success_count,
                "attempt_count": self._attempt_count,
                "failure_count": self._failure_count,
                "busy_rejections": self._busy_rejections,
                "last_duration_ms": self.last_duration_ms,
                "memory_rss_mb": current_rss_mb(),
                "last_error": self.last_error,
                "busy": self._lock.locked(),
                "closed": self._closed,
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.detector.close()


def build_detection_service(config: dict) -> DetectionService:
    return DetectionService(
        detector=build_detector(config),
        gc_interval_scans=int(config["GC_INTERVAL_SCANS"]),
    )


def get_detection_service() -> DetectionService:
    service = current_app.extensions.get("detection_service")
    if service is None:
        raise RuntimeError("Detection service was not initialized")
    return service
