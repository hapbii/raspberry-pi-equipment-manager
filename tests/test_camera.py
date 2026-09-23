from __future__ import annotations

import sys
import types
import unittest
import weakref
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
    def test_previous_frame_is_released_before_next_camera_read(self):
        class Frame:
            pass

        references = []

        def read():
            if references:
                self.assertIsNone(references[-1](), "previous frame is still retained")
            frame = Frame()
            references.append(weakref.ref(frame))
            return True, frame

        capture = FakeCapture()
        capture.read = read
        source = OpenCvFrameSource(0, 640, 480)
        source._camera = capture
        iterator = source.frames(100)
        try:
            for _ in range(100):
                frame = next(iterator)
                del frame
        finally:
            iterator.close()
            source.close()
        self.assertTrue(all(reference() is None for reference in references))

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
    def test_capture_timeout_cancels_pending_job_before_stop_and_close(self):
        camera = Mock()
        camera.capture_array.side_effect = TimeoutError()
        source = Picamera2FrameSource(640, 480)
        source._camera, source._started = camera, True
        with self.assertRaisesRegex(DetectionError, "5초"):
            next(source.frames(1))
        camera.capture_array.assert_called_once_with("main", wait=5.0)
        self.assertEqual([call[0] for call in camera.mock_calls],
                         ["capture_array", "cancel_all_and_flush", "stop", "close"])
        self.assertIsNone(source._camera)

    def test_capture_interrupt_cancels_pending_job_before_caller_closes(self):
        camera = Mock()
        camera.capture_array.side_effect = KeyboardInterrupt()
        source = Picamera2FrameSource(640, 480)
        source._camera, source._started = camera, True
        try:
            with self.assertRaises(KeyboardInterrupt):
                next(source.frames(1))
        finally:
            source.close()
        self.assertEqual([call[0] for call in camera.mock_calls],
                         ["capture_array", "cancel_all_and_flush", "stop", "close"])

    def test_interrupted_stop_still_closes_camera(self):
        camera = Mock()
        camera.stop.side_effect = KeyboardInterrupt
        source = Picamera2FrameSource(640, 480)
        source._camera, source._started = camera, True
        with self.assertRaises(KeyboardInterrupt):
            source.close()
        camera.close.assert_called_once_with()
        self.assertIsNone(source._camera)
        self.assertFalse(source._started)

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
