from __future__ import annotations

import logging
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from flask import current_app


logger = logging.getLogger(__name__)


class DetectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    votes: int
    frame_count: int


class MockDetector:
    def detect(self, category_hint: str | None = None) -> Detection:
        if not category_hint:
            raise DetectionError("모의 인식용 기자재를 선택해 주세요.")
        return Detection(label=category_hint, confidence=0.98, votes=5, frame_count=5)


class FrameCamera:
    def __init__(self, backend: str, index: int, width: int, height: int):
        self.backend = backend
        self.index = index
        self.width = width
        self.height = height

    def capture_frames(self, count: int):
        if self.backend == "picamera2":
            yield from self._capture_picamera2(count)
            return
        if self.backend in {"opencv", "usb"}:
            yield from self._capture_opencv(count)
            return
        raise DetectionError(f"지원하지 않는 카메라 방식입니다: {self.backend}")

    def _capture_picamera2(self, count: int):
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise DetectionError(
                "Picamera2가 설치되어 있지 않습니다. Raspberry Pi OS에서 python3-picamera2를 설치해 주세요."
            ) from exc

        camera = Picamera2()
        try:
            config = camera.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            camera.configure(config)
            camera.start()
            for _ in range(count):
                yield camera.capture_array()
        except Exception as exc:
            raise DetectionError(f"카메라 촬영에 실패했습니다: {exc}") from exc
        finally:
            camera.stop()
            camera.close()

    def _capture_opencv(self, count: int):
        try:
            import cv2
        except ImportError as exc:
            raise DetectionError("OpenCV가 설치되어 있지 않습니다.") from exc

        camera = cv2.VideoCapture(self.index)
        try:
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            if not camera.isOpened():
                raise DetectionError("카메라를 열 수 없습니다.")
            warmup = max(2, count)
            for _ in range(warmup):
                camera.read()
            for _ in range(count):
                ok, frame = camera.read()
                if not ok:
                    raise DetectionError("카메라 프레임을 읽지 못했습니다.")
                yield frame
        finally:
            camera.release()


class YoloDetector:
    def __init__(self, config: dict):
        self.model_path = Path(config["YOLO_MODEL_PATH"])
        self.image_size = int(config["YOLO_IMAGE_SIZE"])
        self.confidence = float(config["YOLO_CONFIDENCE"])
        self.min_votes = int(config["YOLO_MIN_VOTES"])
        self.frame_count = int(config["YOLO_FRAME_COUNT"])
        self.aliases = dict(config.get("YOLO_CLASS_ALIASES", {}))
        self.camera = FrameCamera(
            config["CAMERA_BACKEND"],
            int(config["CAMERA_INDEX"]),
            int(config["CAMERA_WIDTH"]),
            int(config["CAMERA_HEIGHT"]),
        )
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not self.model_path.exists():
            raise DetectionError(f"YOLO 모델을 찾을 수 없습니다: {self.model_path}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectionError("ultralytics 패키지가 설치되어 있지 않습니다.") from exc
        logger.info("Loading YOLO model from %s", self.model_path)
        self._model = YOLO(str(self.model_path))
        return self._model

    def detect(self, category_hint: str | None = None) -> Detection:
        del category_hint
        model = self._load_model()
        votes: Counter[str] = Counter()
        confidences: dict[str, list[float]] = defaultdict(list)

        for frame in self.camera.capture_frames(self.frame_count):
            results = model.predict(
                source=frame,
                imgsz=self.image_size,
                conf=self.confidence,
                verbose=False,
                device="cpu",
            )
            result = results[0]
            if result.boxes is None or len(result.boxes) == 0:
                continue
            best_index = int(result.boxes.conf.argmax().item())
            class_id = int(result.boxes.cls[best_index].item())
            score = float(result.boxes.conf[best_index].item())
            raw_label = str(result.names[class_id])
            label = self.aliases.get(raw_label, raw_label)
            votes[label] += 1
            confidences[label].append(score)

        if not votes:
            raise DetectionError("기자재를 인식하지 못했습니다. 위치와 조명을 확인해 주세요.")
        label, vote_count = votes.most_common(1)[0]
        if vote_count < self.min_votes:
            raise DetectionError("인식 결과가 일정하지 않습니다. 기자재를 하나만 놓고 다시 시도해 주세요.")
        average_confidence = sum(confidences[label]) / len(confidences[label])
        return Detection(
            label=label,
            confidence=average_confidence,
            votes=vote_count,
            frame_count=self.frame_count,
        )


class DetectionCoordinator:
    def __init__(self, detector):
        self.detector = detector
        self._lock = threading.Lock()

    def detect(self, category_hint: str | None = None) -> Detection:
        if not self._lock.acquire(blocking=False):
            raise DetectionError("현재 다른 인식 작업을 처리 중입니다. 잠시 후 다시 시도해 주세요.")
        try:
            return self.detector.detect(category_hint)
        finally:
            self._lock.release()


def get_detector() -> DetectionCoordinator:
    coordinator = current_app.extensions.get("detector")
    if coordinator is None:
        mode = current_app.config["DETECTOR_MODE"]
        if mode == "mock":
            detector = MockDetector()
        elif mode == "yolo":
            detector = YoloDetector(current_app.config)
        else:
            raise DetectionError(f"지원하지 않는 인식 모드입니다: {mode}")
        coordinator = DetectionCoordinator(detector)
        current_app.extensions["detector"] = coordinator
    return coordinator
