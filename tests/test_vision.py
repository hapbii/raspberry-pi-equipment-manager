from __future__ import annotations

import unittest
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

from equipment_manager.vision.detector import YoloDetector
from equipment_manager.vision.service import DetectionService
from equipment_manager.vision.types import Detection, DetectionError


class FakeDetector:
    def __init__(self):
        self.closed = False
        self.calls = 0

    def detect(self, category_hint=None):
        self.calls += 1
        return Detection(
            label=category_hint or "멀티미터",
            confidence=0.91,
            votes=3,
            frame_count=5,
        )

    def close(self):
        self.closed = True


class FailingDetector(FakeDetector):
    def detect(self, category_hint=None):
        self.calls += 1
        raise DetectionError("x" * 700)


class BlockingDetector(FakeDetector):
    def __init__(self):
        super().__init__()
        self.started = Event()
        self.release = Event()

    def detect(self, category_hint=None):
        self.started.set()
        self.release.wait(timeout=2)
        return super().detect(category_hint)


class FakeScalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class FakeVector:
    def __init__(self, values):
        self.values = values

    def argmax(self):
        best = max(range(len(self.values)), key=self.values.__getitem__)
        return FakeScalar(best)

    def __getitem__(self, index):
        return FakeScalar(self.values[index])


class FakeBoxes:
    def __init__(self):
        self.conf = FakeVector([0.72, 0.91])
        self.cls = FakeVector([1, 0])

    def __len__(self):
        return 2


class FakeResult:
    boxes = FakeBoxes()
    names = {0: "multimeter", 1: "arduino"}


class FakeResultStream:
    def __init__(self, result=None):
        self.closed = False
        self._result = result or FakeResult()

    def __iter__(self):
        return self

    def __next__(self):
        if self._result is None:
            raise StopIteration
        result, self._result = self._result, None
        return result

    def close(self):
        self.closed = True


class FakeModel:
    def __init__(self):
        self.calls = []
        self.streams = []
        self.predictor = SimpleNamespace(
            batch=None,
            dataset=None,
            results=None,
            plotted_img=None,
        )

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        self.predictor.batch = object()
        self.predictor.dataset = object()
        self.predictor.results = object()
        self.predictor.plotted_img = object()
        stream = FakeResultStream()
        self.streams.append(stream)
        return stream


class SequenceResult:
    names = {0: "multimeter", 1: "arduino"}

    def __init__(self, class_id):
        self.boxes = SingleBox(class_id)


class SingleBox:
    def __init__(self, class_id):
        self.conf = FakeVector([0.9])
        self.cls = FakeVector([class_id])

    def __len__(self):
        return 1


class SequenceModel(FakeModel):
    def __init__(self, class_ids):
        super().__init__()
        self.class_ids = iter(class_ids)

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        stream = FakeResultStream(SequenceResult(next(self.class_ids)))
        self.streams.append(stream)
        return stream


class FakeFrame:
    shape = (480, 640, 3)


class FakeFrameSource:
    backend_name = "fake-camera"

    def __init__(self):
        self.closed = False
        self.requests = []
        self.iterators = []

    def frames(self, count):
        self.requests.append(count)
        iterator = FakeFrameIterator(count)
        self.iterators.append(iterator)
        return iterator

    def close(self):
        self.closed = True


class FakeFrameIterator:
    def __init__(self, count):
        self.remaining = count
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            raise StopIteration
        self.remaining -= 1
        return FakeFrame()

    def close(self):
        self.closed = True


