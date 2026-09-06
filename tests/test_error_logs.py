from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from equipment_manager.error_logs import ErrorLogStore


class ErrorLogStoreTestCase(unittest.TestCase):
    def test_rotation_display_limit_and_clear_are_bounded(self):
        package_logger = logging.getLogger("equipment_manager")
        original_propagate = package_logger.propagate
        package_logger.propagate = False

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "errors.log"
            store = ErrorLogStore(
                log_path,
                max_bytes=64 * 1024,
                backup_count=2,
                display_bytes=8 * 1024,
            )
            try:
                logger = logging.getLogger("equipment_manager.error-log-test")
                for index in range(40):
                    logger.error("entry-%s %s", index, "x" * 4000)

                snapshot = store.snapshot()
                self.assertTrue(snapshot["has_logs"])
                self.assertTrue(snapshot["truncated"])
                self.assertLessEqual(snapshot["file_count"], 3)
                self.assertIn("entry-39", snapshot["text"])
                self.assertLessEqual(
                    len(str(snapshot["text"]).encode("utf-8")),
                    8 * 1024,
                )

                store.clear()
                cleared = store.snapshot()
                self.assertFalse(cleared["has_logs"])
                self.assertEqual(cleared["file_count"], 0)
            finally:
                store.close()
                package_logger.propagate = original_propagate


if __name__ == "__main__":
    unittest.main()
