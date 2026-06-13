import os
import sys
import time
import json
import subprocess
import shutil

# 1. Setup environment to use our mock docker CLI first!
MOCK_BIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mock_bin'))
os.environ["PATH"] = f"{MOCK_BIN_DIR}{os.path.pathsep}{os.environ.get('PATH', '')}"

# Add backend directory to sys.path to resolve imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from routes.tasks import calculate_submission_priority

MOCK_LOG_PATH = "/Users/delyan-boychev/nai-webplatform/mock_docker_run.log"

def print_banner(text):
    print("\n" + "=" * 60)
    print(f"   {text}")
    print("=" * 60)

def main():
    print_banner("INTEGRITY PIPELINE & CONTAINER LOGIC TEST")

    # Clear previous mock docker logs if any
    if os.path.exists(MOCK_LOG_PATH):
        os.remove(MOCK_LOG_PATH)

    # 1. Check Redis availability
    print("--> Checking Redis broker status...")
    try:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379/0")
        r.ping()
        print("    [OK] Redis broker is online.")
    except Exception as e:
        print(f"    [ERROR] Redis broker is offline or not installed: {e}")
        print("    Please start Redis and run this script again.")
        sys.exit(1)

    # 2. Check Docker availability (should invoke our mock docker CLI)
    print("--> Checking Docker CLI status...")
    docker_available = False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if res.returncode == 0 and "Mocked Docker" in res.stdout:
            docker_available = True
            print("    [OK] Mock Docker CLI wrapper is correctly active in PATH.")
        else:
            print(f"    [WARNING] 'docker info' output did not match mock: {res.stdout}")
    except FileNotFoundError:
        print("    [ERROR] 'docker' command not found in PATH after prepending mock_bin.")
        sys.exit(1)
        
    if not docker_available:
        print("\n    [ERROR] Mock Docker is required to verify container sandbox logic.")
        sys.exit(1)

    # 3. Initialize Flask App Context
    app = create_app()
    app_context = app.app_context()
    app_context.push()

    # Create tables if they do not exist
    db.create_all()

    # 4. Clean up any previous test remnants
    print("--> Cleaning up previous test records...")
    test_challenges = Challenge.query.filter_by(title="Integrity Pipeline Container Test").all()
    for tc in test_challenges:
        Submission.query.filter_by(challenge_id=tc.id).delete()
        Task.query.filter_by(challenge_id=tc.id).delete()
        db.session.delete(tc)
    User.query.filter_by(username="container_tester").delete()
    db.session.commit()

    # 5. Programmatically seed Test Data with container specifications
    print("--> Seeding test challenge and container task...")
    challenge = Challenge(
        title="Integrity Pipeline Container Test",
        description="A validation challenge for container build and sandbox execution logic.",
        max_eval_requests=10,
        metric_name="accuracy"
    )
    db.session.add(challenge)
    db.session.commit()

    # Create task upload directory
    task_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], "task_test_container")
    os.makedirs(task_upload_dir, exist_ok=True)

    # Write a custom evaluator script
    evaluator_content = """import json
import sys

# Import the user's predict function from submission_runner
try:
    from submission_runner import predict
except ImportError:
    print(json.dumps({"status": "error", "error": "Could not import predict function."}))
    sys.exit(1)

try:
    inputs = ["input_A", "input_B"]
    preds = predict(inputs)
    
    if len(preds) != len(inputs):
        raise ValueError("Predictions length mismatch.")
        
    # Correct predictions should be [1, 1]
    correct = sum(1 for p in preds if p == 1)
    acc = correct / len(inputs)
    
    print(json.dumps({
        "status": "success",
        "public_score": acc,
        "private_score": acc,
        "metrics_payload_public": {"accuracy": acc},
        "metrics_payload_private": {"accuracy": acc},
        "execution_time_ms": 15
    }))
except Exception as e:
    print(json.dumps({"status": "error", "error": str(e)}))
"""
    evaluator_path = os.path.join(task_upload_dir, "evaluator.py")
    with open(evaluator_path, "w") as f:
        f.write(evaluator_content)

    # Note container task specifications!
    task = Task(
        challenge_id=challenge.id,
        title="Container Verification Task",
        description="Solve this task using a predict function using numpy.",
        ram_limit_mb=2048,
        time_limit_sec=15,
        gpu_required=False,
        files="[]",
        evaluator_script_path=evaluator_path,
        public_eval_percentage=50,
        # Container Settings
        base_docker_image="python:3.10-slim",
        apt_packages="curl, htop",
        pip_requirements="numpy>=1.20.0"
    )
    db.session.add(task)

    tester = User(
        username="container_tester",
        password_hash="pbkdf2:sha256:...",
        role="competitor",
        alias_id="Container-Tester-Robot"
    )
    db.session.add(tester)
    db.session.commit()
    print(f"    [OK] Seeded Challenge #{challenge.id}, Task #{task.id}, and User #{tester.id}.")

    # 6. Start Local Celery Worker node in background
    print("--> Starting Celery worker process locally...")
    worker_log = open("backend/celery_test_run.log", "w")
    celery_cmd = [sys.executable, "-m", "celery", "-A", "tasks.celery", "worker", "--loglevel=info"]
    worker_proc = subprocess.Popen(
        celery_cmd,
        cwd="backend",
        stdout=worker_log,
        stderr=worker_log,
        env=os.environ.copy() # Inherits PATH containing mock_bin/
    )

    # Wait for worker to connect and show online status
    print("    Waiting for worker to come online (polling /api/worker-status)...")
    worker_online = False
    for _ in range(15):
        time.sleep(1.5)
        from tasks import celery
        try:
            inspect = celery.control.inspect(timeout=0.5)
            ping_res = inspect.ping()
            if ping_res and len(ping_res) > 0:
                worker_online = True
                print("    [OK] Worker is online and connected to Redis!")
                break
        except Exception:
            pass
            
    if not worker_online:
        print("    [ERROR] Celery worker failed to start or connect to Redis within 20s.")
        print("    Check backend/celery_test_run.log for logs.")
        worker_proc.terminate()
        sys.exit(1)

    # 7. Submit code cell solution using numpy
    print("--> Creating submission...")
    solution_code = [
        "# SUBMIT",
        "import numpy as np",
        "def predict(inputs):",
        "    # Correct pipeline solution returning list of ones using numpy",
        "    arr = np.ones(len(inputs))",
        "    return arr.tolist()"
    ]
    
    submission = Submission(
        user_id=tester.id,
        challenge_id=challenge.id,
        task_id=task.id,
        status="queued",
        detailed_status="queued",
        code_cells=json.dumps(solution_code)
    )
    db.session.add(submission)
    db.session.commit()
    print(f"    [OK] Submission #{submission.id} created.")

    # 8. Trigger Celery Task asynchronously
    print("--> Dispatching Celery task...")
    from tasks import evaluate_submission
    priority = calculate_submission_priority(tester.id, "competitor")
    evaluate_submission.apply_async(args=[submission.id], priority=priority)

    # 9. Monitor DB status transitions in real-time
    print("--> Monitoring status transitions (polling database)...")
    last_status = None
    last_detailed = None
    start_time = time.time()
    success = False

    while time.time() - start_time < 35:
        time.sleep(0.5)
        db.session.expire_all()
        sub = db.session.get(Submission, submission.id)
        
        if sub.status != last_status or sub.detailed_status != last_detailed:
            last_status = sub.status
            last_detailed = sub.detailed_status
            print(f"    [Status Update] main_status: {last_status.upper()} | detailed_status: {last_detailed.upper()}")

        if sub.status in ["completed", "failed"]:
            if sub.status == "completed" and sub.public_score == 1.0:
                success = True
            break

    # 10. Print Results & Assertions
    sub = db.session.get(Submission, submission.id)
    print_banner("Test Evaluation Results")
    print(f"Final Status:     {sub.status.upper()}")
    print(f"Detailed Status: {sub.detailed_status.upper()}")
    print(f"Public Score:    {sub.public_score}")
    print(f"Private Score:   {sub.private_score}")
    print(f"Execution Time:  {sub.execution_time_ms} ms")
    print(f"Sandbox Node:    {sub.gpu_node}")
    print("\n--- Sandbox Execution Logs ---")
    print(sub.logs or "[No logs written]")
    print("-" * 30)

    # 11. Read and parse mock docker logs to fully assert all container settings
    print("\n--> Verifying detailed container sandbox configuration logs...")
    container_assertions_passed = True
    
    if not os.path.exists(MOCK_LOG_PATH):
        print("    [FAILED] No mock docker logs were generated. Sandbox did not execute container path!")
        container_assertions_passed = False
    else:
        build_events = []
        run_events = []
        with open(MOCK_LOG_PATH, "r") as f:
            for line in f:
                try:
                    event = json.loads(line)
                    if event["event"] == "build":
                        build_events.append(event["details"])
                    elif event["event"] == "run":
                        run_events.append(event["details"])
                except Exception as e:
                    print(f"    [WARNING] Error parsing log line: {e}")

        # Assert build event
        if not build_events:
            print("    [FAILED] No 'build' event recorded by mock docker.")
            container_assertions_passed = False
        else:
            build = build_events[0]
            print(f"    [OK] Captured Docker image build request for tag: '{build.get('tag')}'")
            
            # Check Dockerfile contents
            dockerfile = build.get("dockerfile", "")
            if "FROM python:3.10-slim" in dockerfile:
                print(f"    [OK] Dockerfile base image correctly set to 'python:3.10-slim'")
            else:
                print(f"    [FAILED] Dockerfile base image incorrect: {dockerfile}")
                container_assertions_passed = False
            if "curl" in dockerfile and "htop" in dockerfile:
                print("    [OK] Dockerfile APT packages correctly installed: 'curl, htop'")
            else:
                print(f"    [FAILED] Dockerfile APT packages missing: {dockerfile}")
                container_assertions_passed = False
                
            requirements = build.get("requirements", "")
            if "numpy>=1.20.0" in requirements:
                print("    [OK] Dockerfile pip requirements correctly installed: 'numpy>=1.20.0'")
            else:
                print(f"    [FAILED] Dockerfile pip requirements missing or incorrect: {requirements}")
                container_assertions_passed = False

        # Assert run event
        if not run_events:
            print("    [FAILED] No 'run' event recorded by mock docker.")
            container_assertions_passed = False
        else:
            run = run_events[0]
            print(f"    [OK] Captured Docker run request for tag: '{run.get('image_tag')}'")
            
            # Check sandbox constraints
            if run.get("memory") == "2048m":
                print("    [OK] Sandbox RAM limit correctly set to '2048m'")
            else:
                print(f"    [FAILED] Sandbox RAM limit incorrect: {run.get('memory')}")
                container_assertions_passed = False
                
            if run.get("network") == "none":
                print("    [OK] Sandbox network disabled correctly (--network none)")
            else:
                print(f"    [FAILED] Sandbox network not disabled: {run.get('network')}")
                container_assertions_passed = False
                
            if run.get("pids_limit") == "64":
                print("    [OK] Sandbox PIDs limit set to '64'")
            else:
                print(f"    [FAILED] Sandbox PIDs limit incorrect: {run.get('pids_limit')}")
                container_assertions_passed = False
                
            if run.get("tmpfs") == "/tmp":
                print("    [OK] Sandbox /tmp tmpfs mount enabled")
            else:
                print(f"    [FAILED] Sandbox tmpfs mount missing: {run.get('tmpfs')}")
                container_assertions_passed = False

    # 12. Terminate Celery Worker
    print("\n--> Terminating Celery worker process...")
    worker_proc.terminate()
    try:
        worker_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        worker_proc.kill()
    worker_log.close()

    # 13. Tear Down Database records and directories
    print("--> Cleaning up test files and database records...")
    db.session.delete(sub)
    db.session.delete(task)
    db.session.delete(challenge)
    db.session.delete(tester)
    db.session.commit()
    app_context.pop()

    shutil.rmtree(task_upload_dir, ignore_errors=True)
    if os.path.exists("backend/celery_test_run.log"):
        os.remove("backend/celery_test_run.log")
    if os.path.exists(MOCK_LOG_PATH):
        os.remove(MOCK_LOG_PATH)

    if success and container_assertions_passed:
        print("\n[SUCCESS] Pipeline and Docker Container logic tests passed perfectly!")
        sys.exit(0)
    else:
        print("\n[FAILURE] Integration tests failed. Check logs above.")
        sys.exit(1)

if __name__ == '__main__':
    main()