class DetectionServiceTestCase(unittest.TestCase):
    def test_service_reuses_one_detector_and_releases_it(self):
        detector = FakeDetector()
        service = DetectionService(detector, gc_interval_scans=3)
        for _ in range(10):
            result = service.detect("멀티미터")
            self.assertEqual(result.label, "멀티미터")
            self.assertIsNotNone(result.duration_ms)
        self.assertEqual(detector.calls, 10)
        self.assertEqual(service.status()["scan_count"], 10)
        service.close()
        self.assertTrue(detector.closed)
        with self.assertRaises(DetectionError):
            service.detect()

    def test_close_is_idempotent(self):
        detector = FakeDetector()
        service = DetectionService(detector)
        service.close()
        service.close()
        self.assertTrue(detector.closed)

    def test_failures_are_counted_cleaned_and_error_is_bounded(self):
        detector = FailingDetector()
        service = DetectionService(detector, gc_interval_scans=2)
        with patch("equipment_manager.vision.service.gc.collect") as collect:
            for _ in range(2):
                with self.assertRaises(DetectionError):
                    service.detect()
            collect.assert_called_once()
        status = service.status()
        self.assertEqual(status["attempt_count"], 2)
        self.assertEqual(status["failure_count"], 2)
        self.assertEqual(status["scan_count"], 0)
        self.assertEqual(len(status["last_error"]), 500)
        service.close()

    def test_concurrent_inference_is_rejected_without_extra_detector_call(self):
        detector = BlockingDetector()
        service = DetectionService(detector)
        worker = Thread(target=service.detect, args=("멀티미터",))
        worker.start()
        self.assertTrue(detector.started.wait(timeout=1))
        with self.assertRaises(DetectionError):
            service.detect("아두이노")
        detector.release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(detector.calls, 1)
        self.assertEqual(service.status()["busy_rejections"], 1)
        service.close()


class YoloDetectorTestCase(unittest.TestCase):
    def test_streaming_inference_reuses_model_and_camera(self):
        source = FakeFrameSource()
        model = FakeModel()
        detector = YoloDetector(
            {
                "YOLO_MODEL_PATH": "models/test.pt",
                "YOLO_IMAGE_SIZE": 320,
                "YOLO_CONFIDENCE": 0.6,
                "YOLO_MIN_VOTES": 3,
                "YOLO_FRAME_COUNT": 5,
                "YOLO_MAX_DETECTIONS": 5,
                "INFERENCE_THREADS": 2,
                "YOLO_CLASS_ALIASES": {"multimeter": "멀티미터"},
            },
            frame_source=source,
        )
        detector._model = model

        first = detector.detect()
        second = detector.detect()

        self.assertEqual(first.label, "멀티미터")
        self.assertEqual(first.votes, 3)
        self.assertEqual(first.frame_count, 3)
        self.assertEqual(second.label, "멀티미터")
        self.assertEqual(source.requests, [5, 5])
        self.assertEqual(len(model.calls), 6)
        self.assertTrue(all(call["stream"] for call in model.calls))
        self.assertTrue(all(call["save"] is False for call in model.calls))
        self.assertTrue(all(stream.closed for stream in model.streams))
        self.assertTrue(all(iterator.closed for iterator in source.iterators))
        self.assertIsNone(model.predictor.batch)
        self.assertIsNone(model.predictor.dataset)
        self.assertIsNone(model.predictor.results)
        self.assertIsNone(model.predictor.plotted_img)

        detector.close()
        self.assertTrue(source.closed)

    def test_tied_vote_is_rejected(self):
        source = FakeFrameSource()
        detector = YoloDetector(
            {
                "YOLO_MODEL_PATH": "models/test.pt",
                "YOLO_IMAGE_SIZE": 320,
                "YOLO_CONFIDENCE": 0.6,
                "YOLO_MIN_VOTES": 2,
                "YOLO_FRAME_COUNT": 4,
                "YOLO_MAX_DETECTIONS": 5,
                "INFERENCE_THREADS": 2,
                "YOLO_CLASS_ALIASES": {},
            },
            frame_source=source,
        )
        model = SequenceModel([0, 1, 0, 1])
        detector._model = model

        with self.assertRaisesRegex(DetectionError, "같은 횟수"):
            detector.detect()

        self.assertTrue(all(stream.closed for stream in model.streams))
        self.assertTrue(source.iterators[0].closed)
        detector.close()


if __name__ == "__main__":
    unittest.main()
