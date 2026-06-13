# National AI Competition (NAI) Web Platform

A secure, sandboxed, and real-time Natural Language Processing (NLP) / Machine Learning (ML) competition platform. Participants submit Jupyter Notebooks or raw Python code solutions, which are executed and evaluated inside isolated GPU/CPU container sandboxes under strict resource constraints.

---

## System Architecture

The NAI platform utilizes a decoupled, database-free worker node architecture:

```mermaid
graph TD
    Client[React Frontend] <-->|HTTP / SSE| Server[Flask API Server]
    Server <-->|PostgreSQL| DB[(Local DB)]
    Server <-->|Celery Queue| Broker[(Redis Broker)]
    Broker <-->|Task Metadata| Worker[Remote GPU/CPU Worker]
    Worker -->|Dynamic Download API| Server
    Worker -->|Secure HTTPS Score Report Callback| Server
```

- **Main Server**: Houses the database (PostgreSQL), the task coordinator (Flask), the front-end interface, and the Redis Celery broker.
- **Worker Nodes**: Decoupled, database-free worker machines (`RUNNING_AS_WORKER=true`). They listen to Celery queues (CPU or GPU), dynamically download task files from the main server via secure tokens, build/cache task containers, execute user code inside resource-limited Docker sandboxes, and callback scores over secure APIs.

---

## Configuration & Environment

Configuration is managed via `.env` in the root directory. Copy the template to start:

```bash
cp .env.example .env
```

### Key Environment Variables

| Variable | Description | Location / Default |
| :--- | :--- | :--- |
| `SECRET_KEY` | Flask API security key | `nai-super-secret-key-1337-secure-random-length-for-jwt` |
| `FIELD_ENCRYPTION_KEY` | AES key for encrypting competitor demographics | Generated on setup |
| `DATABASE_URL` | SQLAlchemy database url (PostgreSQL) | `postgresql://nai_user:nai_pass@localhost:5432/nai_competition` |
| `CELERY_BROKER_URL` | Redis Broker connection string | `redis://localhost:6379/0` |
| `MAIN_SERVER_URL` | HTTP endpoint of Main Server (for worker callbacks) | `http://127.0.0.1:5001` |
| `WORKER_SECRET_KEY` | Shared token for worker download/report headers | Shared across server + workers |
| `HF_CACHE_DIR` | Cache directory for datasets and models | `backend/hf_cache/` |

---

## Setup & Local Debugging

If you want to run the platform locally in debug mode on a single developer machine, you can run all services using our host-level debugging runner.

### Quick Start (All-in-one Debug Script)

