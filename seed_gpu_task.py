import os
import sys
import time
from datetime import datetime, timedelta
import json

# Add backend directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app import create_app
from models import db, Challenge, Task, User

app = create_app()
with app.app_context():
    # 1. Create the challenge
    challenge_title = "SMS Spam Neural Challenge"
    # Delete if exists
    existing_challenge = Challenge.query.filter_by(title=challenge_title).first()
    if existing_challenge:
        print(f"Deleting existing challenge: {challenge_title}")
        db.session.delete(existing_challenge)
        db.session.commit()

    start_time = datetime.utcnow()
    # End time tomorrow 23:59:00 UTC
    end_time = (datetime.utcnow() + timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)

    challenge = Challenge(
        title=challenge_title,
        description="Classify SMS messages into spam or ham using deep learning models on GPU.",
        metric_name="accuracy",
        max_eval_requests=10,
        ram_limit_mb=8192,
        time_limit_sec=300,
        gpu_required=True,
        is_active=True,
        start_time=start_time,
        end_time=end_time
    )
    db.session.add(challenge)
    db.session.commit()

    # 2. Create the task
    task_desc = """Create a Python function `predict_gpu(messages)` that utilizes PyTorch and CUDA to classify SMS messages.

Your function must run tensor operations on the GPU and return predictions (`1` for spam, `0` for ham).

### Example:
```python
# SUBMIT
import torch

def predict_gpu(messages):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # Your GPU-accelerated model logic here
    return [0] * len(messages)
```"""

    eval_script = """import os
import json
import traceback
import time

# 1. SECURE IMPORT
try:
    import submission_runner
except Exception as e:
    with open("eval_results.json", "w") as f:
        json.dump({"status": "error", "error": "Failed to compile or import student code."}, f)
    exit(1)

def run_evaluation():
    try:
        # 2. VALIDATE GPU & TORCH
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("GPU/CUDA is not available inside the execution container, but was required!")

        # Private evaluation dataset
        test_messages = [
            "Congratulations! You've won a free ticket to the Bahamas. Text WIN to 55555.",
            "Hey, are we still meeting for lunch today at 12:30?",
            "URGENT: Your account has been suspended. Log in at http://fake-bank.com immediately.",
            "Can you pick up some milk on your way home?",
            "Winner! You have been selected for a $1000 gift card. Claim now."
        ]
        test_labels = [1, 0, 1, 0, 1]

        # 3. RUN STUDENT LOGIC
        if not hasattr(submission_runner, 'predict_gpu'):
            raise AttributeError("Your notebook must define a function 'predict_gpu(messages)' that takes a list of SMS messages.")
            
        student_func = submission_runner.predict_gpu

        start_time = time.time()
        preds = student_func(test_messages)
        execution_time_ms = int((time.time() - start_time) * 1000)

        if len(preds) != len(test_labels):
            raise ValueError(f"predict_gpu returned {len(preds)} predictions, but expected {len(test_labels)}.")

        correct = sum(1 for p, l in zip(preds, test_labels) if p == l)
        accuracy = correct / len(test_labels)

        # 4. WRITE SECURE RESULTS (Do not print to stdout)
        results = {
            "status": "success",
            "public_score": float(accuracy),
            "private_score": float(accuracy),
            "execution_time_ms": execution_time_ms,
            "metrics_payload_public": {"accuracy": accuracy},
            "metrics_payload_private": {"accuracy": accuracy}
        }
        
        with open("eval_results.json", "w") as f:
            json.dump(results, f)
            
    except Exception as e:
        # 5. PREVENT DATA LEAKAGE
        error_type = type(e).__name__
        error_msg = str(e)
        with open("eval_results.json", "w") as f:
            json.dump({"status": "error", "error": f"Evaluation failed with {error_type}: {error_msg}"}, f)

if __name__ == "__main__":
    run_evaluation()"""

    task = Task(
        challenge_id=challenge.id,
        title="SMS Spam Neural Detector (GPU)",
        description=task_desc,
        custom_eval_code=eval_script,
        ram_limit_mb=8192,
        time_limit_sec=300,
        gpu_required=True,
        base_docker_image="pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime",
        require_submit_tag=True,
        ban_magic_commands=True,
        banned_imports="os,sys,subprocess,socket",
        public_eval_percentage=40,
        files="[]"
    )
    db.session.add(task)
    db.session.commit()

    # Create task directory on disk and write the evaluator.py file
    task_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], f"task_{task.id}")
    os.makedirs(task_upload_dir, exist_ok=True)
    save_path = os.path.join(task_upload_dir, "evaluator.py")
    with open(save_path, "w") as f:
        f.write(eval_script)

    task.evaluator_script_path = save_path
    db.session.commit()

    print(f"Created task: '{task.title}' with ID: {task.id}")

    # 3. Associate competitor user (comp1) with the new challenge so they can test it
    comp_user = User.query.filter_by(username="comp1").first()
    if comp_user:
        comp_user.challenge_id = challenge.id
        db.session.commit()
        print(f"Associated user '{comp_user.username}' with new challenge '{challenge.title}'")
    else:
        print("Warning: competitor user 'comp1' not found, skipping association")

    print("Seeding completed successfully!")
