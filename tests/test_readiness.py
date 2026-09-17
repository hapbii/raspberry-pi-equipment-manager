import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from equipment_manager import create_app
from equipment_manager.readiness import recognition_status
from equipment_manager.vision.types import CameraError, PreflightResult
from equipment_manager.vision.detector import YoloDetector
from equipment_manager.vision.service import DetectionService


class ReadinessTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model = Path(self.temp.name) / "best.pt"
        self.app = create_app({"TESTING": True, "CSRF_ENABLED": False,
            "HEARTBEAT_ENABLED": False, "DETECTOR_MODE": "yolo", "YOLO_MODEL_PATH": str(self.model),
            "DATABASE": str(Path(self.temp.name) / "test.db"),
            "ERROR_LOG_PATH": str(Path(self.temp.name) / "errors.log"),
            "DEVELOPER_USERNAME": "developer", "DEVELOPER_PASSWORD": "test-password",
        })
        self.addCleanup(self.app.extensions["shutdown_services"])
        self.service = self.app.extensions["detection_service"]

    def status(self):
        with self.app.app_context():
            return recognition_status()

    def test_page_reads_do_not_open_camera_and_distinguish_missing_and_unchecked(self):
        with patch.object(YoloDetector, "_load_model", side_effect=AssertionError("must not load")):
            self.assertEqual(self.status()["state"], "model_missing")
            self.assertFalse(self.status()["can_scan"])
            self.model.touch()
            self.assertEqual(self.status()["state"], "unchecked")
            self.assertTrue(self.status()["can_scan"])
            self.assertEqual(self.app.test_client().get("/").status_code, 200)

    def test_preflight_records_camera_failure_and_success_without_transaction(self):
        self.model.touch()
        with patch.object(YoloDetector, "preflight", side_effect=CameraError("unplugged")):
            with self.assertRaises(CameraError):
                self.service.preflight()
        self.assertEqual(self.status()["state"], "camera_error")
        result = PreflightResult(str(self.model), "fake", 640, 480, None, None, 1, 20)
        with patch.object(YoloDetector, "preflight", return_value=result):
            self.service.preflight()
        self.assertEqual(self.status()["state"], "ready")
        self.assertIsNotNone(self.status()["checked_at"])
        self.assertEqual(self.service.status()["scan_count"], 0)

    def test_busy_preflight_does_not_queue_another_camera_operation(self):
        self.service._lock.acquire()
        try:
            from equipment_manager.vision import DetectionError
            with self.assertRaises(DetectionError):
                self.service.preflight()
        finally:
            self.service._lock.release()

    def test_only_developer_can_start_preflight(self):
        client = self.app.test_client()
        with patch.object(self.service, "preflight") as check:
            self.assertEqual(client.post("/developer/recognition-check").status_code, 302)
            check.assert_not_called()
            client.post("/admin/login", data={"username": "developer", "password": "test-password"})
            self.assertEqual(client.post("/developer/recognition-check").status_code, 302)
            check.assert_called_once()


if __name__ == "__main__":
    unittest.main()
