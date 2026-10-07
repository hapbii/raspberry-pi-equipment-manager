from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path

from equipment_manager.error_logs import ErrorLogStore


class ErrorLogStoreTestCase(unittest.TestCase):
    def test_formatting_does_not_cache_large_traceback_on_shared_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ErrorLogStore(Path(directory) / "errors.log", max_bytes=65536,
                                  backup_count=2, display_bytes=8192)
            try:
                try:
                    raise RuntimeError("large failure " + "x" * 100000)
                except RuntimeError:
                    record = logging.LogRecord("equipment_manager", logging.ERROR,
                                               "test", 1, "failed", (), sys.exc_info())
                store._handler.handle(record)
                self.assertTrue(record.exc_text is None, "shared record cached an unbounded traceback")
                self.assertIn("[log entry truncated]", store.snapshot()["text"])
                self.assertLessEqual(store.path.stat().st_size, 16500)
            finally:
                store.close()

    def test_oversized_records_are_bounded_and_closed_handler_cannot_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "errors.log"
            store = ErrorLogStore(path, max_bytes=65536, backup_count=2, display_bytes=8192)
            handler = store._handler
            try:
                for _ in range(20):
                    record = logging.LogRecord("equipment_manager", logging.ERROR, "test", 1,
                                               "한글" * 100000, (), None)
                    handler.handle(record)
                self.assertLessEqual(store.snapshot()["total_size_bytes"], 3 * 65536)
                for log in Path(directory).iterdir():
                    self.assertLessEqual(log.stat().st_size, 65536)
                store.clear()
                handler.handle(logging.makeLogRecord({"msg": "after clear", "levelno": logging.ERROR}))
                self.assertIn("after clear", store.snapshot()["text"])
            finally:
                store.close()
            self.assertIsNone(handler.stream)
            size = path.stat().st_size
            handler.handle(logging.makeLogRecord({"msg": "after close", "levelno": logging.ERROR}))
            self.assertIsNone(handler.stream)
            self.assertEqual(path.stat().st_size, size)

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
