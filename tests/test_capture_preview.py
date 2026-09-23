from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.capture_preview import PreviewSession, create_preview_app, run_preview
from equipment_manager.vision.types import DetectionError
from test_capture_samples import Frame, FrameSource, FakeCv


class Encoded:
    def tobytes(self):
        return b"jpeg-bytes"


class PreviewCv(FakeCv):
    def imencode(self, extension, frame, options):
        return self.succeed, Encoded()


class CapturePreviewTests(unittest.TestCase):
    def setUp(self):
        self.source = FrameSource()
        self.cv = PreviewCv()
        self.writes = []
        self.session = PreviewSession(self.source, self.cv, self.save_photo, 3)
        self.addCleanup(self.session.close)
        patcher = patch.object(Frame, "shape", (480, 640, 3), create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_preview_app(self.session, "raspberry_pi", Path("photos"))
        self.client = self.app.test_client()
        html = self.client.get("/").get_data(as_text=True)
        token = re.search(r'data-token="([^"]+)"', html).group(1)
        self.headers = {"X-Preview-Token": token}

    def save_photo(self, frame, index):
        self.writes.append(index)
        return Path(f"photo_{index}.jpg")

    def test_preview_does_not_save_and_releases_500_frames(self):
        for _ in range(500):
            response = self.client.get("/frame.jpg", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"jpeg-bytes")
            self.assertEqual(response.headers["X-Saved-Count"], "0")
            self.assertTrue(all(ref() is None for ref in self.source.references))
            response.close()
        self.assertEqual(self.writes, [])
        self.assertEqual(self.source.events.count("iterator-close"), 500)

    def test_save_count_limit_and_no_photos_retained(self):
        for index in range(1, 4):
            response = self.client.post("/capture", headers=self.headers)
            self.assertEqual(response.json, {"saved": index, "limit": 3, "file": f"photo_{index}.jpg"})
        self.assertEqual(self.client.post("/capture", headers=self.headers).status_code, 409)
        self.assertEqual(self.writes, [1, 2, 3])
        self.assertTrue(all(ref() is None for ref in self.source.references))

    def test_api_requires_token_and_capture_requires_post(self):
        self.assertEqual(self.client.get("/frame.jpg").status_code, 403)
        self.assertEqual(self.client.post("/capture").status_code, 403)
        self.assertEqual(self.client.post("/capture", headers={"X-Preview-Token": "bad"}).status_code, 403)
        self.assertEqual(self.client.get("/capture", headers=self.headers).status_code, 405)
        self.assertEqual(self.source.references, [])

    def test_dns_rebinding_host_and_cache_protection(self):
        self.assertEqual(self.client.get("/", base_url="http://attacker.example").status_code, 400)
        response = self.client.get("/")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        asset = self.client.get("/assets/preview.js")
        try:
            self.assertEqual(asset.status_code, 200)
        finally:
            asset.close()

    def test_camera_busy_rejects_without_queuing(self):
        with self.session._lock:
            self.assertEqual(self.client.post("/capture", headers=self.headers).status_code, 409)
            self.assertEqual(self.client.get("/frame.jpg", headers=self.headers).status_code, 409)
        self.assertEqual(self.source.references, [])

    def test_usb_discards_old_frames_for_preview_and_save(self):
        self.source.backend_name = "opencv"
        self.session.take_frame()
        self.session.take_frame(save=True)
        self.assertEqual(len(self.source.references), 8)
        self.assertEqual(self.writes, [1])
        self.assertTrue(all(ref() is None for ref in self.source.references))

    def test_saved_frame_is_not_resized_but_preview_is(self):
        sizes = []
        self.cv.resize = lambda frame, size: sizes.append(size) or frame
        with patch.object(Frame, "shape", (1080, 1920, 3)):
            self.session.take_frame()
            self.session.take_frame(save=True)
        self.assertEqual(sizes, [(640, 360)])

    def test_encoding_failure_closes_iterator_releases_frame_and_lock(self):
        self.cv.succeed = False
        try:
            self.session.take_frame()
        except DetectionError as error:
            self.assertTrue(all(ref() is None for ref in self.source.references))
            self.assertFalse(self.session._lock.locked())
            self.assertIn("변환", str(error))
        else:
            self.fail("expected encoding error")
        self.cv.succeed = True
        self.session.take_frame()

    def test_save_failure_does_not_increment_and_next_request_can_retry(self):
        def fail_save(frame, index):
            try:
                raise OSError("disk full")
            finally:
                frame = None
        with patch.object(self.session, "save_photo", fail_save):
            with self.assertLogs("scripts.capture_preview", level="ERROR"):
                self.assertEqual(self.client.post("/capture", headers=self.headers).status_code, 503)
        self.assertEqual(self.session.saved, 0)
        self.assertTrue(all(ref() is None for ref in self.source.references))
        self.assertEqual(self.client.post("/capture", headers=self.headers).status_code, 200)

    def test_empty_camera_iterator_is_error(self):
        with patch.object(self.source, "frames", return_value=(x for x in [])):
            with self.assertRaises(DetectionError):
                self.session.take_frame()

    def test_close_idempotent_and_blocks_new_capture(self):
        self.session.close()
        self.session.close()
        self.assertEqual(self.source.events, ["camera-close"])
        with self.assertRaises(DetectionError):
            self.session.take_frame()

    def test_server_bind_error_interrupt_and_normal_exit_close_camera(self):
        for error, code in [(OSError("port busy"), 1), (KeyboardInterrupt(), 130), (None, 0)]:
            source = FrameSource()
            with patch("scripts.capture_preview.run_web_server", side_effect=error) as server, patch("builtins.print"):
                result = run_preview(source, self.cv, self.save_photo, "test", 2, Path("photos"), 8081)
            self.assertEqual(result, code)
            self.assertEqual(source.events, ["camera-close"])
            self.assertEqual(server.call_args.kwargs["host"], "127.0.0.1")

    def test_startup_failure_closes_camera(self):
        with patch("scripts.capture_preview.create_preview_app", side_effect=RuntimeError("startup")):
            with self.assertRaises(RuntimeError):
                run_preview(self.source, self.cv, self.save_photo, "test", 2, Path("photos"), 8081)
        self.assertEqual(self.source.events, ["camera-close"])


if __name__ == "__main__":
    unittest.main()
