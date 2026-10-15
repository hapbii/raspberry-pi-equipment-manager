"""Retain failures deliberately and check that disposed buffers are released."""
from __future__ import annotations

import gc
import logging
import sys
import tempfile
import unittest
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import current_app

from equipment_manager import create_app
from equipment_manager.hardware import GpioIndicator
from equipment_manager.vision.detector import YoloDetector
from equipment_manager.vision.service import DetectionService
from equipment_manager.vision.types import Detection


class Buffer:
    def __init__(self):
        self.pixels = bytearray(640 * 480 * 3)


def make_detector(model):
    detector = YoloDetector({
        "YOLO_MODEL_PATH": "unused.pt", "YOLO_IMAGE_SIZE": 320,
        "YOLO_CONFIDENCE": 0.6, "YOLO_MIN_VOTES": 1,
        "YOLO_FRAME_COUNT": 1, "YOLO_MAX_DETECTIONS": 5,
        "INFERENCE_THREADS": 2,
    }, frame_source=SimpleNamespace(close=lambda: None))
    detector._model = model
    return detector


class FailureResourcesTest(unittest.TestCase):
    def test_predictor_interrupt_still_releases_remaining_frame_references(self):
        class Predictor:
            def __setattr__(self, name, value):
                super().__setattr__(name, value)
                if name == "batch" and value is None:
                    raise KeyboardInterrupt("predictor cleanup interrupted")

        class Model:
            def __init__(self):
                self.predictor = Predictor()

            def predict(self, **kwargs):
                return iter(())

        model = Model()
        detector = make_detector(model)
        references, errors = [], []
        for _ in range(100):
            for name in ("batch", "dataset", "results", "plotted_img"):
                frame = Buffer()
                references.append(weakref.ref(frame))
                setattr(model.predictor, name, frame)
            frame = None
            try:
                detector._predict_best(Buffer())
            except KeyboardInterrupt as error:
                errors.append(error)
            gc.collect()
            self.assertTrue(all(reference() is None for reference in references))
        self.assertEqual(len(errors), 100)
        try:
            detector.close()
        except KeyboardInterrupt:
            pass

    def test_shutdown_detaches_predictor_even_when_frame_cleanup_is_interrupted(self):
        class Predictor(Buffer):
            def __init__(self):
                super().__init__()
                self.batch = Buffer()

            def __setattr__(self, name, value):
                if name == "batch" and value is None:
                    raise KeyboardInterrupt("batch release interrupted")
                super().__setattr__(name, value)

        class Model:
            def __init__(self):
                self.predictor = Predictor()

        references, errors = [], []
        for _ in range(100):
            model = Model()
            references.append(weakref.ref(model.predictor))
            detector = make_detector(model)
            try:
                detector.close()
            except KeyboardInterrupt as error:
                errors.append(error)
            self.assertIsNone(model.predictor)
        gc.collect()
        self.assertEqual(len(errors), 100)
        self.assertTrue(all(reference() is None for reference in references))

    def test_retained_metadata_failures_release_disposed_detectors(self):
        class Detector(Buffer):
            def detect(self, category_hint=None):
                return Detection(label="meter", confidence=0.9, votes=1, frame_count=1)

            def close(self):
                pass

        def failed_metrics():
            raise RuntimeError("metrics unavailable")

        references, errors = [], []
        with patch("equipment_manager.vision.service.current_rss_mb", failed_metrics):
            for _ in range(100):
                service = DetectionService(Detector())
                references.append(weakref.ref(service._detector))
                try:
                    service.detect()
                except RuntimeError as error:
                    errors.append(error)
                self.assertFalse(service._lock.locked())
                service.close()
        gc.collect()
        self.assertEqual(len(errors), 100)
        self.assertTrue(all(reference() is None for reference in references))

    def test_retained_gpio_startup_failures_release_closed_devices(self):
        for failure in ("allocation", "worker"):
            with self.subTest(failure=failure):
                references, errors, closed = [], [], []

                class Device(Buffer):
                    def __init__(self, pin):
                        super().__init__()
                        self.pin = pin
                        references.append(weakref.ref(self))

                    def off(self):
                        pass

                    def close(self):
                        closed.append(self.pin)

                def led(pin):
                    if failure == "allocation" and pin == 2:
                        raise RuntimeError("second LED failed")
                    return Device(pin)

                def failed_start(thread):
                    raise RuntimeError("no worker available")

                module = SimpleNamespace(LED=led, Buzzer=Device)
                with patch.dict(sys.modules, {"gpiozero": module}), patch(
                    "equipment_manager.hardware.threading.Thread.start", failed_start
                ):
                    for _ in range(20):
                        try:
                            GpioIndicator(1, 2, 3)
                        except RuntimeError as error:
                            errors.append(error)
                gc.collect()
                self.assertEqual(len(errors), 20)
                self.assertEqual(closed, ([1] if failure == "allocation" else [1, 2, 3]) * 20)
                self.assertTrue(all(reference() is None for reference in references))

    def test_retained_app_startup_failures_release_apps_and_closed_services(self):
        references, errors, closed = [], [], []
        logger = logging.getLogger("equipment_manager")
        original_handlers = list(logger.handlers)

        class Service(Buffer):
            def close(self):
                closed.append(True)

        def service_factory(config):
            service = Service()
            references.append(weakref.ref(service))
            return service

        def failed_database():
            app = current_app._get_current_object()
            references.append(weakref.ref(app))
            raise RuntimeError("database unavailable")

        with tempfile.TemporaryDirectory() as directory, patch(
            "equipment_manager.build_detection_service", service_factory
        ), patch("equipment_manager.init_app_database", failed_database):
            config = {
                "TESTING": True, "HEARTBEAT_ENABLED": False, "DETECTOR_MODE": "mock",
                "DATABASE": str(Path(directory) / "test.db"),
                "ERROR_LOG_PATH": str(Path(directory) / "errors.log"),
            }
            for _ in range(20):
                try:
                    create_app(config)
                except RuntimeError as error:
                    errors.append(error)
        gc.collect()
        self.assertEqual(len(errors), 20)
        self.assertEqual(len(closed), 20)
        self.assertEqual(logger.handlers, original_handlers)
        self.assertTrue(all(reference() is None for reference in references))


if __name__ == "__main__":
    unittest.main()
