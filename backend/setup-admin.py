import secrets

from app import create_app
from models import User, db
from utils.dates import utcnow
from werkzeug.security import generate_password_hash


def generate_master_key():
    app = create_app()
    with app.app_context():
        # Drop and recreate database to clean old runs
        print("Dropping all existing database tables...")  # noqa: T201
        try:
            db.session.execute(db.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Non-fatal error resetting schema: {e}. Falling back to drop_all...")  # noqa: T201
            db.drop_all()
        print("Recreating database tables...")  # noqa: T201
        db.create_all()

        # Generate random unique admin username (not standard "admin")
        admin_username = f"admin_{secrets.token_hex(4)}"

        # Generate cryptographically secure random master key
        raw_key = f"admin_key_{secrets.token_hex(24)}"

        # Compute direct PBKDF2 hash of the raw key
        hashed_key = generate_password_hash(raw_key, method="pbkdf2:sha256")

        # Remove any previous admin profiles to avoid credential residue
        User.query.filter_by(role="admin").delete()

        # Insert the master admin account
        admin = User(
            username=admin_username,
            password_hash=hashed_key,
            role="admin",
            alias_id=f"System-Root-{secrets.token_hex(3)}",
        )
        admin.set_demographics("Master", "Administrator", None, None, None)
        db.session.add(admin)
        db.session.commit()

        # Save credentials to a persistent text file in the workspace
        creds_path = "/app/admin_credentials.txt"
        try:
            with open(creds_path, "w") as f:
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
            saved_msg = f"Saved credentials to: {creds_path}"
        except Exception as e:
            saved_msg = f"Failed to save credentials file: {e!s}"

        print("\n" + "=" * 60)  # noqa: T201
        print("         MASTER ADMIN PROFILE GENERATOR ONLINE")  # noqa: T201
        print("=" * 60)  # noqa: T201
        print("  A secure administrator profile has been generated.")  # noqa: T201
        print("  Keep these credentials safe. Paste them to log in.")  # noqa: T201
        print("\n  Generated Admin Username:")  # noqa: T201
        print(f"  \033[96m{admin_username}\033[0m")  # noqa: T201
        print("  Generated Master Key:")  # noqa: T201
        print(f"  \033[92m{raw_key}\033[0m")  # noqa: T201
        print("\n  " + saved_msg)  # noqa: T201
        print("=" * 60 + "\n")  # noqa: T201


if __name__ == "__main__":
    generate_master_key()
