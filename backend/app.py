import os
import json
from datetime import datetime, timedelta
from flask import Flask
from flask_cors import CORS
from models import db, User, Challenge, Submission, Task
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    db.init_app(app)
    
    # Register Service Blueprints
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.challenges import challenges_bp
    from routes.submissions import submissions_bp
    from routes.leaderboard import leaderboard_bp
    from routes.tasks import tasks_bp
    from routes.docs import docs_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(challenges_bp, url_prefix='/api/challenges')
    app.register_blueprint(submissions_bp, url_prefix='/api')
    app.register_blueprint(leaderboard_bp, url_prefix='/api')
    app.register_blueprint(tasks_bp, url_prefix='/api')
    app.register_blueprint(docs_bp, url_prefix='/api/docs')
    
    return app

app = create_app()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5001, debug=True)
