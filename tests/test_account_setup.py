from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from equipment_manager.account_setup import ACCOUNT_KEYS, ensure_role_accounts


class AccountSetupTestCase(unittest.TestCase):
    def test_legacy_admin_becomes_developer_without_losing_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "SECRET_KEY=test\nADMIN_USERNAME=old-admin\n"
                "ADMIN_PASSWORD=kept-password\nDETECTOR_MODE=mock\n",
                encoding="utf-8",
            )

            accounts, added = ensure_role_accounts(env_path)

            self.assertEqual(accounts["DEVELOPER_USERNAME"], "developer")
            self.assertEqual(accounts["DEVELOPER_PASSWORD"], "kept-password")
            self.assertEqual(accounts["TEACHER_USERNAME"], "teacher")
            self.assertGreaterEqual(len(accounts["TEACHER_PASSWORD"]), 12)
            self.assertEqual(set(added), set(ACCOUNT_KEYS))
            updated = env_path.read_text(encoding="utf-8")
            self.assertIn("DEVELOPER_PASSWORD=kept-password", updated)
            self.assertIn("TEACHER_USERNAME=teacher", updated)

    def test_setup_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("SECRET_KEY=test\n", encoding="utf-8")

            first_accounts, first_added = ensure_role_accounts(env_path)
            first_contents = env_path.read_text(encoding="utf-8")
            second_accounts, second_added = ensure_role_accounts(env_path)

            self.assertTrue(first_added)
            self.assertFalse(second_added)
            self.assertEqual(first_accounts, second_accounts)
            self.assertEqual(first_contents, env_path.read_text(encoding="utf-8"))
            for key in ACCOUNT_KEYS:
                self.assertEqual(first_contents.count(f"{key}="), 1)

    def test_missing_env_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                ensure_role_accounts(Path(temp_dir) / ".env")


if __name__ == "__main__":
    unittest.main()
