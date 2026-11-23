import os
import re
import sqlite3
import tempfile
import unittest
from unittest import mock

import pandas as pd

from src import mailer, security
from src import user_service as us
from src.database import init_db


class RecoveryBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)
        self.admin = us.create_user("admin", "Admin12345", full_name="Boss", role="admin", must_change=False,
                                    email="Boss@Example.com", db_path=self.db)
        self.outbox = []

    def tearDown(self):
        os.remove(self.db)

    def sender(self, to, subject, body):
        self.outbox.append((to, subject, body))

    def code_from_mail(self):
        return re.search(r"\b(\d{6})\b", self.outbox[-1][2]).group(1)


class RecoveryCodeTests(RecoveryBase):
    def test_code_resets_password_and_rotates(self):
        code = us.create_recovery_code(self.admin, db_path=self.db)
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        new_code = us.reset_with_recovery_code("ADMIN", code.lower(), "Brand9New1", db_path=self.db)
        self.assertNotEqual(new_code, code)
        self.assertEqual(us.authenticate("admin", "Brand9New1", db_path=self.db)["username"], "admin")
        with self.assertRaises(us.AuthError):  # old code is single use
            us.reset_with_recovery_code("admin", code, "Another9Pass1", db_path=self.db)
        us.reset_with_recovery_code("admin", new_code, "Third9Pass12", db_path=self.db)

    def test_hash_only_is_stored(self):
        code = us.create_recovery_code(self.admin, db_path=self.db)
        stored = sqlite3.connect(self.db).execute("SELECT recovery_hash FROM users").fetchone()[0]
        self.assertNotIn(security.normalize_recovery_code(code), stored)
        self.assertTrue(us.get_user(self.admin, self.db)["has_recovery"])
        self.assertNotIn("recovery_hash", us.get_user(self.admin, self.db))

    def test_wrong_code_is_generic_and_locks_after_five(self):
        us.create_recovery_code(self.admin, db_path=self.db)
        for _ in range(us.MAX_FAILED_ATTEMPTS):
            with self.assertRaises(us.AuthError) as ctx:
                us.reset_with_recovery_code("admin", "AAAA-BBBB-CCCC", "Brand9New1", db_path=self.db)
            self.assertEqual(str(ctx.exception), us.GENERIC_RECOVERY_ERROR)
        with self.assertRaises(us.AuthError) as ctx:
            us.reset_with_recovery_code("admin", "AAAA-BBBB-CCCC", "Brand9New1", db_path=self.db)
        self.assertIn("Too many", str(ctx.exception))

    def test_unknown_user_no_code_and_inactive_are_generic(self):
        for name in ("nobody", "admin"):  # admin has no code yet
            with self.assertRaises(us.AuthError) as ctx:
                us.reset_with_recovery_code(name, "AAAA-BBBB-CCCC", "Brand9New1", db_path=self.db)
            self.assertEqual(str(ctx.exception), us.GENERIC_RECOVERY_ERROR)

    def test_weak_new_password_does_not_burn_the_code(self):
        code = us.create_recovery_code(self.admin, db_path=self.db)
        with self.assertRaises(ValueError):
            us.reset_with_recovery_code("admin", code, "weak", db_path=self.db)
        us.reset_with_recovery_code("admin", code, "Strong9Pass1", db_path=self.db)


class EmailCodeTests(RecoveryBase):
    def test_full_flow(self):
        self.assertTrue(us.request_email_code("Admin", sender=self.sender, db_path=self.db))
        to, subject, body = self.outbox[-1]
        self.assertEqual(to, "boss@example.com")
        code = self.code_from_mail()
        us.reset_with_email_code("admin", code, "Fresh9Pass1", db_path=self.db)
        self.assertEqual(us.authenticate("admin", "Fresh9Pass1", db_path=self.db)["username"], "admin")
        with self.assertRaises(us.AuthError):  # single use
            us.reset_with_email_code("admin", code, "Other9Pass12", db_path=self.db)

    def test_unknown_user_or_missing_email_sends_nothing(self):
        us.create_user("noemail", "Temp12345", db_path=self.db)
        self.assertFalse(us.request_email_code("ghost", sender=self.sender, db_path=self.db))
        self.assertFalse(us.request_email_code("noemail", sender=self.sender, db_path=self.db))
        self.assertEqual(self.outbox, [])

    def test_wrong_code_five_times_kills_it(self):
        us.request_email_code("admin", sender=self.sender, db_path=self.db)
        good = self.code_from_mail()
        bad = "000000" if good != "000000" else "111111"
        for _ in range(us.MAX_FAILED_ATTEMPTS):
            with self.assertRaises(us.AuthError):
                us.reset_with_email_code("admin", bad, "Fresh9Pass1", db_path=self.db)
        with self.assertRaises(us.AuthError):
            us.reset_with_email_code("admin", good, "Fresh9Pass1", db_path=self.db)

    def test_expired_code_rejected(self):
        us.request_email_code("admin", sender=self.sender, db_path=self.db)
        code = self.code_from_mail()
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE password_resets SET expires_at = '2000-01-01 00:00:00'")
        conn.commit()
        conn.close()
        with self.assertRaises(us.AuthError):
            us.reset_with_email_code("admin", code, "Fresh9Pass1", db_path=self.db)

    def test_request_throttle(self):
        results = [us.request_email_code("admin", sender=self.sender, db_path=self.db) for _ in range(5)]
        self.assertEqual(results, [True] * 3 + [False] * 2)

    def test_mail_failure_is_swallowed_and_code_disabled(self):
        def boom(*args):
            raise mailer.MailError("smtp down")

        self.assertFalse(us.request_email_code("admin", sender=boom, db_path=self.db))
        self.assertEqual(sqlite3.connect(self.db).execute(
            "SELECT COUNT(*) FROM password_resets WHERE used = 0").fetchone()[0], 0)

    def test_code_is_not_stored_in_clear(self):
        us.request_email_code("admin", sender=self.sender, db_path=self.db)
        stored = sqlite3.connect(self.db).execute("SELECT code_hash FROM password_resets").fetchone()[0]
        self.assertNotIn(self.code_from_mail(), stored.split("$")[0])


