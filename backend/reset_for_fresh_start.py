import os
import sys
import secrets
import hashlib
from datetime import datetime

from werkzeug.security import generate_password_hash

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from models import db, User


def reset_and_create_admin():
    app = create_app()
    with app.app_context():
        print("Dropping all database tables...")
        # Use raw engine connection to bypass SQLAlchemy session autoflush
        with db.engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(db.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

        print("Creating database tables...")
        db.create_all()

        admin_username = f"admin_{secrets.token_hex(4)}"
        raw_key = f"admin_key_{secrets.token_hex(24)}"
        client_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        hashed_key = generate_password_hash(client_hash, method="pbkdf2:sha256")

        admin = User(
            username=admin_username,
            password_hash=hashed_key,
            role="admin",
            alias_id=f"System-Root-{secrets.token_hex(3)}",
        )
        admin.set_demographics("Master", "Administrator", None, None, None)
        db.session.add(admin)
        db.session.commit()

        creds_path = os.path.join(
            os.path.dirname(backend_path), "admin_credentials.txt"
        )
        try:
            with open(creds_path, "w") as f:
                f.write("=" * 50 + "\n")
                f.write("      NAI COMPETITION SYSTEM ADMIN CREDENTIALS\n")
                f.write("=" * 50 + "\n")
                f.write(
                    f"Generated On   : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                )
                f.write(f"Admin Username : {admin_username}\n")
                f.write(f"Master Key     : {raw_key}\n\n")
                f.write("Keep this file secure. Enter these credentials on the\n")
                f.write("login page (Sign In as Administrator checkbox).\n")
                f.write("=" * 50 + "\n")
            saved_msg = f"Saved credentials to: {creds_path}"
        except Exception as e:
            saved_msg = f"Failed to save credentials file: {e}"

        print("\n" + "=" * 60)
        print("         MASTER ADMIN PROFILE GENERATOR ONLINE")
        print("=" * 60)
        print("  A secure administrator profile has been generated.")
        print("  Keep these credentials safe. Paste them to log in.")
        print(f"\n  Admin Username: \033[96m{admin_username}\033[0m")
        print(f"  Master Key:     \033[92m{raw_key}\033[0m")
        print(f"\n  {saved_msg}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    reset_and_create_admin()
