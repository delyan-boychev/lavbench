import os
import sys

# Ensure backend directory is in the path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import create_app
from models import db

app = create_app()
with app.app_context():
    print("Dropping all existing database tables...")
    db.drop_all()
    print("Re-creating all database tables...")
    db.create_all()
    print("Database reset successfully! No seed data created.")
