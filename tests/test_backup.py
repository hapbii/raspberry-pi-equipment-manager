from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from equipment_manager.backup import backup_database


class DatabaseBackupTestCase(unittest.TestCase):
    def test_backup_is_readable_and_contains_source_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.db"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                db.execute("INSERT INTO sample(value) VALUES ('saved')")
                db.commit()

            destination = backup_database(source, root / "backups")

            self.assertTrue(destination.is_file())
            with closing(sqlite3.connect(destination)) as backup:
                value = backup.execute("SELECT value FROM sample").fetchone()[0]
                integrity = backup.execute("PRAGMA quick_check").fetchone()[0]
            self.assertEqual(value, "saved")
            self.assertEqual(integrity, "ok")

    def test_missing_source_does_not_create_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(FileNotFoundError):
                backup_database(root / "missing.db", root / "backups")

    def test_interrupt_closes_connections_and_removes_incomplete_backup(self):
        class InterruptedBackup(sqlite3.Connection):
            def backup(self, target):
                target.execute("CREATE TABLE incomplete (value)")
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.db"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE original (value)")
            real_connect = sqlite3.connect
            connections = []

            def connect(path):
                connection = real_connect(path, factory=InterruptedBackup)
                connections.append(connection)
                return connection

            with patch("equipment_manager.backup.sqlite3.connect", side_effect=connect):
                with self.assertRaises(KeyboardInterrupt):
                    backup_database(source, root / "backups")
            self.assertEqual(list((root / "backups").iterdir()), [])
            for connection in connections:
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")
            with closing(real_connect(source)) as db:
                self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='original'").fetchone())


if __name__ == "__main__":
    unittest.main()
