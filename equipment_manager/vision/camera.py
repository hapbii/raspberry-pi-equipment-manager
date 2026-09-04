from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from typing import Protocol

from .types import DetectionError


logger = logging.getLogger(__name__)


class FrameSource(Protocol):
    backend_name: str

    def frames(self, count: int) -> Iterator[object]: ...

    def close(self) -> None: ...


class Picamera2FrameSource:
    backend_name = "picamera2"

    def __init__(
        self,
        width: int,
        height: int,
        buffer_count: int = 2,
        warmup_seconds: float = 0.5,
    ):
        self.width = width
        self.height = height
        self.buffer_count = max(1, min(buffer_count, 4))
        self.warmup_seconds = max(0.0, warmup_seconds)
        self._camera = None
        self._started = False
        self._lock = threading.RLock()

    def _ensure_started(self) -> None:
        if self._started and self._camera is not None:
            return
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise DetectionError(
                "Picamera2가 설치되어 있지 않습니다. Raspberry Pi OS에서 "
                "sudo apt install python3-picamera2를 실행해 주세요."
            ) from exc

        camera = Picamera2()
        try:
            config = camera.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"},
                buffer_count=self.buffer_count,
                queue=False,
            )
            camera.configure(config)
            camera.start()
            if self.warmup_seconds:
                time.sleep(self.warmup_seconds)
        except Exception as exc:
            try:
                camera.close()
            except Exception:
                logger.debug("Camera close after startup failure also failed", exc_info=True)
            raise DetectionError(f"Picamera2 시작에 실패했습니다: {exc}") from exc

        self._camera = camera
        self._started = True
        logger.info(
            "Picamera2 started: %sx%s, buffers=%s, queue=false",
            self.width,
            self.height,
            self.buffer_count,
        )

    def frames(self, count: int) -> Iterator[object]:
        with self._lock:
            self._ensure_started()
            try:
                for _ in range(max(1, count)):
                    yield self._camera.capture_array("main")
            except Exception as exc:
                self.close()
                raise DetectionError(f"Picamera2 프레임 촬영에 실패했습니다: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            camera, self._camera = self._camera, None
            started, self._started = self._started, False
            if camera is None:
                return
            if started:
                try:
                    camera.stop()
                except Exception:
                    logger.debug("Picamera2 stop failed", exc_info=True)
            try:
                camera.close()
            except Exception:
                logger.debug("Picamera2 close failed", exc_info=True)
            logger.info("Picamera2 closed")


class OpenCvFrameSource:
    backend_name = "opencv"

    def __init__(
        self,
        index: int,
        width: int,
        height: int,
        warmup_frames: int = 3,
    ):
        self.index = index
        self.width = width
        self.height = height
        self.warmup_frames = max(0, warmup_frames)
        self._camera = None
        self._lock = threading.RLock()

    def _ensure_started(self) -> None:
        if self._camera is not None and self._camera.isOpened():
            return
        stale_camera, self._camera = self._camera, None
        if stale_camera is not None:
            try:
                stale_camera.release()
            except Exception:
                logger.debug("Stale OpenCV camera release failed", exc_info=True)
        try:
            import cv2
        except ImportError as exc:
            raise DetectionError("OpenCV가 설치되어 있지 않습니다.") from exc

        camera = cv2.VideoCapture(self.index)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not camera.isOpened():
            camera.release()
            raise DetectionError(f"USB 카메라 {self.index}번을 열 수 없습니다.")
        self._camera = camera
        for _ in range(self.warmup_frames):
            camera.grab()
        logger.info("OpenCV camera started: index=%s, %sx%s", self.index, self.width, self.height)

    def frames(self, count: int) -> Iterator[object]:
        with self._lock:
            self._ensure_started()
            try:
                for _ in range(max(1, count)):
                    ok, frame = self._camera.read()
                    if not ok:
                        raise DetectionError("USB 카메라 프레임을 읽지 못했습니다.")
                    yield frame
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        with self._lock:
            camera, self._camera = self._camera, None
            if camera is not None:
                camera.release()
                logger.info("OpenCV camera closed")


def build_frame_source(config: dict) -> FrameSource:
    backend = str(config["CAMERA_BACKEND"]).lower()
    width = max(160, min(int(config["CAMERA_WIDTH"]), 1920))
    height = max(120, min(int(config["CAMERA_HEIGHT"]), 1080))
    if backend == "picamera2":
        return Picamera2FrameSource(
            width=width,
            height=height,
            buffer_count=int(config["CAMERA_BUFFER_COUNT"]),
            warmup_seconds=float(config["CAMERA_WARMUP_SECONDS"]),
        )
    if backend in {"opencv", "usb"}:
        return OpenCvFrameSource(
            index=int(config["CAMERA_INDEX"]),
            width=width,
            height=height,
        )
    raise DetectionError(f"지원하지 않는 카메라 방식입니다: {backend}")
