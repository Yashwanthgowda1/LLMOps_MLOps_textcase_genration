import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from Api_mock import auth
from Api_mock.password_utils import hash_password, verify_password
from Sqllite.migrate_passwords import migrate_passwords


class PasswordHashTests(unittest.TestCase):
    def test_hash_verifies_only_the_original_password(self):
        stored_hash = hash_password("correct horse battery staple")

        self.assertNotEqual(stored_hash, "correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", stored_hash))
        self.assertFalse(verify_password("wrong password", stored_hash))
        self.assertFalse(verify_password("password", "not-a-valid-hash"))


class PasswordAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "users.db"
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    last_login DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
            )
        self.db_path_patch = patch.object(auth, "DB_PATH", str(self.database_path))
        self.db_path_patch.start()

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_registration_hashes_password_and_login_verifies_it(self):
        result = auth.registration_new_user({
            "email": "new@example.test",
            "name": "New User",
            "password": "safe-demo-password",
        })

        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            stored_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("new@example.test",),
            ).fetchone()[0]

        self.assertNotEqual(stored_hash, "safe-demo-password")
        self.assertTrue(verify_password("safe-demo-password", stored_hash))
        self.assertNotIn("password_hash", result)

        login_result = auth.login(SimpleNamespace(
            username="new@example.test",
            password="safe-demo-password",
        ))
        self.assertEqual(login_result["user_id"], result["user_id"])

        with self.assertRaises(HTTPException) as error:
            auth.login(SimpleNamespace(
                username="new@example.test",
                password="incorrect",
            ))
        self.assertEqual(error.exception.status_code, 401)

    def test_migration_hashes_existing_plaintext_password(self):
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """INSERT INTO users (email, name, password_hash, role)
                   VALUES (?, ?, ?, ?)""",
                ("legacy@example.test", "Legacy User", "legacy-password", "Customer"),
            )

        self.assertEqual(migrate_passwords(self.database_path), 1)

        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            stored_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("legacy@example.test",),
            ).fetchone()[0]

        self.assertNotEqual(stored_hash, "legacy-password")
        self.assertTrue(verify_password("legacy-password", stored_hash))
        self.assertEqual(migrate_passwords(self.database_path), 0)


if __name__ == "__main__":
    unittest.main()