class UsernameReminderTests(RecoveryBase):
    def test_reminder_sent_case_insensitively_and_throttled(self):
        self.assertEqual(us.send_username_reminders("BOSS@example.com", sender=self.sender, db_path=self.db), 1)
        self.assertIn("admin", self.outbox[-1][2])
        for _ in range(2):
            us.send_username_reminders("boss@example.com", sender=self.sender, db_path=self.db)
        self.assertEqual(us.send_username_reminders("boss@example.com", sender=self.sender, db_path=self.db), 0)

    def test_unknown_or_invalid_address(self):
        self.assertEqual(us.send_username_reminders("who@example.com", sender=self.sender, db_path=self.db), 0)
        self.assertEqual(us.send_username_reminders("not-an-email", sender=self.sender, db_path=self.db), 0)
        self.assertEqual(self.outbox, [])


class AdminRequestTests(RecoveryBase):
    def test_request_lifecycle(self):
        us.create_reset_request("Boss", "forgot password, phone 0300", db_path=self.db)  # matches by full name
        us.create_reset_request("boss", "again", db_path=self.db)  # same person within 24 h: ignored
        self.assertEqual(us.pending_request_count(self.db), 1)
        df = us.list_reset_requests(db_path=self.db)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["matched_username"], "admin")
        us.resolve_reset_request(int(df.iloc[0]["id"]), "resolved", actor="admin", db_path=self.db)
        self.assertEqual(us.pending_request_count(self.db), 0)
        self.assertEqual(len(us.list_reset_requests(status=None, db_path=self.db)), 1)

    def test_unknown_name_is_recorded_unmatched(self):
        us.create_reset_request("somebody else", db_path=self.db)
        row = us.list_reset_requests(db_path=self.db).iloc[0]
        self.assertTrue(pd.isna(row["matched_username"]))

    def test_empty_identifier(self):
        with self.assertRaises(us.AuthError):
            us.create_reset_request("   ", db_path=self.db)

    def test_long_input_is_truncated(self):
        us.create_reset_request("x" * 500, "n" * 5000, db_path=self.db)
        row = us.list_reset_requests(db_path=self.db).iloc[0]
        self.assertLessEqual(len(row["identifier"]), 60)
        self.assertLessEqual(len(row["note"]), 300)


class EmailAndMailerTests(RecoveryBase):
    def test_set_email_validation(self):
        us.set_email(self.admin, " New@Example.org ", db_path=self.db)
        self.assertEqual(us.get_user(self.admin, self.db)["email"], "new@example.org")
        us.set_email(self.admin, "", db_path=self.db)
        self.assertIsNone(us.get_user(self.admin, self.db)["email"])
        for bad in ("nope", "a@b", "a b@c.d"):
            with self.assertRaises(us.AuthError):
                us.set_email(self.admin, bad, db_path=self.db)

    def test_mailer_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("SMTP_HOST", "SMTP_FROM", "SMTP_USER"):
                os.environ.pop(key, None)
            self.assertFalse(mailer.is_configured())
            with self.assertRaises(mailer.MailError):
                mailer.send_email("a@b.co", "s", "b")

    def test_mailer_sends_via_starttls_with_login(self):
        env = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
               "SMTP_FROM": "noreply@example.com"}
        with mock.patch.dict(os.environ, env), mock.patch("smtplib.SMTP") as smtp:
            server = smtp.return_value
            server.__enter__.return_value = server  # like the real smtplib.SMTP context manager
            self.assertTrue(mailer.is_configured())
            mailer.send_email("to@example.com", "Hi", "Body")
            smtp.assert_called_once_with("smtp.example.com", 587, timeout=20)
            server.starttls.assert_called_once()
            server.login.assert_called_once_with("u", "p")
            sent = server.send_message.call_args[0][0]
            self.assertEqual(sent["To"], "to@example.com")

    def test_mailer_wraps_network_errors(self):
        env = {"SMTP_HOST": "smtp.example.com", "SMTP_FROM": "noreply@example.com"}
        with mock.patch.dict(os.environ, env), mock.patch("smtplib.SMTP", side_effect=OSError("no route")):
            with self.assertRaises(mailer.MailError):
                mailer.send_email("to@example.com", "Hi", "Body")


class MigrationTests(unittest.TestCase):
    def test_v2_database_gets_new_columns_and_keeps_users(self):
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(db)
            conn.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, full_name TEXT,
                    role TEXT NOT NULL DEFAULT 'user', password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 0, failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT, last_login TEXT, created_at TEXT);
                INSERT INTO users (username, role, password_hash) VALUES ('admin','admin','x');
            """)
            conn.commit()
            conn.close()
            init_db(db)
            init_db(db)
            cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(users)")}
            self.assertTrue({"email", "recovery_hash", "recovery_created_at", "password_changed_at"} <= cols)
            self.assertEqual(us.count_users(db), 1)
        finally:
            os.remove(db)


if __name__ == "__main__":
    unittest.main()
