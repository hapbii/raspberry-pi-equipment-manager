from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

from equipment_manager.vision.camera import OpenCvFrameSource, Picamera2FrameSource
from equipment_manager.vision.types import DetectionError


class FakeCapture:
    def __init__(self, opened=True):
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened and not self.released

    def set(self, _property, _value):
        return True

    def grab(self):
        return True

    def release(self):
        self.released = True


class OpenCvFrameSourceTestCase(unittest.TestCase):
    def test_configuration_and_warmup_failures_release_camera(self):
        for operation in ("set", "grab"):
            with self.subTest(operation=operation):
                capture = FakeCapture()
                cv2 = types.SimpleNamespace(
                    CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4,
                    CAP_PROP_BUFFERSIZE=38, VideoCapture=lambda _index: capture,
                )
                source = OpenCvFrameSource(index=0, width=640, height=480)
                with patch.dict(sys.modules, {"cv2": cv2}), patch.object(
                    capture, operation, side_effect=RuntimeError("camera disconnected")
                ):
                    with self.assertRaisesRegex(RuntimeError, "camera disconnected"):
                        source._ensure_started()
                self.assertTrue(capture.released)
                self.assertIsNone(source._camera)

    def test_stale_camera_is_released_before_reconnect(self):
        replacement = FakeCapture()
        cv2 = types.ModuleType("cv2")
        cv2.CAP_PROP_FRAME_WIDTH = 3
        cv2.CAP_PROP_FRAME_HEIGHT = 4
        cv2.CAP_PROP_BUFFERSIZE = 38
        cv2.VideoCapture = lambda _index: replacement

        source = OpenCvFrameSource(index=0, width=640, height=480, warmup_frames=0)
        stale = FakeCapture(opened=False)
        source._camera = stale

        with patch.dict(sys.modules, {"cv2": cv2}):
            source._ensure_started()

        self.assertTrue(stale.released)
        self.assertIs(source._camera, replacement)
        source.close()
        self.assertTrue(replacement.released)


class Picamera2FrameSourceTestCase(unittest.TestCase):
    def test_failed_or_interrupted_startup_closes_camera_and_can_retry(self):
        for error in (RuntimeError("camera failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                camera = Mock()
                source = Picamera2FrameSource(640, 480)
                module = types.SimpleNamespace(Picamera2=lambda: camera)
                expected = DetectionError if isinstance(error, Exception) else KeyboardInterrupt
                with patch.dict(sys.modules, {"picamera2": module}), patch(
                    "equipment_manager.vision.camera.time.sleep", side_effect=error
                ):
                    with self.assertRaises(expected):
                        source._ensure_started()
                camera.close.assert_called_once_with()
                self.assertIsNone(source._camera)
                self.assertFalse(source._started)
                with patch.dict(sys.modules, {"picamera2": module}), patch(
                    "equipment_manager.vision.camera.time.sleep"
                ):
                    source._ensure_started()
                self.assertIs(source._camera, camera)
                source.close()


if __name__ == "__main__":
    unittest.main()
