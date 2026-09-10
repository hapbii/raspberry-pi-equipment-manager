from __future__ import annotations

import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from equipment_manager.vision import DetectionError
from scripts import memory_soak_test, pi_diagnostics


class DiagnosticsTestCase(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.detect.return_value = SimpleNamespace(label="meter", confidence=0.9)
        self.service.preflight.return_value = SimpleNamespace(
            frame_width=640, frame_height=480, detected_label="meter",
            confidence=0.9, duration_ms=100, memory_rss_mb=50,
        )
        self.shutdown = Mock()
        self.app = SimpleNamespace(
            config={
                "DETECTOR_MODE": "yolo", "CAMERA_BACKEND": "fake",
                "CAMERA_WIDTH": 640, "CAMERA_HEIGHT": 480,
                "YOLO_MODEL_PATH": "unused.pt", "YOLO_IMAGE_SIZE": 320,
            },
            extensions={"shutdown_services": self.shutdown, "detection_service": self.service},
            app_context=nullcontext,
        )
        self.args = SimpleNamespace(scans=12, interval=0, max_growth_mb=120)
        for target, kwargs in (
            ("builtins.print", {}),
            ("scripts.memory_soak_test.current_rss_mb", {"return_value": 50}),
            ("scripts.memory_soak_test.gc.collect", {}),
            ("scripts.memory_soak_test.time.sleep", {}),
            ("scripts.pi_diagnostics.linux_memory", {"return_value": (None, None)}),
            ("scripts.pi_diagnostics.get_detection_service", {"return_value": self.service}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_soak(self):
        return memory_soak_test.run_memory_check(self.app, self.args)

    def test_successful_measurement_closes_once(self):
        self.assertEqual(self.run_soak(), 0)
        self.assertEqual(self.service.detect.call_count, 15)
        self.shutdown.assert_called_once_with()

    def test_zero_successes_cannot_pass_with_flat_rss(self):
        self.service.detect.side_effect = DetectionError("no equipment")
        self.assertEqual(self.run_soak(), 1)
        self.shutdown.assert_called_once_with()

    def test_mock_mode_closes_without_opening_camera(self):
        self.app.config["DETECTOR_MODE"] = "mock"
        for runner in (self.run_soak, lambda: pi_diagnostics.run_diagnostics(self.app)):
            with self.subTest(runner=runner):
                self.shutdown.reset_mock()
                self.assertEqual(runner(), 2)
                self.shutdown.assert_called_once_with()
        self.service.preflight.assert_not_called()

    def test_interrupts_close_during_preflight_warmup_and_measurement(self):
        for phase in ("preflight", "warmup", "measurement"):
            with self.subTest(phase=phase):
                self.service.reset_mock(side_effect=True)
                self.shutdown.reset_mock()
                if phase == "preflight":
                    self.service.preflight.side_effect = KeyboardInterrupt
                elif phase == "warmup":
                    self.service.detect.side_effect = KeyboardInterrupt
                else:
                    self.service.detect.side_effect = [self.service.detect.return_value] * 3 + [KeyboardInterrupt]
                self.assertEqual(self.run_soak(), 130)
                self.shutdown.assert_called_once_with()

    def test_unexpected_warmup_error_closes_before_propagating(self):
        self.service.detect.side_effect = MemoryError("allocation failed")
        with self.assertRaises(MemoryError):
            self.run_soak()
        self.shutdown.assert_called_once_with()

    def test_preflight_error_closes(self):
        self.service.preflight.side_effect = DetectionError("camera unavailable")
        self.assertEqual(self.run_soak(), 1)
        self.shutdown.assert_called_once_with()

    def test_failed_output_still_closes(self):
        for runner in (self.run_soak, lambda: pi_diagnostics.run_diagnostics(self.app)):
            with self.subTest(runner=runner):
                self.shutdown.reset_mock()
                with patch("builtins.print", side_effect=BrokenPipeError):
                    with self.assertRaises(BrokenPipeError):
                        runner()
                self.shutdown.assert_called_once_with()

    def test_rss_unavailable_cannot_pass(self):
        with patch("scripts.memory_soak_test.current_rss_mb", return_value=None):
            self.assertEqual(self.run_soak(), 1)
        self.shutdown.assert_called_once_with()

    def test_excessive_growth_fails(self):
        with patch("scripts.memory_soak_test.current_rss_mb", side_effect=[50] + [200] * 14):
            self.assertEqual(self.run_soak(), 1)
        self.shutdown.assert_called_once_with()

    def test_diagnostics_closes_on_early_metadata_error(self):
        with patch("scripts.pi_diagnostics.linux_memory", side_effect=OSError):
            with self.assertRaises(OSError):
                pi_diagnostics.run_diagnostics(self.app)
        self.shutdown.assert_called_once_with()

    def test_diagnostics_closes_on_success_failure_and_interrupt(self):
        for error, expected in ((None, 0), (DetectionError("no camera"), 1), (KeyboardInterrupt, 130)):
            with self.subTest(error=error):
                self.shutdown.reset_mock()
                self.service.preflight.side_effect = error
                self.assertEqual(pi_diagnostics.run_diagnostics(self.app), expected)
                self.shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
