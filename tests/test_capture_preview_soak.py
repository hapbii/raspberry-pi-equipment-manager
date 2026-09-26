"""Optional real JPEG encode/write soak on synthetic pixels, without a camera or DB."""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import re
import sys
import tempfile
import threading
import unittest
import weakref
from collections import deque
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from equipment_manager.system_metrics import current_rss_mb
from scripts.capture_preview import PreviewSession, create_preview_app
from scripts.capture_samples import _save_frame


def run_preview_soak(cycles=1000, warmup=50):
    import cv2
    import numpy as np

    class SyntheticCamera:
        backend_name = "picamera2"
        previous = None
        closed = False
        iterator_count = 0

        def frames(self, count):
            frame = None
            try:
                for _ in range(count):
                    if self.previous is not None and self.previous() is not None:
                        raise AssertionError("Previous frame is still retained")
                    frame = np.full((1080, 1920, 3), 80, dtype=np.uint8)
                    self.previous = weakref.ref(frame)
                    try:
                        yield frame
                    finally:
                        frame = None
            finally:
                frame = None
                self.iterator_count += 1

        def close(self):
            self.closed = True

    threads_before = threading.active_count()
    samples = deque(maxlen=6)
    with tempfile.TemporaryDirectory(prefix="equipment-preview-soak-") as directory:
        output = Path(directory)
        source = SyntheticCamera()

        def save_photo(frame, index):
            try:
                path = output / f"photo_{index}.jpg"
                _save_frame(source.backend_name, cv2, frame, path)
                return path
            finally:
                frame = None

        session = PreviewSession(source, cv2, save_photo, cycles + warmup)
        app = create_preview_app(session, "soak", output)
        reference = weakref.ref(app)
        client = app.test_client()
        with client.get("/") as response:
            token = re.search(r'data-token="([^"]+)"', response.get_data(as_text=True)).group(1)
        headers = {"X-Preview-Token": token}

        def cycle(index):
            with client.get("/frame.jpg", headers=headers) as response:
                if response.status_code != 200 or not response.data.startswith(b"\xff\xd8"):
                    raise AssertionError("Expected a real JPEG response")
            if index % 25 == 0:
                with client.post("/capture", headers=headers) as response:
                    if response.status_code != 200:
                        raise AssertionError(response.get_data(as_text=True))

        try:
            for index in range(warmup):
                cycle(index)
            gc.collect()
            baseline = current_rss_mb()
            for index in range(cycles):
                cycle(index)
                if (index + 1) % max(1, cycles // 5) == 0:
                    samples.append(current_rss_mb())
            final = current_rss_mb()
            saved = session.saved
            files = sum(1 for _ in output.glob("*.jpg"))
            frames_released = source.previous is not None and source.previous() is None
        finally:
            session.close()
        response = client = app = None
        gc.collect()
        return {
            "preview_cycles": cycles, "warmup_cycles": warmup,
            "input_resolution": "1920x1080 (synthetic pixels)",
            "saved_photos": saved, "file_count_matches": files == saved,
            "baseline_rss_mb": baseline, "rss_samples_mb": list(samples), "final_rss_mb": final,
            "frame_references_released": frames_released, "source_closed": source.closed,
            "application_released": reference() is None,
            "thread_count_before": threads_before, "thread_count_after": threading.active_count(),
        }


@unittest.skipUnless(importlib.util.find_spec("cv2") and importlib.util.find_spec("numpy"),
                     "Optional JPEG soak requires OpenCV and NumPy")
class PreviewJpegSoakTest(unittest.TestCase):
    def test_real_jpeg_requests_release_frame_and_app(self):
        report = run_preview_soak(cycles=30, warmup=5)
        for key in ("file_count_matches", "frame_references_released", "source_closed", "application_released"):
            self.assertTrue(report[key], key)
        self.assertEqual(report["thread_count_after"], report["thread_count_before"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=50)
    args = parser.parse_args()
    if args.cycles < 1 or args.warmup < 0:
        parser.error("cycles must be positive and warmup must be nonnegative")
    result = run_preview_soak(args.cycles, args.warmup)
    print(json.dumps(result, indent=2))
    if not (all(result[key] for key in (
        "file_count_matches", "frame_references_released", "source_closed", "application_released"
    )) and result["thread_count_after"] == result["thread_count_before"]):
        raise SystemExit(1)
