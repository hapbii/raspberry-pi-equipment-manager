from __future__ import annotations

import gc
import logging
import sqlite3
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask, g

from equipment_manager import create_app
from equipment_manager.db import get_db


class LifecycleTestCase(unittest.TestCase):
    def test_repeated_startup_failures_release_services_and_log_handlers(self):
        logger = logging.getLogger("equipment_manager")
        original_handlers = list(logger.handlers)
        with tempfile.TemporaryDirectory() as directory:
            config = {
                "TESTING": True,
                "DATABASE": str(Path(directory) / "test.db"),
                "ERROR_LOG_PATH": str(Path(directory) / "errors.log"),
                "HEARTBEAT_ENABLED": False,
            }
            for _ in range(20):
                detector = Mock()
                with patch("equipment_manager.build_detection_service", return_value=detector), patch(
                    "equipment_manager.init_app_database", side_effect=RuntimeError("DB unavailable")
                ):
                    with self.assertRaisesRegex(RuntimeError, "DB unavailable"):
                        create_app(config)
                detector.close.assert_called_once()
                self.assertEqual(logger.handlers, original_handlers)

    def test_manual_shutdown_unregisters_exit_callback_and_app_is_collectable(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({
                "HEARTBEAT_ENABLED": False,
                "DETECTOR_MODE": "mock",
                "DATABASE": str(Path(directory) / "test.db"),
                "ERROR_LOG_PATH": str(Path(directory) / "errors.log"),
            })
            reference = weakref.ref(app)
            app.extensions["shutdown_services"]()
            app.extensions["shutdown_services"]()
            del app
            gc.collect()
            self.assertIsNone(reference())

    def test_failed_connection_configuration_closes_connection(self):
        app = Flask(__name__)
        app.config["DATABASE"] = ":memory:"
        connection = Mock()
        connection.execute.side_effect = sqlite3.OperationalError("configuration failed")
        with app.app_context(), patch("equipment_manager.db.sqlite3.connect", return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                get_db()
            connection.close.assert_called_once()
            self.assertNotIn("db", g)
