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
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(challenges_bp, url_prefix='/api/challenges')
    app.register_blueprint(submissions_bp, url_prefix='/api')
    app.register_blueprint(leaderboard_bp, url_prefix='/api')
    app.register_blueprint(tasks_bp, url_prefix='/api')
    
    return app

app = create_app()

# --- SEEDING METHOD ON STARTUP ---
def seed_database():
    db.create_all()
    
    # Check if we already have challenges
    if Challenge.query.first():
        return
        
    print("Seeding database with default challenges, tasks, users, and completed runs...")
    
    # Helper to hash seed passwords
    import hashlib
    from werkzeug.security import generate_password_hash
    def sha256_hash(text):
        return hashlib.sha256(text.encode()).hexdigest()

    # 1. Create Challenges
    imdb_challenge = Challenge(
        title="IMDb Movie Sentiment Classification",
        description="Predict whether movie reviews from the IMDb dataset are positive or negative. The submissions will execute inside our container and access the test split.",
        hf_dataset_path="imdb",
        hf_dataset_config="",
        hf_dataset_split="test",
        metric_name="accuracy",
        max_eval_requests=10,
        ram_limit_mb=8192,
        time_limit_sec=300,
        gpu_required=True
    )
    
    sst2_challenge = Challenge(
        title="SST-2 Sentence Classification (GLUE)",
        description="Predict the sentiment of sentences extracted from movie reviews in the Stanford Sentiment Treebank. Evaluated using Accuracy on the validation split.",
        hf_dataset_path="glue",
        hf_dataset_config="sst2",
        hf_dataset_split="validation",
        metric_name="accuracy",
        max_eval_requests=5,
        ram_limit_mb=4096,
        time_limit_sec=150,
        gpu_required=False
    )
    db.session.add_all([imdb_challenge, sst2_challenge])
    db.session.commit()

    # 2. Create Tasks for Challenges
    imdb_eval_code = """import json
import sys
import traceback

# Mock evaluation dataset
test_inputs = [
    "This movie was absolutely wonderful and the acting was top notch!",
    "A complete waste of time. The plot made no sense and it was very boring.",
    "I loved the cinematography, but the pacing was a bit slow. Still enjoyed it.",
    "Terrible film. I would not recommend it to anyone.",
    "An average watch. Nothing special but not bad either."
]
test_labels = [1, 0, 1, 0, 1]

try:
    if 'predict' not in globals():
        raise AttributeError("Your code must define a function 'predict(inputs_list)' that takes a list of reviews and returns predictions (0 or 1).")
        
    preds = predict(test_inputs)
    if len(preds) != len(test_labels):
        raise ValueError(f"predict returned {len(preds)} predictions, but expected {len(test_labels)}.")
        
    correct = sum(1 for p, l in zip(preds, test_labels) if p == l)
    acc = correct / len(test_labels)
    
    # Print structured JSON results
    print(json.dumps({
        "status": "success",
        "public_score": acc,
        "private_score": acc,
        "execution_time_ms": 10
    }))
except Exception as e:
    print(json.dumps({
        "status": "error",
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
"""

    task1 = Task(
        challenge_id=imdb_challenge.id,
        title="Task 1: Basic Lexicon Classifier",
        description="Write a Python script defining a function `predict(inputs_list)` that classifies IMDb reviews. Start with a simple list-based dictionary classifier.",
        custom_eval_code=imdb_eval_code,
        files="[]"
    )

    task2 = Task(
        challenge_id=imdb_challenge.id,
        title="Task 2: Advanced Substring Classifier",
        description="Improve your lexicon classifier by matching substrings and word shapes to handle negation words (e.g. 'not good').",
        custom_eval_code=imdb_eval_code,
        files="[]"
    )

    task_sst = Task(
        challenge_id=sst2_challenge.id,
        title="Task 1: SST-2 Binary Sentence Classification",
        description="Define a function `predict(inputs_list)` for the SST-2 sentiment task. Sentences are shorter and may require nuanced matching.",
        custom_eval_code=imdb_eval_code,
        files="[]"
    )

    db.session.add_all([task1, task2, task_sst])
    db.session.commit()

    # 3. Create Users
    jury = User(
        username="jury",
        email="jury@competition.ai",
        password_hash=generate_password_hash(sha256_hash("jury123"), method='pbkdf2:sha256'),
        role="jury",
        alias_id="Jury-Oracle-101"
    )
    jury.set_demographics("Dr. Sarah", "Connor", None, None, None)
    
    comp1 = User(
        username="comp1",
        email="comp1@competition.ai",
        password_hash=generate_password_hash(sha256_hash("comp123"), method='pbkdf2:sha256'),
        role="competitor",
        alias_id="Quantum-Falcon-402",
        challenge_id=imdb_challenge.id
    )
    comp1.set_demographics("Alice", "Lovelace", "11", "AI High", "Sofia")
    
    comp2 = User(
        username="comp2",
        email="comp2@competition.ai",
        password_hash=generate_password_hash(sha256_hash("comp223"), method='pbkdf2:sha256'),
        role="competitor",
        alias_id="Cyber-Eclipse-712",
        challenge_id=imdb_challenge.id
    )
    comp2.set_demographics("Bob", "Turing", "12", "Turing Academy", "Varna")
    
    db.session.add_all([jury, comp1, comp2])
    db.session.commit()
    
    # 4. Create mock submissions associated with tasks
    sub1 = Submission(
        user_id=comp1.id,
        challenge_id=imdb_challenge.id,
        task_id=task1.id,
        status="completed",
        code_cells=json.dumps([
            "def predict(inputs):\n    # Simple lexicon heuristic\n    positives = {'good', 'great', 'love', 'amazing', 'excellent', 'wonderful'}\n    preds = []\n    for text in inputs:\n        words = set(text.lower().split())\n        score = len(words.intersection(positives))\n        preds.append(1 if score > 0 else 0)\n    return preds"
        ]),
        public_score=0.80,
        private_score=0.80,
        logs="--- Starting execution ---\nModel loaded successfully.\nEvaluated public split: 0.80\nEvaluated private split: 0.80",
        gpu_node="gpu-worker-0",
        execution_time_ms=10,
        created_at=datetime.utcnow() - timedelta(hours=3),
        executed_at=datetime.utcnow() - timedelta(hours=2, minutes=58)
    )
    
    sub2 = Submission(
        user_id=comp2.id,
        challenge_id=imdb_challenge.id,
        task_id=task1.id,
        status="completed",
        code_cells=json.dumps([
            "def predict(inputs):\n    # Sentiment analysis mock model\n    pos = {'good', 'great', 'love', 'amazing', 'excellent', 'wonderful', 'like', 'best', 'funny', 'happy'}\n    neg = {'bad', 'worst', 'hate', 'boring', 'waste', 'terrible', 'awful'}\n    preds = []\n    for text in inputs:\n        words = set(text.lower().split())\n        p_count = len(words.intersection(pos))\n        n_count = len(words.intersection(neg))\n        preds.append(1 if p_count >= n_count else 0)\n    return preds"
        ]),
        public_score=0.60,
        private_score=0.60,
        logs="--- Starting execution ---\nModel loaded successfully.\nEvaluated public split: 0.60\nEvaluated private split: 0.60",
        gpu_node="gpu-worker-1",
        execution_time_ms=10,
        created_at=datetime.utcnow() - timedelta(hours=2),
        executed_at=datetime.utcnow() - timedelta(hours=1, minutes=58)
    )
    
    sub3 = Submission(
        user_id=comp1.id,
        challenge_id=imdb_challenge.id,
        task_id=task1.id,
        status="failed",
        code_cells=json.dumps([
            "def predict(inputs):\n    return 1 / 0"
        ]),
        logs="--- Starting execution ---\nAn error occurred:\nTraceback (most recent call last):\n  File \"submission_runner.py\", line 17, in run_evaluation\n    preds = predict(test_inputs)\n  File \"<string>\", line 2, in predict\nZeroDivisionError: division by zero",
        gpu_node="gpu-worker-0",
        execution_time_ms=10,
        created_at=datetime.utcnow() - timedelta(minutes=45),
        executed_at=datetime.utcnow() - timedelta(minutes=44)
    )
    
    db.session.add_all([sub1, sub2, sub3])
    db.session.commit()
    print("Database seeding completed.")

if __name__ == '__main__':
    with app.app_context():
        seed_database()
    app.run(host='0.0.0.0', port=5001, debug=True)
