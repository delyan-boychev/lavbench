"""Create the one admin account or replace its credentials; data is deleted only on request."""

import argparse
import os
import secrets
import sys

from sqlalchemy import create_engine

os.umask(0o077)

# This script lives in backend/scripts/, so the backend package root is not on
# sys.path when it is invoked by path (python /app/scripts/setup-admin.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from config import Config  # noqa: E402
from models import User, db  # noqa: E402
from utils.dates import utcnow  # noqa: E402
from utils.migrations import migrate_database  # noqa: E402

CONFIRM_PHRASE = "drop everything"
CREDENTIALS_PATH = "/app/admin_credentials.txt"


def reset_database(engine):
    """Drop every table and all data, then recreate the empty schema."""
    print("Dropping all existing database tables...")  # noqa: T201
    try:
        with engine.begin() as connection:
            connection.execute(db.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    except Exception as e:
        print(f"Non-fatal error resetting schema: {e}. Falling back to drop_all...")  # noqa: T201
        db.metadata.drop_all(bind=engine)


def reset_confirmed(assume_yes):
    """Whether the operator confirmed the destructive reset."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(  # noqa: T201
            "Refusing to reset the database: confirm on a terminal, or pass --yes in a script."
        )
        return False
    print(  # noqa: T201
        "--reset-database deletes every competition, task, submission, score, user and audit"
        " entry in this database. Take a backup first if any of it matters."
    )
    answer = input(f"Type '{CONFIRM_PHRASE}' to continue: ")
    if answer.strip() != CONFIRM_PHRASE:
        print("Confirmation did not match; nothing was changed.")  # noqa: T201
        return False
    return True


def provision_admin():
    """Create the admin account, or give the existing one new credentials in place.

    Returns (username, master key, whether an existing account was replaced).
    """
    admin_username = f"admin_{secrets.token_hex(4)}"
    raw_key = f"admin_key_{secrets.token_hex(24)}"
    hashed_key = generate_password_hash(raw_key, method="pbkdf2:sha256")

    admins = User.query.filter_by(role="admin").all()
    if len(admins) > 1:
        msg = "More than one admin account exists; remove the extra ones before running this."
        raise SystemExit(msg)
    if admins:
        # Same row, so its audit history stays linked; the new hash ends its sessions
        admin = admins[0]
        admin.username = admin_username
        admin.password_hash = hashed_key
    else:
        admin = User(
            username=admin_username,
            password_hash=hashed_key,
            role="admin",
            alias_id=f"System-Root-{secrets.token_hex(3)}",
        )
        admin.set_demographics("Master", "Administrator", None, None, None)
        db.session.add(admin)
    db.session.commit()
    return admin_username, raw_key, bool(admins)


def save_credentials(admin_username, raw_key):
    """Write the credentials to a 0600 file and say where they went."""
    try:
        with open(CREDENTIALS_PATH, "w") as f:
            f.write("==================================================\n")
            f.write("      LAVBENCH ADMIN CREDENTIALS\n")
            f.write("==================================================\n")
            generated_on = utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            f.write(f"Generated On   : {generated_on}\n")
            f.write(f"Admin Username : {admin_username}\n")
            f.write(f"Master Key     : {raw_key}\n\n")
            f.write("Keep this file secure. Enter these credentials on the\n")
            f.write("login page (Sign In as Administrator checkbox).\n")
            f.write("==================================================\n")
        os.chmod(CREDENTIALS_PATH, 0o600)
        return f"Saved credentials to: {CREDENTIALS_PATH}"
    except Exception as e:
        return f"Failed to save credentials file: {e!s}"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Create the admin account, or replace the existing admin's username and master key."
            " Data is kept unless --reset-database is given."
        )
    )
    parser.add_argument(
        "--reset-database",
        action="store_true",
        help="first delete ALL data and tables (asks for a typed confirmation)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the typed confirmation of --reset-database (non-interactive scripts)",
    )
    args = parser.parse_args(argv)
    if args.reset_database and not reset_confirmed(args.yes):
        return 1

    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    if args.reset_database:
        reset_database(engine)
    print("Applying database migrations...")  # noqa: T201
    migrate_database(engine)
    engine.dispose()

    from app import create_app

    app = create_app()
    with app.app_context():
        admin_username, raw_key, replaced = provision_admin()

    saved_msg = save_credentials(admin_username, raw_key)
    print("\n" + "=" * 60)  # noqa: T201
    print("         MASTER ADMIN PROFILE GENERATOR ONLINE")  # noqa: T201
    print("=" * 60)  # noqa: T201
    if replaced:
        print("  The existing administrator account has new credentials.")  # noqa: T201
        print("  Its old username and master key no longer work.")  # noqa: T201
    else:
        print("  A secure administrator profile has been generated.")  # noqa: T201
    print("  Keep these credentials safe. Paste them to log in.")  # noqa: T201
    print("\n  Generated Admin Username:")  # noqa: T201
    print(f"  \033[96m{admin_username}\033[0m")  # noqa: T201
    print("  Generated Master Key:")  # noqa: T201
    print(f"  \033[92m{raw_key}\033[0m")  # noqa: T201
    print("\n  " + saved_msg)  # noqa: T201
    print("=" * 60 + "\n")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
