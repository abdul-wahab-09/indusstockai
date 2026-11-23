import os
import tempfile
import unittest

from src import inventory_service as svc
from src import security, user_service as us
from src.database import init_db


class SecurityTests(unittest.TestCase):
    def test_hash_and_verify(self):
        stored = security.hash_password("Secret123")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertNotIn("Secret123", stored)
        self.assertTrue(security.verify_password("Secret123", stored))
        self.assertFalse(security.verify_password("secret123", stored))
        self.assertNotEqual(stored, security.hash_password("Secret123"))  # unique salt
        self.assertFalse(security.verify_password("x", "garbage"))

    def test_password_policy(self):
        for bad in ("short1", "alllettersonly", "123456789"):
            with self.assertRaises(ValueError):
                security.validate_password(bad)
        security.validate_password("goodpass1")

    def test_username_rules(self):
        self.assertEqual(security.normalize_username("  Ali.Khan "), "ali.khan")
        for bad in ("ab", "has space", "bad!char", "x" * 31):
            with self.assertRaises(ValueError):
                security.normalize_username(bad)

    def test_generated_password_meets_policy(self):
        for _ in range(50):
            security.validate_password(security.generate_password())


class UserServiceTests(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self.db)
        self.admin = us.create_user("admin", "Admin12345", full_name="Boss", role="admin",
                                    must_change=False, db_path=self.db)

    def tearDown(self):
        os.remove(self.db)

    def test_create_and_login(self):
        us.create_user("Ali", "Temp12345", role="user", db_path=self.db)
        user = us.authenticate("ali", "Temp12345", db_path=self.db)
        self.assertEqual((user["username"], user["role"], user["must_change_password"]), ("ali", "user", 1))
        self.assertNotIn("password_hash", user)

    def test_duplicate_username_and_bad_role(self):
        with self.assertRaises(us.AuthError):
            us.create_user("ADMIN", "Another123", db_path=self.db)
        with self.assertRaises(us.AuthError):
            us.create_user("bob", "Bobpass123", role="root", db_path=self.db)

    def test_wrong_password_uses_generic_message(self):
        for name, pw in (("admin", "wrong"), ("nobody", "whatever1")):
            with self.assertRaises(us.AuthError) as ctx:
                us.authenticate(name, pw, db_path=self.db)
            self.assertEqual(str(ctx.exception), us.GENERIC_LOGIN_ERROR)

    def test_lockout_after_repeated_failures_and_unlock(self):
        for _ in range(us.MAX_FAILED_ATTEMPTS):
            with self.assertRaises(us.AuthError):
                us.authenticate("admin", "bad", db_path=self.db)
        with self.assertRaises(us.AuthError) as ctx:
            us.authenticate("admin", "Admin12345", db_path=self.db)  # correct password, still locked
        self.assertIn("locked", str(ctx.exception))
        us.unlock_user(self.admin, db_path=self.db)
        self.assertEqual(us.authenticate("admin", "Admin12345", db_path=self.db)["username"], "admin")

    def test_inactive_user_cannot_sign_in(self):
        uid = us.create_user("ali", "Temp12345", db_path=self.db)
        us.update_user(uid, is_active=False, db_path=self.db)
        with self.assertRaises(us.AuthError) as ctx:
            us.authenticate("ali", "Temp12345", db_path=self.db)
        self.assertIn("deactivated", str(ctx.exception))

    def test_last_admin_is_protected(self):
        with self.assertRaises(us.AuthError):
            us.update_user(self.admin, role="user", db_path=self.db)
        with self.assertRaises(us.AuthError):
            us.update_user(self.admin, is_active=False, db_path=self.db)
        second = us.create_user("admin2", "Admin22222", role="admin", db_path=self.db)
        us.update_user(second, is_active=False, db_path=self.db)  # fine: another admin remains
        with self.assertRaises(us.AuthError):
            us.update_user(self.admin, is_active=False, actor_id=self.admin, db_path=self.db)

    def test_change_own_password(self):
        with self.assertRaises(us.AuthError):
            us.change_own_password(self.admin, "wrong", "NewPass123", db_path=self.db)
        with self.assertRaises(us.AuthError):
            us.change_own_password(self.admin, "Admin12345", "Admin12345", db_path=self.db)
        us.change_own_password(self.admin, "Admin12345", "NewPass123", db_path=self.db)
        self.assertEqual(us.authenticate("admin", "NewPass123", db_path=self.db)["username"], "admin")

    def test_reset_password_forces_change_and_clears_lock(self):
        uid = us.create_user("ali", "Temp12345", must_change=False, db_path=self.db)
        us.reset_password(uid, "Reset12345", db_path=self.db)
        user = us.authenticate("ali", "Reset12345", db_path=self.db)
        self.assertEqual(user["must_change_password"], 1)

    def test_events_are_audited_without_passwords(self):
        us.create_user("ali", "Temp12345", db_path=self.db)
        us.authenticate("ali", "Temp12345", db_path=self.db)
        with self.assertRaises(us.AuthError):
            us.authenticate("ali", "bad", db_path=self.db)
        log = svc.audit_df(db_path=self.db)
        actions = set(log["action"])
        self.assertTrue({"USER_CREATED", "LOGIN", "LOGIN_FAILED"} <= actions)
        self.assertFalse(log["details"].str.contains("Temp12345|bad").any())

    def test_list_users_hides_hashes(self):
        df = us.list_users(db_path=self.db)
        self.assertNotIn("password_hash", df.columns)
        self.assertEqual(len(df), 1)


if __name__ == "__main__":
    unittest.main()
