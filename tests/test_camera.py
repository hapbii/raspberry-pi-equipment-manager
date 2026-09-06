from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from equipment_manager.vision.camera import OpenCvFrameSource


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


if __name__ == "__main__":
    unittest.main()
