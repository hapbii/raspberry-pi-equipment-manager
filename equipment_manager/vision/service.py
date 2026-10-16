from __future__ import annotations

import gc
import logging
import threading
from dataclasses import replace
from contextlib import contextmanager
from time import perf_counter

from flask import current_app

from ..system_metrics import current_rss_mb
from ..db import utc_now
from ..resources import release_error_frames
from .detector import YoloDetector, build_detector
from .types import CameraError, Detection, DetectionError, PreflightResult


logger = logging.getLogger(__name__)


class DetectionService:
    def __init__(self, detector, gc_interval_scans: int = 20):
        self._detector = detector
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
        self.check_state = "unchecked"
        self.checked_at: str | None = None

    def _record_check(self, state: str) -> None:
        checked_at = None
        try:
            checked_at = utc_now()
        except Exception as exc:
            release_error_frames(exc)
            logger.warning("Recognition status timestamp unavailable", exc_info=True)
        with self._metrics_lock:
            self.check_state = state
            self.checked_at = checked_at

    @contextmanager
    def _operation(self, busy_message: str, *, count_busy: bool = False):
        """Serialize camera work and release error frames at one boundary."""
        if self._closed:
            raise DetectionError("객체 인식 서비스가 종료되었습니다.")
        if not self._lock.acquire(blocking=False):
            if count_busy:
                with self._metrics_lock:
                    self._busy_rejections += 1
            raise DetectionError(busy_message)
        try:
            # Shutdown may have acquired the lock after the first state read.
            if self._closed:
                raise DetectionError("객체 인식 서비스가 종료되었습니다.")
            yield
        except BaseException as exc:
            # Includes metadata/GC failures after inference has returned.
            release_error_frames(exc)
            raise
        finally:
            # Metrics and cleanup may also fail; neither may strand the lock.
            self._lock.release()

    def detect(self, category_hint: str | None = None) -> Detection:
        with self._operation(
            "현재 다른 인식 작업을 처리 중입니다. 잠시 후 다시 시도해 주세요.", count_busy=True,
        ):
            return self._detect_locked(category_hint)

    def _detect_locked(self, category_hint: str | None) -> Detection:
        started = duration_ms = None
        succeeded = False
        try:
            with self._metrics_lock:
                self._attempt_count += 1
            started = perf_counter()
            detector = self._detector
            if detector is None:
                raise DetectionError("객체 인식 서비스가 종료되었습니다.")
            detection = detector.detect(category_hint)
            duration_ms = round((perf_counter() - started) * 1000)
            result = replace(
                detection,
                duration_ms=duration_ms,
                memory_rss_mb=current_rss_mb(),
            )
            self._record_check("ready")
            succeeded = True
            return result
        except Exception as exc:
            self._record_check("camera_error" if isinstance(exc, CameraError) else "inference_error")
            with self._metrics_lock:
                self.last_error = str(exc)[:500]
            raise
        finally:
            self._finish_attempt(started, succeeded, duration_ms)

    def _finish_attempt(self, started: float | None, succeeded: bool, duration_ms: int | None) -> None:
        # Reuse the duration already measured on success. On failure, optional
        # final timing must not replace the original camera/inference error.
        if duration_ms is None and started is not None:
            try:
                duration_ms = round((perf_counter() - started) * 1000)
            except Exception as exc:
                release_error_frames(exc)
                logger.warning("Recognition duration unavailable", exc_info=True)
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
            try:
                gc.collect()
            except Exception as exc:
                release_error_frames(exc)
                logger.warning("Post-inference garbage collection failed", exc_info=True)

    def preflight(self) -> PreflightResult:
        detector = None
        try:
            with self._operation("현재 인식 중입니다. 잠시 후 점검해 주세요."):
                detector = self._detector
                if not isinstance(detector, YoloDetector):
                    raise DetectionError("실제 YOLO 모드에서만 사전 점검을 실행할 수 있습니다.")
                try:
                    result = detector.preflight()
                except Exception as exc:
                    self._record_check("camera_error" if isinstance(exc, CameraError) else "inference_error")
                    raise
                self._record_check("ready")
                return result
        finally:
            detector = None

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
                "check_state": self.check_state,
                "checked_at": self.checked_at,
            }

    @contextmanager
    def transaction(self, config: dict):
        # A mode change cannot slip between the HTTP mode check and DB commit.
        with self._operation("다른 인식·거래를 처리 중입니다. 잠시 후 다시 시도해 주세요."):
            if config["DETECTOR_MODE"] == "mock" and not config["TESTING"]:
                raise DetectionError("모의 모드에서는 실제 대여·반납을 할 수 없습니다.")
            yield

    def switch_mode(self, config: dict, mode: str, expected: str, persist) -> bool:
        """Replace the backend only when idle; keep the service/lock identity."""
        with self._operation("인식·점검 중에는 모드를 바꿀 수 없습니다. 완료 후 다시 시도해 주세요."):
            if config["DETECTOR_MODE"] != expected:
                raise DetectionError("다른 요청에서 모드가 변경되었습니다. 새로고침 후 다시 시도해 주세요.")
            if mode == expected:
                return False
            replacement = previous = None
            try:
                # Constructors are lazy: opening the camera/loading the model
                # remains the job of the next preflight or real scan.
                replacement = build_detector(dict(config, DETECTOR_MODE=mode))
                persist()
                previous, self._detector = self._detector, replacement
                replacement = None
                config.update(DETECTOR_MODE=mode, ALLOW_MOCK_MODE=mode == "mock")
                with self._metrics_lock:
                    self._attempt_count = self._success_count = self._failure_count = 0
                    self._busy_rejections = 0
                    self.last_duration_ms = self.last_error = self.checked_at = None
                    self.check_state = "unchecked"
                if previous is not None:
                    try:
                        previous.close()
                    except Exception as exc:
                        release_error_frames(exc)
                        logger.exception("Previous detector cleanup failed after mode change")
                return True
            finally:
                try:
                    # If construction/persistence fails, keep the old detector
                    # active and release the unused candidate, even on Ctrl+C.
                    if replacement is not None:
                        replacement.close()
                finally:
                    replacement = previous = None

    def close(self) -> None:
        detector = None
        with self._lock:
            if self._closed:
                return
            self._closed = True
            detector, self._detector = self._detector, None
        try:
            if detector is not None:
                detector.close()
        except BaseException as exc:
            release_error_frames(exc)
            raise
        finally:
            detector = None
            gc.collect()


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
