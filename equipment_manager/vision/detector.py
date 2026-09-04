from __future__ import annotations

import gc
import logging
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Protocol

from .camera import FrameSource, build_frame_source
from .types import Detection, DetectionError, PreflightResult


logger = logging.getLogger(__name__)


class Detector(Protocol):
    def detect(self, category_hint: str | None = None) -> Detection: ...

    def close(self) -> None: ...


class MockDetector:
    def __init__(self, frame_count: int = 5):
        self.frame_count = frame_count

    def detect(self, category_hint: str | None = None) -> Detection:
        if not category_hint:
            raise DetectionError("모의 인식용 기자재를 선택해 주세요.")
        return Detection(
            label=category_hint,
            confidence=0.98,
            votes=self.frame_count,
            frame_count=self.frame_count,
        )

    def close(self) -> None:
        return None


class YoloDetector:
    def __init__(self, config: dict, frame_source: FrameSource | None = None):
        self.model_path = Path(config["YOLO_MODEL_PATH"])
        self.image_size = int(config["YOLO_IMAGE_SIZE"])
        self.confidence = float(config["YOLO_CONFIDENCE"])
        self.min_votes = int(config["YOLO_MIN_VOTES"])
        self.frame_count = int(config["YOLO_FRAME_COUNT"])
        self.max_detections = int(config["YOLO_MAX_DETECTIONS"])
        self.inference_threads = int(config["INFERENCE_THREADS"])
        self.aliases = dict(config.get("YOLO_CLASS_ALIASES", {}))
        self.frame_source = frame_source or build_frame_source(config)
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not self.model_path.exists():
            raise DetectionError(f"YOLO 모델을 찾을 수 없습니다: {self.model_path}")

        os.environ.setdefault("OMP_NUM_THREADS", str(self.inference_threads))
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(self.inference_threads))
        os.environ.setdefault("MKL_NUM_THREADS", str(self.inference_threads))
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectionError("ultralytics 패키지가 설치되어 있지 않습니다.") from exc

        try:
            import torch

            torch.set_num_threads(max(1, self.inference_threads))
            torch.set_num_interop_threads(1)
        except (ImportError, RuntimeError):
            logger.debug("Torch thread configuration was not applied", exc_info=True)

        logger.info("Loading YOLO model from %s", self.model_path)
        try:
            self._model = YOLO(str(self.model_path))
        except Exception as exc:
            raise DetectionError(f"YOLO 모델 로딩에 실패했습니다: {exc}") from exc
        return self._model

    def _predict_best(self, frame) -> tuple[str, float] | None:
        model = self._load_model()
        result_stream = None
        result = None
        boxes = None
        try:
            result_stream = model.predict(
                source=frame,
                imgsz=self.image_size,
                conf=self.confidence,
                max_det=self.max_detections,
                verbose=False,
                save=False,
                stream=True,
                device="cpu",
            )
            result = next(iter(result_stream), None)
            if result is None or result.boxes is None or len(result.boxes) == 0:
                return None
            boxes = result.boxes
            best_index = int(boxes.conf.argmax().item())
            class_id = int(boxes.cls[best_index].item())
            score = float(boxes.conf[best_index].item())
            raw_label = str(result.names[class_id])
            return self.aliases.get(raw_label, raw_label), score
        except DetectionError:
            raise
        except Exception as exc:
            raise DetectionError(f"YOLO 추론에 실패했습니다: {exc}") from exc
        finally:
            if result_stream is not None and hasattr(result_stream, "close"):
                try:
                    result_stream.close()
                except Exception:
                    logger.debug("YOLO result stream close failed", exc_info=True)
            del boxes, result, result_stream

    def detect(self, category_hint: str | None = None) -> Detection:
        del category_hint
        votes: Counter[str] = Counter()
        confidences: dict[str, list[float]] = defaultdict(list)

        for frame in self.frame_source.frames(self.frame_count):
            try:
                prediction = self._predict_best(frame)
                if prediction is None:
                    continue
                label, score = prediction
                votes[label] += 1
                confidences[label].append(score)
            finally:
                del frame

        if not votes:
            raise DetectionError("기자재를 인식하지 못했습니다. 위치와 조명을 확인해 주세요.")
        label, vote_count = votes.most_common(1)[0]
        if vote_count < self.min_votes:
            raise DetectionError(
                "인식 결과가 일정하지 않습니다. 기자재를 하나만 놓고 다시 시도해 주세요."
            )
        average_confidence = sum(confidences[label]) / len(confidences[label])
        return Detection(
            label=label,
            confidence=average_confidence,
            votes=vote_count,
            frame_count=self.frame_count,
        )

    def preflight(self) -> PreflightResult:
        from time import perf_counter

        from ..system_metrics import current_rss_mb

        started = perf_counter()
        self._load_model()
        frame_iterator = self.frame_source.frames(1)
        frame = next(frame_iterator)
        try:
            height, width = frame.shape[:2]
            prediction = self._predict_best(frame)
        finally:
            del frame
            if hasattr(frame_iterator, "close"):
                frame_iterator.close()
        gc.collect()
        return PreflightResult(
            model_path=str(self.model_path),
            camera_backend=self.frame_source.backend_name,
            frame_width=width,
            frame_height=height,
            detected_label=prediction[0] if prediction else None,
            confidence=prediction[1] if prediction else None,
            duration_ms=round((perf_counter() - started) * 1000),
            memory_rss_mb=current_rss_mb(),
        )

    def close(self) -> None:
        self.frame_source.close()
        self._model = None
        gc.collect()
        logger.info("YOLO detector released")


def build_detector(config: dict) -> Detector:
    mode = str(config["DETECTOR_MODE"]).lower()
    if mode == "mock":
        return MockDetector(frame_count=int(config["YOLO_FRAME_COUNT"]))
    if mode == "yolo":
        return YoloDetector(config)
    raise DetectionError(f"지원하지 않는 인식 모드입니다: {mode}")
