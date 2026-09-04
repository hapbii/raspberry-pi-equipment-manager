from __future__ import annotations

import unittest

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
    def __init__(self):
        self.closed = False
        self._result = FakeResult()

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

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        stream = FakeResultStream()
        self.streams.append(stream)
        return stream


class FakeFrame:
    shape = (480, 640, 3)


class FakeFrameSource:
    backend_name = "fake-camera"

    def __init__(self):
        self.closed = False
        self.requests = []

    def frames(self, count):
        self.requests.append(count)
        for _ in range(count):
            yield FakeFrame()

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
        self.assertEqual(first.votes, 5)
        self.assertEqual(second.label, "멀티미터")
        self.assertEqual(source.requests, [5, 5])
        self.assertEqual(len(model.calls), 10)
        self.assertTrue(all(call["stream"] for call in model.calls))
        self.assertTrue(all(call["save"] is False for call in model.calls))
        self.assertTrue(all(stream.closed for stream in model.streams))

        detector.close()
        self.assertTrue(source.closed)


if __name__ == "__main__":
    unittest.main()
