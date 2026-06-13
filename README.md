# NAI Web Platform

A secure, sandboxed, and real-time Natural Language Processing (NLP) / Machine Learning (ML) competition platform designed for participants to submit Python notebooks or code solutions and have them evaluated under strict environment and resource constraints.

---

## Key Features

1. **Sandboxed Container Logic**:
   - Automated `Dockerfile` generation based on task requirements (e.g., base images, APT packages, and pip dependencies).
   - Container execution with strict security parameters: memory limits (`-m`), no-network flags (`--network none`), process limitations (`--pids-limit 64`), and isolated volume mounts.
   - Custom GPU device visibilities for multi-GPU worker clusters.
   - **Image Caching Optimization**: Hashes container configurations (base image, apt packages, pip requirements) to tag images. If a matching image exists on the worker, the `docker build` check is skipped for instant container startup!

2. **Real-time Live Worker Status**:
   - Real-time display indicating whether worker clusters are live or offline (SSE-driven live state).
   - Prevents local host-worker loops by design, enforcing dedicated worker architecture.

3. **Decoupled Worker Architecture (No Remote DB Exposure)**:
   - Workers execute database-free (`RUNNING_AS_WORKER=true`). The database is kept local to the main server.
   - Task parameters are sent directly via Celery queue metadata, and worker reports status changes and final scores back to the main server via secure HTTPS REST API callbacks.
   - Workers download task dataset files dynamically on-demand from the main server using secure tokens.

4. **Deadline Fallback Strategy**:
   - Automatically detects late evaluations and falls back to selecting each user's highest-scoring validated submission when a competition ends if a worker cluster outage prevented deadline submissions from processing in time.

5. **Blind Jury Reviews**:
   - Encrypted demographics stored in PostgreSQL, only visible to administrators or after the leaderboard has been officially finalized.

---

## Project Structure

```bash
├── backend/                  # Flask API server & Celery Tasks
│   ├── app.py                # Server entry & seeding script
│   ├── config.py             # Config loader (dotenv-integrated)
│   ├── models.py             # SQLAlchemy schemas & field encryption
│   ├── tasks.py              # Celery tasks (Docker Sandbox builder & runner)
│   └── routes/               # API Blueprints (Auth, Admin, Submissions, Leaderboard)
├── frontend/                 # React UI + Vite
├── mock_bin/                 # Mock Docker CLI shim for execution testing
├── test_run.py               # E2E Integration Pipeline test suite
├── .env.example              # Configuration environment template
└── .env                      # Local environment configuration
```

---

## Configuration & Environment Setup

1. Copy the environment template to your local `.env`:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` and fill out the configuration values:
   - `DATABASE_URL`: Connection string for PostgreSQL (local to main server).
   - `CELERY_BROKER_URL` & `CELERY_RESULT_BACKEND`: Redis server broker URL (shared/authenticated).
   - `HF_CACHE_DIR`: Directory where Hugging Face datasets and models are cached.
   - `MAIN_SERVER_URL`: The HTTP URL of the main web platform API (needed for worker callbacks).
   - `WORKER_SECRET_KEY`: Secure shared token used to authorize worker callbacks and downloads (`X-Worker-Token` header).

---

## Running the Platform

### 1. Database & Broker
Ensure **PostgreSQL** and **Redis** services are running locally or remotely as configured in your `.env`.

### 2. Backend API Server
Activate your virtual environment and start the Flask development server:
```bash
source venv/bin/activate
python backend/app.py
```
*Note: The database seeds automatically with default challenges and test accounts on startup.*

### 3. Remote Worker node
Start the Celery worker node (supports Micromamba/Conda environments or Python `venv` automatically):
```bash
./start_worker.sh <REDIS_URL> [GPU_ID]
```

### 4. Frontend Dev Server
Navigate to the frontend directory, install dependencies, and start Vite:
```bash
cd frontend
npm install
npm run dev
```

---

## Integration Pipeline Testing

To test the entire pipeline (including database updates, SSE, Celery workers, and the Docker container sandbox execution logic) on any machine without needing a real Docker daemon active, execute:

```bash
python test_run.py
```

### How Container Verification Works Under the Test:
- The script prepends the `mock_bin/` directory to the `PATH`, activating our custom Docker CLI shim.
- It seeds a task specifying `base_docker_image`, `apt_packages`, `pip_requirements`, and memory limits.
- Spawns a background Celery worker, submits a task using `numpy`, and processes it.
- Asserts that all custom container parameters, volume mounts, network restrictions, and memory limitations were precisely configured in the backend and successfully passed to the Docker runner.
