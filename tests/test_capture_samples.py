from __future__ import annotations

import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

from scripts.capture_samples import capture_samples


class Frame:
    def __init__(self):
        self.pixels = bytearray(640 * 480 * 3)


class FrameIterator:
    def __init__(self, count, references, events):
        self.remaining = count
        self.references = references
        self.events = events
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            raise StopIteration
        if any(reference() is not None for reference in self.references):
            raise AssertionError("An old image is still retained before the next capture")
        self.remaining -= 1
        frame = Frame()
        self.references.append(weakref.ref(frame))
        return frame

    def close(self):
        self.closed = True
        self.events.append("iterator-close")


class FrameSource:
    backend_name = "picamera2"

    def __init__(self):
        self.references = []
        self.events = []
        self.iterator = None

    def frames(self, count):
        self.iterator = FrameIterator(count, self.references, self.events)
        return self.iterator

    def close(self):
        self.events.append("camera-close")


class FakeCv:
    COLOR_RGB2BGR = 1
    IMWRITE_JPEG_QUALITY = 1

    def __init__(self):
        self.saved = 0
        self.converted = []
        self.succeed = True

    def cvtColor(self, frame, code):
        converted = Frame()
        self.converted.append(weakref.ref(converted))
        return converted

    def imwrite(self, path, frame, options):
        self.saved += 1
        return self.succeed


class CaptureSamplesTestCase(unittest.TestCase):
    def setUp(self):
        self.source = FrameSource()
        self.cv2 = FakeCv()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        for target in ("scripts.capture_samples.time.sleep", "builtins.print"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def capture(self, count=3):
        return capture_samples(self.source, self.cv2, self.output, "meter", count, 0)

    def test_repeated_captures_release_images_before_next_frame(self):
        self.assertEqual(self.capture(100), 0)
        self.assertEqual(self.cv2.saved, 100)
        self.assertEqual(self.source.events, ["iterator-close", "camera-close"])
        self.assertTrue(all(ref() is None for ref in self.source.references + self.cv2.converted))

    def test_save_failure_closes_iterator_and_camera(self):
        self.cv2.succeed = False
        self.assertEqual(self.capture(), 1)
        self.assertEqual(self.source.events, ["iterator-close", "camera-close"])
        self.assertTrue(all(ref() is None for ref in self.source.references + self.cv2.converted))

    def test_usb_frames_do_not_create_a_conversion_copy(self):
        self.source.backend_name = "opencv"
        self.assertEqual(self.capture(), 0)
        self.assertEqual(self.cv2.converted, [])
        self.assertTrue(all(ref() is None for ref in self.source.references))

    def test_startup_interrupt_closes_camera_and_returns_cancelled_status(self):
        with patch("scripts.capture_samples.time.sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(self.capture(), 130)
        self.assertEqual(self.source.events, ["camera-close"])

    def test_interrupt_between_images_closes_iterator_before_camera(self):
        with patch("scripts.capture_samples.time.sleep", side_effect=[None, KeyboardInterrupt]):
            self.assertEqual(self.capture(), 130)
        self.assertEqual(self.cv2.saved, 1)
        self.assertEqual(self.source.events, ["iterator-close", "camera-close"])

    def test_startup_output_error_closes_camera(self):
        with patch("builtins.print", side_effect=BrokenPipeError):
            with self.assertRaises(BrokenPipeError):
                self.capture()
        self.assertEqual(self.source.events, ["camera-close"])

    def test_retained_output_exception_does_not_retain_images(self):
        error = None
        with patch("builtins.print", side_effect=[None, None, BrokenPipeError]):
            try:
                self.capture()
            except BrokenPipeError as exc:
                error = exc
        self.assertIsNotNone(error)
        self.assertEqual(self.source.events, ["iterator-close", "camera-close"])
        self.assertTrue(all(ref() is None for ref in self.source.references + self.cv2.converted))

    def test_iterator_close_failure_still_closes_camera(self):
        with patch.object(FrameIterator, "close", side_effect=RuntimeError("close failed")):
            with self.assertRaisesRegex(RuntimeError, "close failed"):
                self.capture(1)
        self.assertEqual(self.source.events, ["camera-close"])


if __name__ == "__main__":
    unittest.main()
