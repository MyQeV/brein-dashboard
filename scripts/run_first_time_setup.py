"""First-time setup: create admin user when no users exist. Used at app startup (main.py)."""

import asyncio
import getpass
import os
import sys

from brein.store import users as store_users


def run_first_time_setup(db_path: str | None = None) -> bool:
    """
    If no users exist, create the first admin user (interactive prompt or env vars).
    Returns True if setup is done or already had users; False on failure.
    """
    if asyncio.run(store_users.count_users()) > 0:
        return True

    username: str
    password: str
    email: str | None = None
    full_name: str | None = None

    admin_user = os.environ.get("BREIN_ADMIN_USERNAME", "").strip()
    admin_pass = os.environ.get("BREIN_ADMIN_PASSWORD", "").strip()

    if admin_user and admin_pass:
        username = admin_user
        password = admin_pass
        print(
            "Creating first admin user from BREIN_ADMIN_USERNAME / BREIN_ADMIN_PASSWORD."
        )
    else:
        print("No users in database. Create the first admin user.")
        try:
            username = input("Username: ").strip()
            if not username:
                print("Error: username is required.", file=sys.stderr)
                return False
            password = getpass.getpass("Password (min 8 characters): ")
            email_in = input("Email (optional, press Enter to skip): ").strip()
            email = email_in or None
            full_name_in = input("Full name (optional, press Enter to skip): ").strip()
            full_name = full_name_in or None
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return False

    if len(password) < 8:
        print("Error: password must be at least 8 characters.", file=sys.stderr)
        return False

    try:
        from brein.web import auth as web_auth
    except Exception as e:
        print(f"Error loading auth: {e}", file=sys.stderr)
        return False

    try:
        hashed = web_auth.get_password_hash(password)
        asyncio.run(
            store_users.create_user(
                username=username,
                hashed_password=hashed,
                email=email,
                full_name=full_name,
                is_admin=True,
            )
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return False

    print("Admin user created. Starting server.")
    return True
