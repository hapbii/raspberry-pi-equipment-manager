from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
