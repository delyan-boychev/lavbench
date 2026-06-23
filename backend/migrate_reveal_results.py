"""One-shot migration: replace 3 reveal flags with single reveal_results column.

Run once after updating models.py:
    cd backend && python migrate_reveal_results.py
"""

from app import create_app, db


def migrate():
    app = create_app()
    with app.app_context():
        with db.engine.connect() as conn:
            # Add new columns
            conn.execute(
                db.text(
                    "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS reveal_results BOOLEAN DEFAULT true NOT NULL"
                )
            )
            conn.execute(
                db.text(
                    "ALTER TABLE stages ADD COLUMN IF NOT EXISTS reveal_results BOOLEAN DEFAULT false NOT NULL"
                )
            )

            # Drop old columns from challenges
            for col in (
                "reveal_public_scores",
                "reveal_private_scores",
                "reveal_points",
            ):
                try:
                    conn.execute(
                        db.text(f"ALTER TABLE challenges DROP COLUMN IF EXISTS {col}")
                    )
                except Exception:
                    pass

            # Drop old columns from stages
            for col in ("reveal_public", "reveal_private", "reveal_points"):
                try:
                    conn.execute(
                        db.text(f"ALTER TABLE stages DROP COLUMN IF EXISTS {col}")
                    )
                except Exception:
                    pass

            conn.commit()
        print("Migration complete.")


if __name__ == "__main__":
    migrate()
