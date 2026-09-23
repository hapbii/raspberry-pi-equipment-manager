from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing

from equipment_manager.db import immediate_transaction


class ImmediateTransactionTest(unittest.TestCase):
    def test_commit_and_rollback_including_interrupts_leave_no_open_transaction(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE items (value INTEGER NOT NULL)")
            with immediate_transaction(db):
                db.execute("INSERT INTO items VALUES (1)")
            self.assertFalse(db.in_transaction)
            for error in (ValueError, KeyboardInterrupt, SystemExit):
                with self.assertRaises(error):
                    with immediate_transaction(db):
                        db.execute("INSERT INTO items VALUES (2)")
                        raise error()
                self.assertFalse(db.in_transaction)
                self.assertEqual(db.execute("SELECT value FROM items").fetchall(), [(1,)])

    def test_failed_deferred_commit_also_rolls_back(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            db.execute("""CREATE TABLE child (parent_id INTEGER REFERENCES parent(id)
                DEFERRABLE INITIALLY DEFERRED)""")
            with self.assertRaises(sqlite3.IntegrityError):
                with immediate_transaction(db):
                    db.execute("INSERT INTO child VALUES (123)")
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute("SELECT * FROM child").fetchall(), [])
