from __future__ import annotations

import gc
import logging
import os
from collections import Counter, defaultdict
from collections.abc import Iterator
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
        self.image_size = max(160, min(int(config["YOLO_IMAGE_SIZE"]), 1280))
        self.confidence = max(0.01, min(float(config["YOLO_CONFIDENCE"]), 1.0))
        self.frame_count = max(1, min(int(config["YOLO_FRAME_COUNT"]), 30))
        self.min_votes = max(1, min(int(config["YOLO_MIN_VOTES"]), self.frame_count))
        self.max_detections = max(1, min(int(config["YOLO_MAX_DETECTIONS"]), 100))
        self.inference_threads = max(1, min(int(config["INFERENCE_THREADS"]), 4))
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
            self._clear_predictor_frame_references(model)
            del boxes, result, result_stream

    @staticmethod
    def _clear_predictor_frame_references(model) -> None:
        """Ultralytics predictor에 남는 마지막 프레임 참조를 해제합니다."""
        predictor = getattr(model, "predictor", None)
        if predictor is None:
            return
        for attribute in ("batch", "dataset", "results", "plotted_img"):
            if hasattr(predictor, attribute):
                try:
                    setattr(predictor, attribute, None)
                except Exception:
                    logger.debug(
                        "YOLO predictor attribute release failed: %s",
                        attribute,
                        exc_info=True,
                    )

    def detect(self, category_hint: str | None = None) -> Detection:
        del category_hint
        votes: Counter[str] = Counter()
        confidence_sums: dict[str, float] = defaultdict(float)
        processed_frames = 0
        frame_iterator: Iterator[object] | None = self.frame_source.frames(self.frame_count)

        try:
            for frame in frame_iterator:
                processed_frames += 1
                try:
                    prediction = self._predict_best(frame)
                    if prediction is not None:
                        label, score = prediction
                        votes[label] += 1
                        confidence_sums[label] += score
                finally:
                    del frame

                if self._winner_is_decided(votes, processed_frames):
                    break
        finally:
            if frame_iterator is not None and hasattr(frame_iterator, "close"):
                try:
                    frame_iterator.close()
                except Exception:
                    logger.debug("Camera frame iterator close failed", exc_info=True)
            frame_iterator = None

        if not votes:
            raise DetectionError("기자재를 인식하지 못했습니다. 위치와 조명을 확인해 주세요.")
        ordered_votes = votes.most_common(2)
        label, vote_count = ordered_votes[0]
        if len(ordered_votes) > 1 and ordered_votes[1][1] == vote_count:
            raise DetectionError(
                "서로 다른 기자재가 같은 횟수로 인식되었습니다. 하나만 놓고 다시 시도해 주세요."
            )
        if vote_count < self.min_votes:
            raise DetectionError(
                "인식 결과가 일정하지 않습니다. 기자재를 하나만 놓고 다시 시도해 주세요."
            )
        average_confidence = confidence_sums[label] / vote_count
        return Detection(
            label=label,
            confidence=average_confidence,
            votes=vote_count,
            frame_count=processed_frames,
        )

    def _winner_is_decided(self, votes: Counter[str], processed_frames: int) -> bool:
        if not votes:
            return False
        ordered = votes.most_common(2)
        leading_votes = ordered[0][1]
        second_votes = ordered[1][1] if len(ordered) > 1 else 0
        remaining_frames = self.frame_count - processed_frames
        return (
            leading_votes >= self.min_votes
            and leading_votes > second_votes + remaining_frames
        )

    def preflight(self) -> PreflightResult:
        from time import perf_counter

        from ..system_metrics import current_rss_mb

        started = perf_counter()
        self._load_model()
        frame_iterator: Iterator[object] | None = self.frame_source.frames(1)
        frame = None
        try:
            frame = next(frame_iterator)
            height, width = frame.shape[:2]
            prediction = self._predict_best(frame)
        finally:
            if hasattr(frame_iterator, "close"):
                try:
                    frame_iterator.close()
                except Exception:
                    logger.debug("Preflight frame iterator close failed", exc_info=True)
            frame = None
            frame_iterator = None
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
        model, self._model = self._model, None
        try:
            self.frame_source.close()
        finally:
            if model is not None:
                self._clear_predictor_frame_references(model)
                try:
                    model.predictor = None
                except Exception:
                    logger.debug("YOLO predictor release failed", exc_info=True)
            model = None
            gc.collect()
            logger.info("YOLO detector released")


def build_detector(config: dict) -> Detector:
    mode = str(config["DETECTOR_MODE"]).lower()
    if mode == "mock":
        return MockDetector(frame_count=int(config["YOLO_FRAME_COUNT"]))
    if mode == "yolo":
        return YoloDetector(config)
    raise DetectionError(f"지원하지 않는 인식 모드입니다: {mode}")
