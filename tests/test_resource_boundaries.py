"""Fault injection with temporary data only; no camera, model or live DB."""
from __future__ import annotations

import gc
import sqlite3
import tempfile
import unittest
import weakref
from pathlib import Path

from flask import g

from equipment_manager import create_app
from equipment_manager.db import close_db, get_db, set_device_status
from equipment_manager.inventory import add_equipment, create_scan_session
from equipment_manager.vision.detector import YoloDetector
from equipment_manager.vision.types import DetectionError


class InterruptingConnection(sqlite3.Connection):
    interrupt_statement = None

    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        if self.interrupt_statement and self.interrupt_statement in sql:
            raise KeyboardInterrupt("interrupted after SQL write")
        return result


class DatabaseWriteBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.db"
        self.app = create_app({
            "TESTING": True, "DATABASE": str(self.path),
            "ERROR_LOG_PATH": str(Path(self.temp.name) / "errors.log"),
            "SECRET_KEY": "boundary-test", "HEARTBEAT_ENABLED": False,
            "DETECTOR_MODE": "mock", "DEFAULT_EQUIPMENT": ["meter"],
        })
        self.addCleanup(self.app.extensions["shutdown_services"])

    def test_interrupted_writes_roll_back_and_allow_next_transaction(self):
        operations = (
            ("INSERT INTO equipment", lambda: add_equipment("new item", 2, 7)),
            ("INSERT INTO scan_sessions", lambda: create_scan_session(1, 0.9, "teacher:test")),
            ("UPDATE device_status", lambda: set_device_status("must roll back")),
        )
        with self.app.app_context():
            close_db()
            connection = sqlite3.connect(self.path, factory=InterruptingConnection)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            g.db = connection
            for sql, operation in operations:
                with self.subTest(sql=sql):
                    connection.interrupt_statement = sql
                    try:
                        with self.assertRaises(KeyboardInterrupt):
                            operation()
                        self.assertFalse(connection.in_transaction)
                        self.assertEqual(connection.execute("SELECT COUNT(*) FROM equipment").fetchone()[0], 1)
                        self.assertEqual(connection.execute("SELECT COUNT(*) FROM scan_sessions").fetchone()[0], 0)
                        self.assertIsNone(connection.execute("SELECT last_error FROM device_status").fetchone()[0])
                        connection.execute("BEGIN IMMEDIATE")
                    finally:
                        connection.interrupt_statement = None
                        connection.rollback()

    def test_failed_scan_insert_does_not_commit_cleanup_or_hold_write_lock(self):
        with self.app.app_context():
            db = get_db()
            with db:
                db.execute("""INSERT INTO scan_sessions
                    (token, equipment_id, confidence, created_at, expires_at)
                    VALUES ('expired', 1, 0.9, '2000-01-01', '2000-01-02')""")
                db.execute("""CREATE TRIGGER reject_scan BEFORE INSERT ON scan_sessions
                    BEGIN SELECT RAISE(ABORT, 'write failed'); END""")
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    create_scan_session(1, 0.9)
                self.assertFalse(db.in_transaction)
                self.assertEqual(db.execute("SELECT token FROM scan_sessions").fetchone()[0], "expired")
            finally:
                db.rollback()


class Frame:
    def __init__(self):
        self.buffer = bytearray(640 * 480 * 3)


class Source:
    def close(self):
        pass


def detector_for_test(detector_type=YoloDetector):
    return detector_type({
        "YOLO_MODEL_PATH": "unused.pt", "YOLO_IMAGE_SIZE": 320,
        "YOLO_CONFIDENCE": 0.6, "YOLO_MIN_VOTES": 1,
        "YOLO_FRAME_COUNT": 1, "YOLO_MAX_DETECTIONS": 5, "INFERENCE_THREADS": 2,
    }, frame_source=Source())


class InferenceBoundaryTest(unittest.TestCase):
    def test_model_load_failure_does_not_pin_frames_in_retained_tracebacks(self):
        class MissingModel(YoloDetector):
            def _load_model(self):
                raise DetectionError("model missing")

        detector = detector_for_test(MissingModel)
        frames, errors = [], []
        for _ in range(100):
            frame = Frame()
            frames.append(weakref.ref(frame))
            try:
                detector._predict_best(frame)
            except DetectionError as exc:
                errors.append(exc)
            finally:
                frame = None
        gc.collect()
        self.assertEqual(len(errors), 100)
        self.assertTrue(all(reference() is None for reference in frames))

    def test_stream_close_interrupt_does_not_pin_model_after_shutdown(self):
        class Stream:
            def __iter__(self):
                return iter(())

            def close(self):
                raise KeyboardInterrupt

        class Model:
            predictor = None

            def predict(self, **kwargs):
                return Stream()

        detector = detector_for_test()
        detector._model = Model()
        reference = weakref.ref(detector._model)
        errors = []
        try:
            detector._predict_best(Frame())
        except KeyboardInterrupt as exc:
            errors.append(exc)
        detector.close()
        gc.collect()
        self.assertEqual(len(errors), 1)
        self.assertIsNone(reference())


if __name__ == "__main__":
    unittest.main()