We provide a comprehensive debug script [deploy_debug.sh](./deploy_debug.sh) that:
1. Prepares a local Python virtualenv and installs dependencies.
2. Checks for local PostgreSQL and Redis services (and automatically starts them in Docker if they aren't running natively).
3. Creates and seeds the database schemas.
4. Spawns the Flask API server, a local Celery worker (logs to `backend/celery.log`), and the Vite development server.

Run it in your shell:
```bash
chmod +x deploy_debug.sh
./deploy_debug.sh
```
*To terminate all running background services, simply press `Ctrl + C`.*

### Manual Step-by-Step Local Setup

If you prefer launching each layer individually:

1. **Start Infrastructure**:
   Ensure PostgreSQL and Redis are running locally.
2. **Backend Setup**:
   ```bash
   cd backend
   
   # Using Micromamba (Recommended):
   micromamba create -n nai_backend python=3.10 -y
   micromamba activate nai_backend
   pip install -r requirements.txt
   
   # Or using standard python virtual environment (Python 3.10 recommended):
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   
   # Setup database schemas & seed default challenges/users
   python -c "from app import app, db, seed_database; with app.app_context(): db.create_all(); seed_database()"
   
   # Start Flask Dev Server (Port 5001)
   python app.py
   ```

   #### Managing Python Dependencies
   The backend dependencies are specified in `backend/requirements.in` and compiled into `backend/requirements.txt` using `pip-compile`.
   * **To modify dependencies**: Edit [backend/requirements.in](./backend/requirements.in).
   * **To re-compile dependencies**: Run the compile command manually:
     ```bash
     micromamba run -n nai_backend pip-compile backend/requirements.in --output-file backend/requirements.txt
     ```

3. **Celery Worker Setup**:
   With your virtualenv active, run:
   ```bash
   cd backend
   celery -A tasks.celery worker --loglevel=info
   ```
4. **Frontend Setup**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

---

## Docker Deployment (Production Compose)

To run the entire platform isolated in production-grade Docker containers (Frontend, Backend API, PostgreSQL database, Redis broker, and Celery Worker node):

We provide a deployment script [deploy_docker.sh](./deploy_docker.sh). Execute:
```bash
chmod +x deploy_docker.sh
./deploy_docker.sh
```

This script automates:
- Tearing down any active container configurations (`docker-compose down`).
- Rebuilding the application images (`docker-compose build`).
- Starting the PostgreSQL database and waiting for it to be fully online (`pg_isready`).
- Launching the Flask API, the React/Nginx frontend, and the Celery worker node.
- Seeding the database inside the container context.

### Useful Commands:
* **View logs**: `docker-compose logs -f`
* **Stop services**: `docker-compose down`

---

## Remote GPU / CPU Worker Setup

Worker nodes execute in a decoupled model and **do not require direct database access**.

### Prerequisites:
- **Docker** must be installed and running on the worker machine.
- If GPU support is required, **NVIDIA Container Toolkit** must be installed.
- Access to the shared **Redis Broker** port (typically `6379`) configured on the main server.

### Worker Initialization Flow ([start_worker.sh](./start_worker.sh))
The startup script handles worker activation:
1. Disables direct database access checks (`RUNNING_AS_WORKER="true"`).
2. Configures GPU visibilities and links queue channels.
3. Automatically sets up the execution context:
   - **Micromamba / Conda**: If `micromamba` is detected on the system path, it automatically creates a dedicated environment named `nai_worker` with Python 3.10 and installs dependencies.
   - **Virtualenv Fallback**: If micromamba is not available, it attempts to find and activate a local virtualenv (`venv`).

### Running the Worker:
```bash
chmod +x start_worker.sh
./start_worker.sh <REDIS_URL> [GPU_ID]
```

#### Examples:
* **GPU Worker 0**:
  ```bash
  ./start_worker.sh redis://:broker_password@main-server-ip:6379/0 0
  ```
  *(This binds the worker to NVIDIA GPU `0` and listens on the `gpu_queue` queue).*
* **CPU-Only Worker**:
  ```bash
  ./start_worker.sh redis://:broker_password@main-server-ip:6379/0
  ```
  *(This runs the worker in CPU-only mode, listening on the default `celery` queue).*

---

## Testing & Debugging

The platform features comprehensive frontend and backend unit test suites.

### 1. Frontend Unit Tests (Vitest + Testing Library)
Run the React component test suite:
```bash
cd frontend
npm run test
```
*This validates all forms, validations (such as `.ipynb` uploads, cell checkboxes, and empty submissions), formatters (bytes-to-MB calculations), mock routers, and page layouts (blind review columns, theme toggles, and live status badge indicators).*

### 2. Backend Unit Tests (Python unittest)
Run the Python route and exception test suite inside your virtualenv:
```bash
cd backend
python -m unittest discover -s tests
```
*This discover tool executes all happy-path tests, rate-limiting limits, calendar deadline constraints, AST sandbox rule checks (magic command bans, blocked imports), and API endpoint exception paths (missing payloads, 401 unauths, and 403 access blocks).*

### 3. Pipeline Integration Testing ([test_run.py](./test_run.py))
To test the entire pipeline (including database updates, SSE, Celery workers, and the Docker container sandbox execution logic) on any machine without needing a real Docker daemon active, execute:
```bash
python test_run.py
```
- **How it works**: The script prepends the `mock_bin/` directory to the `PATH`, activating our custom Docker CLI shim. It builds a dummy task container, runs user code, and verifies that resource limitations (RAM memory limit, process limit, and network lockouts) are verified and logged correctly.
