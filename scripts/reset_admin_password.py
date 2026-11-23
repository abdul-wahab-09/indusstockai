"""Recover access from the computer that runs the app (stop the app first).

  python scripts/reset_admin_password.py --list       show all usernames (use this if you forgot the username)
  python scripts/reset_admin_password.py <username>   set a new temporary password and unlock the account

The person must choose a new password at the next sign-in.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import user_service  # noqa: E402
from src.database import init_db  # noqa: E402

if len(sys.argv) != 2:
    sys.exit(__doc__)

init_db()
users = user_service.list_users()

if sys.argv[1] == "--list":
    if users.empty:
        sys.exit("No accounts yet. Start the app to create the administrator.")
    for row in users.itertuples():
        state = "active" if row.is_active else "DEACTIVATED"
        print(f"  {row.username:<20} {row.role:<6} {state:<12} {row.full_name or ''}")
    sys.exit(0)

match = users[users["username"] == sys.argv[1].strip().lower()]
if match.empty:
    sys.exit(f"No user named '{sys.argv[1]}'. Run with --list to see the usernames.")

password = getpass.getpass("New temporary password (8+ characters, letter and number): ")
if password != getpass.getpass("Repeat password: "):
    sys.exit("Passwords do not match.")
try:
    user_id = int(match.iloc[0]["id"])
    user_service.reset_password(user_id, password, must_change=True, actor="recovery-script")
    user_service.unlock_user(user_id, actor="recovery-script")
    user_service.update_user(user_id, is_active=True, actor="recovery-script")
except ValueError as error:
    sys.exit(str(error))
print("Done. Sign in with the new password; you will be asked to change it.")
