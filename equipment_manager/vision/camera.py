from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import Protocol

from .types import CameraError


logger = logging.getLogger(__name__)


class FrameSource(Protocol):
    """Frames use BGR channel order, ready for OpenCV/Ultralytics."""
    backend_name: str

    def frames(self, count: int) -> Iterator[object]: ...

    def close(self) -> None: ...


@contextmanager
def fresh_frame(source: FrameSource):
    """Borrow one current frame; discard queued USB images and close the iterator.

    The caller must drop its own frame reference before leaving the context if
    it retains exception tracebacks. This helper clears its references as well.
    """
    frame = frames = None
    try:
        count = 4 if source.backend_name == "opencv" else 1
        with closing(source.frames(count)) as frames:
            index = 0
            for frame in frames:
                index += 1
                if index == count:
                    try:
                        yield frame
                    finally:
                        frame = None
                    return
                frame = None
            raise CameraError("카메라에서 촬영 프레임을 받지 못했습니다.")
    finally:
        frame = frames = None


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
            raise CameraError(
                "Picamera2가 설치되어 있지 않습니다. Raspberry Pi OS에서 "
                "sudo apt install python3-picamera2를 실행해 주세요."
            ) from exc

        camera = Picamera2()
        try:
            config = camera.create_preview_configuration(
                # Picamera2's RGB888 byte layout is BGR (not RGB).
                main={"size": (self.width, self.height), "format": "RGB888"},
                buffer_count=self.buffer_count,
                queue=False,
            )
            camera.configure(config)
            camera.start()
            if self.warmup_seconds:
                time.sleep(self.warmup_seconds)
        except BaseException as exc:
            try:
                camera.close()
            except Exception:
                logger.debug("Camera close after startup failure also failed", exc_info=True)
            if not isinstance(exc, Exception):
                raise
            raise CameraError(f"Picamera2 시작에 실패했습니다: {exc}") from exc

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
            try:
                self._ensure_started()
                for _ in range(max(1, count)):
                    frame = None
                    try:
                        try:
                            # A disconnected sensor can otherwise block a web
                            # worker and prevent camera shutdown indefinitely.
                            frame = self._camera.capture_array("main", wait=5.0)
                        except BaseException as exc:
                            # Timed-out Picamera2 jobs remain queued. Cancel them
                            # before stop() so the stop job cannot get stuck behind
                            # a capture that will never receive a frame.
                            try:
                                self._camera.cancel_all_and_flush()
                            except Exception:
                                logger.debug("Camera job cancellation failed", exc_info=True)
                            if isinstance(exc, TimeoutError):
                                raise CameraError(
                                    "카메라가 5초 동안 영상을 보내지 않았습니다. "
                                    "촬영을 종료하고 전원을 끈 뒤 카메라 케이블 연결을 확인하세요."
                                ) from exc
                            raise
                        yield frame
                    finally:
                        frame = None
            except Exception as exc:
                self.close()
                raise CameraError(f"Picamera2 프레임 촬영에 실패했습니다: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            camera, self._camera = self._camera, None
            started, self._started = self._started, False
            if camera is None:
                return
            try:
                if started:
                    try:
                        camera.stop()
                    except Exception:
                        logger.debug("Picamera2 stop failed", exc_info=True)
            finally:
                # stop() can be interrupted too; never skip closing the handle.
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
            raise CameraError("OpenCV가 설치되어 있지 않습니다.") from exc

        camera = cv2.VideoCapture(self.index)
        try:
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not camera.isOpened():
                raise CameraError(f"USB 카메라 {self.index}번을 열 수 없습니다.")
            for _ in range(self.warmup_frames):
                camera.grab()
        except BaseException:
            try:
                camera.release()
            except Exception:
                logger.debug("OpenCV startup cleanup failed", exc_info=True)
            raise
        self._camera = camera
        logger.info("OpenCV camera started: index=%s, %sx%s", self.index, self.width, self.height)

    def frames(self, count: int) -> Iterator[object]:
        with self._lock:
            try:
                self._ensure_started()
                for _ in range(max(1, count)):
                    ok, frame = self._camera.read()
                    try:
                        if not ok:
                            raise CameraError("USB 카메라 프레임을 읽지 못했습니다.")
                        yield frame
                    finally:
                        # Do not keep the old image while allocating the next.
                        frame = None
            except Exception as exc:
                self.close()
                raise CameraError(f"USB 카메라 촬영에 실패했습니다: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            camera, self._camera = self._camera, None
            if camera is not None:
                try:
                    camera.release()
                except Exception:
                    logger.debug("OpenCV camera release failed", exc_info=True)
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
    raise CameraError(f"지원하지 않는 카메라 방식입니다: {backend}")
