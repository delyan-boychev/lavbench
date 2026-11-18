# LavBench System Architecture & Infrastructure

## 1. System Overview

```text
Browser (React SPA) ──> Nginx (Port 80 / 443, HTTP(S) / SSE Reverse Proxy)
                            ├── Flask API Server (Port 5001, Gunicorn + gevent)
                            │     ├── PostgreSQL 15 (Primary Database)
                            │     ├── Redis (Celery Broker + Coordination: SSE pub/sub fan-out, worker_spec registry, submission fallback key, versioned leaderboard invalidations, dead-letter queue, GPU/build locks)
                            │     ├── Redis Cache (Private, server-only: leaderboard caches, locks, rate-limit counters, JWT blacklist — CACHE_REDIS_URL never given to external workers)
                            │     ├── Celery Beat (Periodic Scheduler: Backups, Watchdog)
                            │     └── Internal Celery Worker (System tasks only, inside Docker Compose, -Q celery,internal)
                            └── Remote Execution Workers (Celery evaluation-only workers: Docker container or host, consume cpu_queue, plus gpu_queue on GPU hosts)
                                  └── Sibling Sandbox Containers (--network none, --read-only, --cap-drop ALL)
```

---

## 2. Component Technology Stack

| Component | Technology | Role & Key Responsibilities |
| :--- | :--- | :--- |
| **Frontend** | React 19 + Vite + Vanilla/Tailwind CSS | SPA with SSE live updates, i18n (en/bg), JSDoc `@type` validation (`tsc --noEmit`). |
| **API Server** | Flask 3.1 + Gunicorn + gevent + spectree | REST API endpoints, Pydantic v2 request/response validation, SSE event streaming. |
| **Primary Database** | PostgreSQL 15 | Users, challenges, stages, tasks, submissions, audit logs (`AuditLog`). |
| **Cache & Broker** | Redis | Celery task broker + **coordination client** for all cross-machine shared state: SSE pub/sub fan-out, worker spec registry (`worker_spec:<hostname>`), submission fallback key, versioned leaderboard invalidations, dead-letter queue, GPU/build locks, distributed locks (submit, leaderboard), rate-limit counters, login failures, JWT revocations and backup markers. AOF persistence and `noeviction` protect queued work and these guarantees. |
| **Dedicated Cache** | Redis (DB 1, `volatile-lru`, no persistence) | Private, server-only cache for recomputable data: leaderboard and status caches, SSE log replay lists and submission status (`CACHE_REDIS_URL`). When full it evicts the least recently used keys that have a TTL, so nothing stored here may be needed for correctness. Internal container — no host port; external workers never receive this URL. |
| **Task Queue** | Celery 5.4 | Asynchronous job execution (submission evaluation, image compilation, database backups). |
| **Scheduler** | Celery Beat | Periodic tasks (watchdog for stuck submissions, automated backup schedule). |
| **Worker Nodes** | Celery Evaluation Worker | **Evaluation-only** workers consuming `cpu_queue`, and also `gpu_queue` on hosts with a GPU; run competitor code in sibling Docker sandbox containers (`deploy-worker.sh` / `worker.env`). |

### Database Migration Lifecycle

In Docker Compose, the one-shot `migrate` service waits for healthy PostgreSQL and runs
`python scripts/migrate.py`. The API and internal worker start only after that service exits
successfully; a migration failure prevents them from starting. Standalone deployments must run
`cd backend && python scripts/migrate.py` before the API or workers. The runner upgrades the
database to the latest revision and verifies that the expected head was reached.
The API independently checks the PostgreSQL revision at startup and fails closed on a mismatch.

---

## 3. Authentication & Authorization Flow

```text
1. User → POST /api/auth/login (username + password over TLS; the server checks it against the salted hash with Werkzeug check_password_hash)
2. API Server → verifies credentials → generates JWT with unique jti → sets httpOnly 'auth_token' cookie
3. Browser → subsequent API requests automatically transmit httpOnly cookie
4. Server → verify_token() middleware → checks Redis jti revocation blacklist → DB role lookup → authorizes
5. Logout → POST /api/auth/logout → clears cookie + blacklists jti in Redis (TTL = remaining token lifetime)
```

---

## 4. Submission Pipeline & Sandbox Isolation Security

```text
1. User uploads .ipynb → POST /api/challenges/<id>/parse-notebook
2. User selects code cells → POST /api/tasks/<id>/submit
3. Server: every route creates submissions through one function, `services.submission_service.create_submission`: registration, window and readiness gates, then pre-execution AST validation (IPython magic stripping, banned_imports check). Rejected code returns diagnostics without creating a Submission or consuming quota; accepted code passes the quota checks (the daily limit resets at midnight in the challenge timezone; baselines and `failed_infra` platform failures never count) → creates the Submission → dispatches the Celery evaluation job (baselines and admin and jury test runs at priority 0, ahead of every competitor submission; an enqueue failure marks it `failed_infra`)
4. Worker Node: picks up job → ensures task Docker image (lavbench_task_<id>) is compiled → seeds the run directory (submission script + task data snapshot) into the sandbox via put_archive
5. Hardened Sandbox Container: launches execution with zero-trust security parameters
6. Competitor Code: executes inside container → writes submission.parquet output (pulled back via get_archive)
7. Worker Evaluation Engine: evaluates submission.parquet against labels.parquet server-side (or runs evaluator.py) → updates Submission status & scores → publishes SSE event → invalidates leaderboard cache
```

**File tasks.** A task's `evaluation_mode` is `notebook` (the pipeline above) or `file`; it can change until a competitor has submitted to the task (`ERR_TASK_MODE_LOCKED`, 409). A file task runs no student code:

1. The student submits from the workspace (`POST /api/tasks/<id>/submit-workspace`). One file submission per student and task runs at a time (`ERR_SUBMIT_LOCKED`, 429, with `Retry-After`); other tasks are not blocked. The lock lives 60 seconds and the request renews it while it works, so a crashed web worker frees it within a minute. LavBench asks nanoColab's `export/metadata` for the size and sha256 of `<folder>/submission.parquet` and `<folder>/solution.ipynb`, runs the quota and duplicate checks on that hash, ends the database transaction, and only then streams both files at once with the raw export, checking each against its metadata and capping it at `NANOCOLAB_EXPORT_MAX_BYTES` (20 MiB) while streaming. The workspace and both paths come from the server (the student's workspace row and `Task.folder_name`), never from the request. During a nanoColab outage an admin can turn on the task's emergency upload (`PUT /api/tasks/<id>/emergency-upload`, with a reason, audited), and students then upload the same two files to `POST /api/tasks/<id>/submit-file`.
2. Before any row exists, and with no transaction open, the Parquet is checked against the labels, entirely in a short-lived child process (`services/parquet_check_child.py` under `utils/limited_process.py`): the web process never reads a Parquet. The child gets a clean environment, CPU-time and wall-clock limits (`SUBMISSION_CHECK_TIME_LIMIT_SECONDS`) and a memory limit sized from the labels' ids, from `SUBMISSION_CHECK_MEMORY_MB` up to the ceiling `SUBMISSION_CHECK_MAX_MEMORY_MB`. A limit hit refuses the file; any other failure of the check is a platform error (`ERR_SUBMISSION_CHECK_FAILED`, 503, with `Retry-After`) that is logged, uses no quota and never takes the web worker down. The child first reads the footer: the evaluation size limits, id columns of a plain type (integer, float, string, bool, timestamp or date), and the id and prediction columns the metrics or the custom evaluator need. It then applies three bounds taken from the labels, so a decompression bomb is refused before anything expands. The row count must equal the number of label ids. The id column may hold at most the labels' plain size (ids times the longest id plus 4 bytes, or 8 bytes for numbers) plus an eighth and 64 KiB, and is read with its dictionary kept, so a repeated value stays one entry. No id may be longer than the longest label id, and the ids must be unique. Retrieval runs skip the size and length bounds for `doc_id`, because a run lists documents that are not relevant; `MAX_PARQUET_ROWS` bounds them. Only then does the child read every column in batches of 1024 rows under `MAX_PARQUET_DECODED_BYTES`, and compare the exact id set with Arrow. Each web worker runs at most `SUBMISSION_CHECK_CONCURRENCY` checks (`ERR_SUBMISSION_CHECK_BUSY`, 503, with `Retry-After`). The label ids and their statistics are built once per labels version, when the labels are uploaded, and cached under `UPLOAD_FOLDER/label_ids/v<format>/<labels sha256>`, so a cache written in an older format is ignored and rebuilt; the cache is pruned when no task uses those labels any more. Labels that would need more memory than the ceiling are refused at upload (`ERR_LABELS_TOO_LARGE`, 413, with `limit`). A file that fails gets `ERR_SUBMISSION_FILE_INVALID` (422) with counts only, and uses no quota. Every refusal of the child carries a machine `reason` (for example `row_count` with `rows` and `ids`, or `ids_mismatch` with `expected_ids`, `missing_ids` and `unexpected_ids`) next to the English `detail`: the client shows the text of `api_reasons.<reason>` filled with those values, so a translated message never contains English; `detail` stays for logs and as a fallback. The same holds for `ERR_BASELINE_SUBMISSION_INVALID`, `ERR_BASELINE_SUBMISSION_MISMATCH`, `ERR_HF_ZIP_INVALID` and `ERR_ENVIRONMENT_PACKAGE_TOO_LARGE`.
3. `create_submission` applies the same gates as for cells. Under the submit lock it refuses a Parquet whose sha256 the student already sent to the task (`ERR_SUBMISSION_DUPLICATE`, 409), unless that earlier submission failed on the platform (`failed_infra`). The files move to `UPLOAD_FOLDER/submission_files/<submission id>/`, and the submission records `artifact_path`, `artifact_sha256`, `artifact_size`, `notebook_path`, `notebook_sha256`, `origin` and `workspace_meta`. Every route states the `origin` it creates: `cells` for `/submit`, `workspace`, `emergency_upload`, and `baseline` for baseline runs.
4. File tasks always go to `cpu_queue`. The runner's single branch point (`run_eval_submission`) skips the image and the sandbox: the worker downloads the Parquet from `GET /api/worker/submission-artifact/<id>` with the `submission_artifact` capability of that attempt, re-checks its sha256 (a mismatch fails as `failed_infra`), and goes to the same scoring step as a notebook's output. The scoring step scores the public and the private split together, with one custom evaluator process per distinct metric options, and is timed in one place as `evaluation_time_ms`, shown to admins and the jury only and never used for ranking. In both modes the watchdog allows a running submission its run time (1.5 times the time limit) plus a scoring budget of 120 seconds and `CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS` per evaluator run, so a submission that is still being scored is never marked `failed_infra`. Every Parquet the worker reads is decoded in batches of 1024 rows and stops at `MAX_PARQUET_DECODED_BYTES`.

A file task's baseline is its hidden `baseline_submission.parquet`, checked like a student's file when it is uploaded (`ERR_BASELINE_SUBMISSION_INVALID`, 422) and scored through the same path. The jury and admins download a submission's Parquet and notebook from `GET /api/submissions/<id>/files/parquet` and `.../files/notebook`; while the competition is double-blind the jury's file names carry the alias, never the name. Assigned jury members and admins may download every task file, hidden ones included, at any time, also before the start; competitors never get hidden files. Among a student's submissions with equal scores, the earlier one counts.

### Sandbox Container Isolation Parameters

Competitor code runs inside a zero-trust Docker container with strict Linux kernel caps:

| Parameter | Purpose & Security Guarantee |
| :--- | :--- |
| `--network none` | Completely disables container networking — prevents data exfiltration and external socket calls. |
| `--cap-drop ALL` | Drops all Linux kernel capabilities — blocks raw sockets, `mount()`, `ptrace()`, and privilege escalation. |
| `--read-only` | Mounts root filesystem as read-only — competitor code cannot modify system binaries or libraries. |
| `--no-new-privileges` | Prevents process privilege escalation via SUID binaries. |
| `--tmpfs /tmp:noexec,nosuid,size=128m` | Size-capped temporary memory directory that cannot execute binaries or consume host disk space. |
| `--memory-swap` = RAM Limit | Disables swap memory — guarantees immediate kernel OOM kill if RAM limit is exceeded. |
| `--pids-limit 64` | Restricts total process count to mitigate fork bombs. |
| `--ulimit nofile=256:256` | Caps open file descriptor counts. |
| `--cpus` | Restricts CPU core allocation per container (`CPU_CORES_PER_TASK` / `GPU_CORES_PER_TASK`). |
| `--storage-opt size` | Mandatory quota for the container root writable layer (`WORKER_SANDBOX_STORAGE_OPT`, default `8g`). Evaluation fails closed if the Docker storage driver cannot enforce it. |

> **Known limitation:** `WORKER_SANDBOX_STORAGE_OPT` covers only the container root writable
> layer. The separate per-run anonymous volume mounted at `/app` (rw) is outside that quota and
> has **no disk quota**; competitor code can fill it until the host disk limit is reached. Memory,
> CPU, pid count, and wall-clock time remain capped, and free space on `TASK_IMAGES_DIR`
> (`MIN_BUILD_DISK_GB`) is monitored during builds, but those controls do not cap `/app`.

### Persistent Storage Layout

Sandboxes get no host paths except the read-only Hugging Face folders of their own task (see
"Hugging Face data" below). Task images, the HF cache and the worker workspace live in Docker
**named volumes**, mounted at fixed container paths
(`/var/lib/lavbench/task_images`, `/var/lib/lavbench/hf_cache`, `/var/lib/lavbench/workspace`):

- **Docker mode** (`scripts/deploy-worker.sh`): named volumes `lavbench_task_images`,
  `lavbench_hf_cache`, `lavbench_workspace`, created automatically on deploy.
- **Compose** (`docker-compose.yml`): `task_images_data`, `workspace_data` plus the shared
  `hf_cache` volume, mounted at the same container paths.
- **CI**: the eval worker uses job-local named volumes with the same layout.
- **Local micromamba mode**: the worker runs as a host process and uses plain host directories
  (`TASK_IMAGES_DIR`, `HF_CACHE_DIR`, `LAVBENCH_WORKSPACE_DIR`) — no Docker volumes involved.

### Sandbox `/app`: per-run anonymous volume

Each submission gets a disposable anonymous Docker volume mounted at `/app` (rw). The worker
streams the run directory into it with `put_archive` before the container starts and pulls the
output back with `get_archive` afterwards; the volume is removed together with the container.
Tar metadata is normalized to the sandbox user (uid/gid 65534, dirs 0777, files 0644 + exec bits)
so the non-root process can read and write `/app`. This removes the host-path bind-mount
requirement entirely — the host daemon never needs to resolve a worker-side path, so the same
runner code works in docker, compose, CI and micromamba setups. Labels (`labels.parquet`) are
never written into the sandbox; they stay server-side. The run directory holds the code, the
task's public files in `data/` and, as hard links, the same files beside the code, so a notebook
reads `train.csv` exactly as it does from its workspace task folder.

### Hugging Face data
Each task may have one Hugging Face ZIP holding only `models/<org>/<name>/...` and
`datasets/<org>/<name>/...`, the folders `hf download <repo> --local-dir` writes. Admins and the
jury upload it with `PUT /api/tasks/<id>/hf-zip` (raw body, `Content-Length` required, up to
`HF_ZIP_MAX_BYTES`, 10 GiB); `DELETE` removes it. The web host checks only the central directory:
no duplicate, absolute, `..` or backslash paths, no links or special files, no encryption, stored
or deflated entries, a compression ratio of at most 200, nanoColab's path rules, at most 50,000
entries counted from the directory itself (not only the end record), at most 2,000 visible files
(the package's file cap, enforced even without workspaces), and at least one file under a model or
dataset folder. Hidden entries (any segment starting with `.`, such as
`.cache/huggingface/` and `.gitattributes`) are skipped and counted (`hf_skipped_count`), never
refused; the declared sizes of the other files must stay within `HF_ZIP_MAX_BYTES`
(`hf_unpacked_bytes`). Errors: `ERR_HF_ZIP_TOO_LARGE` (413, with `limit`), `ERR_HF_ZIP_INVALID`
(422, with a machine `reason` such as `outside_folders` or `case_clash`, the path in `file` and the
English text in `detail`) and, when the competition's workspaces
are on, `ERR_HF_FOLDER_CONFLICT` (409, with `folder` and the other task's title in `detail`) for a
folder that another task of the same environment holds with other files (sizes and CRCs compared
at upload, SHA-256 when the package is built), and `ERR_ENVIRONMENT_PACKAGE_TOO_LARGE` (413, with
the projected size or file count in `detail` and `limit`, and `reason` `package_size` or
`package_files`) when the package would pass its byte or
2,000-file cap. These projections use the task columns (`hf_unpacked_bytes`, `hf_file_count`,
`hf_folders`); a ZIP's directory is read again only when two tasks of one owner share a folder
with different ZIPs, so web requests never unzip anything else.

The ZIP is stored once per hash at `UPLOAD_FOLDER/hf/<sha256>.zip`; an upload of bytes already
stored drops its temporary file and keeps the stored one. Installs of one environment owner (a
stage, or the competition without stages) run under one Redis lock shared with the task data
files, and placing or deleting a stored ZIP takes a per-hash lock. Every notebook run records the
task's ZIP hash at dispatch (`Submission.hf_zip_sha256`); a replaced or removed ZIP is deleted only
when no task and no queued or running run refers to it, and the daily `tasks.sweep_upload_store`
deletes the ones left behind. The ZIP locks with the public files after publish, is left out of
backups and of competition exports (the export records its sha256, size and folders, and an
imported task carries `hf_zip_not_imported` until an upload or removal). A task whose ZIP is
missing on the server, for example after a restore, shows `ERR_HF_ZIP_MISSING`. Saving it
schedules the baseline (see "Task Data Uploads").

Workers fetch the ZIP on the first notebook run that needs it, through
`GET /api/worker/hf-zip/<sha256>` with the `hf_zip` capability, which is issued only for the hash
the run recorded, so a run keeps its data when the task's ZIP is replaced mid-run. The run's Celery
time limits grow by 60 s plus two passes over the ZIP at 20 MiB/s (`utils.metadata.hf_prep_seconds`;
10 GiB adds about 18 minutes), and the wait for the per-hash `flock`
(`HF_CACHE_DIR/.locks/<sha256>.lock`) uses the same budget. The download is streamed and checked
against the size and sha256, then extracted into a temporary folder, skipping hidden entries,
refusing a file larger than its declared size or with a bad CRC, and renamed to
`HF_CACHE_DIR/<sha256>/`. A failure is a platform failure (`failed_infra`): the run log shows one
generic line and the cause goes to the worker log. A failure of the data itself (download, size or
hash mismatch, a missing or invalid ZIP) also sets `ERR_HF_DATA_SYNC_FAILED` on the task, like a
task file sync failure; a full cache disk or a lock timeout is the worker's problem and does not.
Every run touches `<sha256>/.last-used`; the sweep at worker start and the daily sweep remove
caches unused for `HF_CACHE_UNUSED_DAYS` (14) and partial folders older than a day.

The sandbox mounts that hash's `models/` and `datasets/` read-only at `/models` and `/datasets`,
so from the working directory `/app` the paths `../models/<org>/<name>` and
`../datasets/<org>/<name>` resolve as they do from `/workspace/<folder>/` in a workspace. No other
hash is visible. A worker that runs in a container (the usual case: it starts sibling containers
through the Docker socket) reads its container id from the source of its `/etc/hostname` mount,
finds the volume behind `HF_CACHE_DIR` by inspecting its own container and mounts it with a
volume subpath (Docker API 1.45, Docker 26 and later); a bind-mounted cache maps to its host path,
and a worker on the host binds `HF_CACHE_DIR` directly. Inside a container that cannot be
identified or inspected, or with no mount covering `HF_CACHE_DIR`, the run fails as a platform
failure instead of guessing a path. The sandbox sets
`HF_HUB_OFFLINE`, `HF_DATASETS_OFFLINE` and `TRANSFORMERS_OFFLINE` to `1`. Scoring never reads
Hugging Face files, and file tasks run no sandbox, so their HF data only reaches workspaces.

### Stale-Dir Sweep
Submission workspace dirs (`LAVBENCH_WORKSPACE_DIR`) are normally removed in a `finally` block,
but a killed/restarted worker can leave plaintext behind. Two complementary sweeps delete any
workspace subdirectory not modified in 24h:
1. **Worker startup** (tasks.py `_stale_dir_sweep_on_start`, `celeryd_init`, fcntl-serialized);
2. **Daily beat** (`task-dir-sweep-daily`).

---

## 5. Task Image Build Pipeline & Build Error Taxonomy

Each task maintains a persistent build directory at `TASK_IMAGES_DIR/task_{id}/`. The container image is tagged `lavbench_task_{task_id}`.

### Image Build Sequence:
```text
[Base Image Pull] ──> [APT Packages Install] ──> [Pip Requirements Install] ──> [Task Files]
```

### Image Build Error Taxonomy (`ERR_IMAGE_BUILD_FAILED`):
1. **Invalid Base Image**: Non-existent tag or 404/401 registry pull error.
2. **APT Resolution Failure**: Misspelled Ubuntu package names or missing apt repositories.
3. **Pip Dependency Conflict**: Incompatible Python library versions or missing C/C++ build tools (`build-essential`).
4. **Disk Space Exhaustion**: Host free disk space below `MIN_BUILD_DISK_GB` (5 GB limit).

### Build Error Recovery & Troubleshooting:
- Build/environment failures are recorded as a **problem registry** — a list of machine-readable codes on `task.problem_codes` (e.g. `ERR_TASK_FILE_SYNC_FAILED`, `ERR_HF_DATA_SYNC_FAILED`, `ERR_TASK_BUILD_FAILED`, `ERR_BASELINE_FAILED`, `ERR_BASELINE_SUBMISSION_MISMATCH`). Any non-empty registry blocks new submissions with `ERR_TASK_NOT_READY` (403) and every root cause is translated client-side.
- Staff responses (`problem_codes` in the task form and the task list) add codes read from the task's files on every request: `ERR_TASK_LABELS_MISSING`, `ERR_BASELINE_SUBMISSION_MISSING` (file tasks) and `ERR_HF_ZIP_MISSING`. They are shown but not stored. `ERR_TASK_LABELS_MISSING` also closes the readiness gate, since `services.task_data.readiness_problems` feeds both the gate and the list: a task without labels refuses competitor and staff submissions with `ERR_TASK_NOT_READY` (no row, no quota), a file task before its file is fetched or checked; baselines skip the gate as always. The other two codes only inform staff.
- `problem_fields` (staff responses, `Task.problem_fields`) holds message fields stored with a code, by code. `ERR_BASELINE_SUBMISSION_MISMATCH` stores the check's `reason` and values (for example `ids_mismatch` with `expected_ids`, `missing_ids` and `unexpected_ids`, or `row_count` with `rows` and `ids`) and the English `detail`; the problem entries of `ERR_TASK_NOT_READY` carry the same fields, and the task form and task list fill them into the translated text.
- The registry is lifecycle-managed: worker-reported build failures add codes, a successful build clears the build-family codes, and environment config changes (base image, apt/pip settings) clear stale build-family problems.
- Every way a baseline run ends (worker report, never picked up, lost worker, Celery time limit, kill, admin queue clear) settles the task in one place, `services.baseline_service`: a completed run removes `ERR_BASELINE_FAILED`, and a failed, killed or cleared run sets it. A `failed_infra` baseline (never picked up, lost worker, GPU, Docker, Celery time limit) is first retried as a new baseline run, at most 2 times (3 attempts), each with its own submission row and logs. There is no retry when the task already has another problem code (every run would fail the same way) or when the broker refused the run; saving the task schedules a new baseline.
- Creating a task, saving its form and every data file or HF upload or removal schedule the baseline instead of queuing it: `services.baseline_service.schedule_baseline` sets a Redis marker (`baseline_due:<task id>`, a token per change, 10 minutes TTL), deletes the ended baseline runs, and sends `tasks.run_due_baseline` to the `internal` queue with a 60 s countdown. Only the run whose token is still the marker's queues the baseline, so a form save followed by several uploads gives one run about a minute after the last change, and one image build. Queued or running older baseline runs keep their rows, so their workers can still report; while the marker exists their outcome changes nothing. Without Redis or the broker the baseline is queued at once. Because the internal worker dispatches these runs (and the watchdog's baseline retries), its allowlist includes `EVALUATION_SPLIT_SECRET` and the dispatch settings (`DEFAULT_TIME_LIMIT_SEC`, `DEFAULT_RAM_LIMIT_MB`, `DEFAULT_PUBLIC_EVAL_PERCENTAGE`, `CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS`, the Celery time limits, `CELERY_MESSAGE_EXPIRES`, `MAX_QUEUED_EVALUATIONS`); a dispatch that cannot build its metadata marks the run `failed_infra` instead of leaving it queued.
- If a build lock is stuck due to worker interruption, an admin can clear it on the worker host with the worker-side `clear_build_lock(task_id)` helper (`tasks/task_modules/image_builder.py`) — e.g. from a worker shell. There is no UI button or admin HTTP route for this.
- Saving semantic task edits (base image, apt/pip settings, task files, evaluator code) changes the image configuration hash (`_config_hash`), so the next build (the debounced baseline run, or the next submission) builds a new image instead of reusing the cached one.

### Task Data Uploads
The task form saves the metadata with only the small files in one multipart request: the baseline
and solution notebooks and the evaluator, each at most `MAX_NOTEBOOK_BYTES` (16 MiB). Every data
file, public or hidden, `labels.parquet` and `baseline_submission.parquet` included, then streams
one per request as the raw body of `PUT /api/tasks/<id>/files/<name>?visibility=public|hidden`
(`Content-Length` required, up to `TASK_FILE_MAX_BYTES`, 10 GiB, `ERR_FILE_TOO_LARGE` with
`limit`); `DELETE` on the same path removes a file. The multipart routes refuse data file fields
(`ERR_INVALID_UPLOAD_FORMAT`). The upload and the HF ZIP share `utils/uploads.py`: the auth, name,
count (5 files) and lock checks run first. The body must be `application/octet-stream` or
`application/zip` (`ERR_UPLOAD_CONTENT_TYPE`, 415) with a `Content-Length` (`ERR_UPLOAD_LENGTH_REQUIRED`,
411), and must fit the upload disk minus 2 GiB (`ERR_UPLOAD_NO_SPACE`, 507, with the free space in
`limit`). Then the transaction ends and the body is hashed while it is written to a temporary file
in `UPLOAD_FOLDER/.incoming/`, on the same filesystem so that installing it is a rename; a dropped
connection answers `ERR_UPLOAD_INTERRUPTED`. The per-file checks follow: labels in the limited
child, a file task's `baseline_submission.parquet` against the current labels (refused with
`ERR_BASELINE_SUBMISSION_INVALID`, 422, with `detail`), and, for public files when workspaces are
on, the projected package caps. New labels are never refused because of the stored baseline: they
install, and the stored baseline is checked against them afterwards; one that no longer fits sets
`ERR_BASELINE_SUBMISSION_MISMATCH` until a fitting baseline or fitting labels are uploaded, or
either file is removed. Only then, under the environment owner's Redis lock (busy:
`ERR_UPLOAD_STORE_BUSY`, 503, with `Retry-After`), is the file renamed into place and recorded with
its size and sha256, replacing a file of the same name; a refused or interrupted upload leaves the
stored file untouched. A hidden file after publish needs an admin and a `reason`, as before. Every
change is audited (a replacement also records the previous visibility and size) and schedules the
baseline. Moving a task to another stage checks the target owner's package caps and HF folders
under that owner's lock, held until the move commits, so two moves into one owner cannot both
pass.

The daily `tasks.sweep_upload_store` (on the `internal` queue) removes temporary files in
`.incoming/` older than 6 hours, files in a task folder that the task's row does not list (left by
a crash between the rename and the commit) once they are 6 hours old, and stored HF ZIPs nothing
refers to. Competition exports write only the files a task lists, and backups leave `.incoming/` out.

### Task File & Label Replacement (unique `saved_name`)
Uploaded task resource files (including `labels.parquet`) are stored under a UUID-prefixed
`saved_name` (extension preserved). Because re-uploading a file with the *same* public filename
rotates the `saved_name`, the worker-side asset cache — which uses `saved_name` as its change
marker — detects the replacement and re-syncs the new bytes into `TASK_IMAGES_DIR/task_{id}/data`
(and the host-only `labels/` cache), and image builds re-bake the fresh data. The upload route keeps
exactly one manifest entry per filename and reclaims the replaced on-disk file after a
successful upload.

### Worker Downloads & Integrity
Every upload records `size_bytes` and the `sha256` of the stored bytes in its `Task.files` entry,
computed while the file is saved; a challenge import recomputes both from the extracted files.
Workers receive these entries with each submission, and the worker file endpoint
(`GET /api/worker/tasks/{id}/files/{name}`) sends `Content-Length` and, when the hash is known,
an `ETag` equal to the sha256. The endpoint allows 120 requests per minute per worker address, so
concurrent jobs can sync every file of their tasks.

Every worker download (asset cache, host-only labels cache, image build context) goes through
`utils.worker_utils.download_file`; an image build that reads the uploads folder directly copies
through `copy_file_verified`, which applies the same steps 2 to 4:

1. The body is streamed in 1 MiB chunks (`stream=True`) into a temporary file in the destination
   directory and hashed on the way, so memory use does not grow with the file size. Temporary
   files start with `.download-`: the runner's asset snapshot skips them, and the generated
   `.dockerignore` keeps them, `.locks/` and the host-only `labels/` out of the image build
   context.
   `WORKER_DOWNLOAD_TIMEOUT` bounds the connection and each wait for data, not the whole transfer.
2. The size and sha256 are compared with the recorded ones; on a mismatch the temporary file is
   deleted, the destination is left untouched, and the job fails through the existing sync
   failure path (`ERR_TASK_FILE_SYNC_FAILED` for task files and image builds,
   `ERR_TASK_LABELS_SYNC_FAILED` for labels). Entries from
   before this check carry no sha256: they are checked by size, and urllib3 still rejects a body
   shorter than `Content-Length`.
3. The verified file replaces the destination with an atomic `os.replace`.
4. Writes into the shared `TASK_IMAGES_DIR/task_{id}/` caches hold an exclusive `fcntl.flock` on
   `task_{id}/.locks/<dir>-<name>.lock` (outside `data/`, which is baked into the image). Worker
   processes and containers on one host share the volume and therefore the lock: a second job
   waits, then reuses the file when its sha256 matches instead of downloading it again. A sync
   that already knows the cached copy is stale (its `saved_name` changed) skips that check. The
   wait is bounded (`DOWNLOAD_LOCK_MAX_WAIT`, 900 s); a timeout fails the job through the same
   sync failure path. The lock is not meant for network file systems.

The asset manifest (`task_{id}/.assets.json`, the `saved_name` of each cached file) is updated
under its own lock: each sync re-reads it, merges its changes and replaces it through a unique
temporary file. A failed manifest write is logged and does not fail the run, since the cached
files are already verified; the next sync re-checks them.

---

## 6. Evaluation Engine Architecture

`services/evaluation/` supports 44 standard evaluation metrics across 12 problem categories, alongside custom evaluation scripts (`evaluator.py`).

| # | Category | Metric Keys | Primary Use |
| :--- | :--- | :--- | :--- |
| 1 | **Classification** | `accuracy`, `f1`, `precision`, `recall`, `cohen_kappa`, `matthews_corrcoef` | Discrete target classification. |
| 2 | **Probabilistic** | `auc_roc`, `logloss`, `brier_score` | Calibrated continuous confidence scores. |
| 3 | **Regression** | `rmse`, `mse`, `mae`, `r_squared`, `mape`, `median_ae` | Continuous target error measurement. |
| 4 | **Seq-Labeling (NER)** | `seqeval_f1`, `seqeval_precision`, `seqeval_recall` | Token-level entity classification. |
| 5 | **Generative NLP** | `bleu`, `rouge`, `rouge_l`, `meteor`, `chrf`, `ter` | Translation, summarization, and text generation. |
| 6 | **QA Extractive** | `exact_match`, `f1` (word-overlap) | Reading comprehension token overlap. |
| 7 | **Object Detection** | `map_50`, `map_75`, `map_50_95`, `recall` (box recall) | Bounding box IoU and mAP evaluation. |
| 8 | **Segmentation** | `mean_iou`, `dice`, `pixel_accuracy` | Semantic and instance mask evaluation. |
| 9 | **Keypoints** | `oks`, `pck` | Pose estimation object keypoint similarity. |
| 10 | **Image Quality** | `psnr`, `ssim` | Image reconstruction and restoration metrics. |
| 11 | **Audio Quality** | `snr`, `mel_lsd`, `si_sdr` | Speech and audio processing quality. |
| 12 | **Clustering** | `adjusted_rand_index`, `normalized_mutual_info`, `adjusted_mutual_info`, `v_measure` | Unsupervised cluster grouping similarity. |
| + | **Retrieval** | `ndcg_k`, `recall_k`, `mrr` | Information retrieval and ranking metrics. |
| * | **Custom Evaluators** | Dynamic `METRIC_NAME` returned by `evaluator.py` | Custom domain evaluation scripts (`evaluate(df_sub, df_labels, options)`). |

**Custom evaluators** run on the CPU evaluation worker as a limited subprocess, for notebook and file tasks alike (`services/evaluation/custom_evaluator.py`): the worker's own Python and libraries, a temporary folder holding only the predictions, the labels and the options, an environment built from scratch with no `WORKER_*` or other secrets, and `resource` limits set before the evaluator's code runs (address space `CUSTOM_EVALUATOR_MEMORY_MB`, 1024; CPU time and wall clock `CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS`, 300, after which the whole process group is killed). The result must be a mapping of finite numbers within `MAX_EVALUATOR_RESULT_BYTES`; any failure gives the competitor a generic message, and the evaluator's output goes only to the worker log. The subprocess has no network or filesystem isolation: evaluators come only from admins and the jury, and every upload is audited.

---

## 7. API Type Pipeline & Validation Architecture

```text
Pydantic v2 Schemas + spectree @api.validate Decorators
       │
       ▼
  /apidoc/openapi.json (auto-generated OpenAPI 3.0 spec)
       │
       ▼
  openapi-typescript (npm run generate-api-types)
       │
       ▼
  src/types/api.d.ts (Full TypeScript declaration file)
       │
       ▼
  tsc --noEmit (npm run check-types — validates JSDoc annotations & component props)
```

The spec is reachable through nginx at `:80/apidoc/openapi.json` (no backend host port needed). The `docker-build` CI job regenerates `api.d.ts` from the live stack and fails on any drift; the committed spec snapshots in `docs/source/api/` are refreshed with `make -C docs fetch-spec`. End-to-end behavior (auth, role matrix, rate limits, backups, SSE) is exercised by `scripts/api_smoke_test.py` against the running compose stack in CI.

### Error Standardization (`err()` & `check_error_codes.py`)
All backend API error responses use `err("ERR_CODE", status_code)` returning `{"error": "<message>", "code": "ERR_CODE"}`. The script `backend/scripts/check_error_codes.py` validates in CI that every error code is registered in `DEFAULT_ERROR_MESSAGES` and translated in both `en` and `bg` locale files.

---

## 8. SSE Real-Time Streaming Architecture

Five backend endpoints use Server-Sent Events (SSE):

| Endpoint | Event | Trigger |
| :--- | :--- | :--- |
| `/api/challenges/<id>/leaderboard/live` | `{"event": "update"}` | The leaderboard beat (every 20 s) recalculated a challenge whose scores changed. |
| `/api/submissions/<id>/logs/live` | Execution log lines | Live stdout/stderr from the worker sandbox, streamed only while the submission is running. |
| `/api/admin/backups/live` | `{"event": "update"}` | An automatic or manual backup finished. |
| `/api/admin/submissions/queue/live` | `{"event": "update"}` | The evaluation queue changed. |
| `/api/challenges/<id>/environment/live` | `{"event": "update"}` | A nanoColab environment of the competition changed (section 12). |

Events other than log lines carry no data. On each event the client refetches the matching REST endpoint through TanStack Query, throttled so that a burst of events causes one refetch, and the server never builds a payload per viewer. Every stream sends a `retry:` field and a keep-alive comment, the idle timeout has jitter so that streams do not expire together, and the request's database session is released before streaming starts.

Submission lists are not streamed. A competitor's list is polled every 5 seconds while one of their submissions is queued or running, and not at all otherwise. A finished submission shows its stored logs; for running submissions, Redis keeps the last `SSE_LOG_MAX_LINES` log lines (default 500) for `SSE_LOG_TTL` seconds (default 3600) so that a reconnecting viewer can catch up.

SSE capacity is governed by `SSE_MAX_GLOBAL` (default `2000` concurrent connections platform-wide) and `SSE_MAX_PER_USER` (default `15` per client). Docker Compose loads `.env` into the services, so both can be overridden there.

---

## 9. Automated & Manual Backup Retention Architecture

| Backup Type | Trigger Frequency | Retention Policy | Management & API Constraints |
| :--- | :--- | :--- | :--- |
| **Auto-Backup (full)** | Every **6 hours**, during active competitions and when idle. | Keeps the newest **3** (`BACKUP_RETENTION_COUNT`). Older ones are purged automatically. | System managed (`auto_YYYYMMDD_HHMMSS.tar.gz`). Cannot be deleted manually via API (returns HTTP 403). |
| **Auto-Backup (database only)** | Every **20 minutes** during active competitions. | Keeps the newest **18** (`BACKUP_DB_RETENTION_COUNT`), about 6 hours of history, which reaches back to the previous full backup. | System managed (`auto_db_YYYYMMDD_HHMMSS.tar.gz`). Cannot be deleted manually via API (returns HTTP 403). |
| **Manual Backup** | Triggered on demand via **"Force Backup Now"** button. | Retained **indefinitely**. Never auto-deleted by retention routines. | Administrator managed (`manual_YYYYMMDD_HHMMSS.tar.gz`). Downloadable or deletable via Admin Panel. |

Full archives contain a PostgreSQL dump (`pg_dump`) and the `uploads/` assets in a `.tar.gz`; database-only archives contain the dump alone. Rotated log files (`*.log.N`) are left out, and so are `uploads/environment_packages/` (temporary nanoColab packages, rebuilt from the task files) and `uploads/hf/` (Hugging Face ZIPs, which an admin uploads again; exports record their sha256) and `uploads/.incoming/` (uploads in progress). Archives use the fastest gzip level (`gzip -1`), since task data is mostly already compressed; `pg_dump` is bounded by `BACKUP_TIMEOUT` (600 s) and `tar` by the larger of `BACKUP_TIMEOUT` and `BACKUP_UPLOADS_TIMEOUT` (3600 s). Before each backup the server requires free disk space of at least twice the previous backup of the same kind, and at least `MIN_BACKUP_DISK_GB`. A failed automatic backup is not counted as done and is retried at the next 20-minute check, and at most one automatic backup is queued or running at a time.

---

## 10. Worker Hardware Budgeting & Clamping

During initial setup (`make setup-worker`), workers inspect total CPU cores (`nproc`), RAM (`/proc/meminfo`), and GPUs (`nvidia-smi`), reserving 1 CPU core and 4 GB RAM for system overhead.

### Runtime RAM Clamping Formula:
```text
budget_mb = (GPU_RAM_PER_TASK_GB if task.gpu_required else CPU_RAM_PER_TASK_GB) * 1024

if task_ram <= budget_mb:
    use task_ram as-is
elif task_ram <= budget_mb * RAM_CLAMP_FACTOR (1.05):
    clamp container memory to budget_mb (log warning)
else:
    reject task → Celery retry → dead-letter queue (/api/admin/dead-letters)
```

On the `worker_ready` signal, workers write their hardware specification to the Redis coordination client (`worker_spec:<hostname>`) and a background thread refreshes it every `WORKER_HEARTBEAT_SECONDS` (default 30), together with the queues the worker consumes and `last_seen`. The key expires after one day; a worker counts as online while its last heartbeat is younger than `WORKER_HEARTBEAT_STALE_SECONDS` (default 90). The heartbeats feed `GET /api/status` and `GET /api/admin/system-status` (section 11). Worker registration is fully signal-driven — no registration task exists.

---

## 11. Status and Health Endpoints

| Endpoint | Access | Purpose |
| :--- | :--- | :--- |
| `GET /api/health` | Public | Liveness: database, cache Redis, broker Redis and disk. Returns 200 or 503 and is used by the container health checks. It never checks workers, so a missing worker cannot make the API look down. |
| `GET /api/status` | Public | Coarse status for uptime checks, using the Statuspage words `operational`, `degraded_performance`, `partial_outage` and `major_outage`. Cached for `STATUS_CACHE_SECONDS` (default 30). |
| `GET /api/admin/system-status` | Admin, jury | The detail behind the status: queues, workers and submission counts. Shown in the Admin Panel's **Workers and queues** panel, which polls it every 15 seconds. |

Both status endpoints are computed from worker heartbeats, broker queue lengths and the database. Web processes never call Celery `inspect`.

| Component | Rule |
| :--- | :--- |
| `api` | `major_outage` when the database or the broker Redis is unreachable, otherwise `operational`. |
| `scoring` | `major_outage` when no live worker consumes `cpu_queue`; `partial_outage` when another evaluation queue has pending messages but no live consumer; `degraded_performance` when the oldest queued submission has waited longer than `STATUS_QUEUE_DEGRADED_SECONDS` (default 600); otherwise `operational`. |

The overall `status` is the worst component. A worker counts as live when its last heartbeat is younger than `WORKER_HEARTBEAT_STALE_SECONDS` (default 90); workers send one every `WORKER_HEARTBEAT_SECONDS` (default 30).

---

## 12. nanoColab Environments

LavBench drives nanoColab's `/v1` API; nanoColab never calls LavBench. The contract is nanoColab's OpenAPI file, vendored at `backend/tests/contracts/nanocolab-v1.openapi.json`, and `docs/source/ops/nanocolab-integration.md` records the rest. With `NANOCOLAB_API_URL` unset, every environment route answers `ERR_NANOCOLAB_DISABLED` (404), except `GET /api/environment/images`, which answers `available: false` so the admin forms leave the workspace section out. Every challenge payload carries `workspaces_enabled` (nanoColab configured and the competition's workspaces on); the student task page requests its environment and opens the live stream only when it is true.

| Piece | Where | What it does |
| :--- | :--- | :--- |
| Client | `services/nanocolab_client.py` | Bearer key from `NANOCOLAB_API_KEY_FILE`, HTTPS only (plain http only to localhost with `NANOCOLAB_ALLOW_INSECURE_HTTP`), no redirects, a timeout on every call, nanoColab's three error shapes flattened to one message, `Retry-After` kept. |
| Setting | `models/environment.py`, `environment_service.apply_workspace_setting` | `WorkspaceSetting` (table `workspace_settings`, one row per competition, keyed by `challenge_id`) is the single source of truth for a competition's workspaces: `enabled`, `auto_publish`, `image_id`, `profile_id`, the profile's `cpu_cores` and `memory_gib` (snapshotted at save, so stages are derived without asking nanoColab), `workspace_gib` and `archive_until`. It is saved with the competition form (`workspace` in `POST`/`PUT /api/challenges`). nanoColab's catalog (`GET /v1/images`, with an optional top-level `profiles` list) is read only when the image or profile changes or workspaces are switched on; an older nanoColab without profiles gets the built-in `cpu-compact` (2 vCPU, 8 GiB) and `cpu-standard` (2 vCPU, 12 GiB). |
| Environment | `models/environment.py` | The runtime state, one per stage, or per competition when it has no stages (`Environment`, a check constraint keeps exactly one owner): package, asset version, event id, `published_at`, status, and a copy of the setting. `apply_workspace_setting` rewrites that copy on every unpublished environment whenever the setting is saved or a stage is created, edited or deleted; published environments are never rewritten. `disk_gib` is `workspace_gib` plus the package size (public files, starter notebooks and the unpacked Hugging Face files) rounded up to whole GiB, recomputed at derive time and in every sync's package step, frozen at publish; until then the admin's view measures it live, so an HF upload or removal shows at once. When the first stage is added, an unpublished competition environment is switched off and the stages take over; a published one refuses new stages (`ERR_ENVIRONMENT_LOCKED`). `Workspace` maps a student to their nanoColab workspace, created on the first "Open workspace". |
| Package | `services/environment_package.py` | One deterministic ZIP per version: a folder per task named by `Task.folder_name`, holding the task's public files and its baseline as `solution.ipynb`, plus the root `models/` and `datasets/` from every task's Hugging Face ZIP (hidden entries left out, streamed entry by entry; the same ZIP in two tasks ships once, and a folder in two different ZIPs ships once when both hold the same paths and every file has the same SHA-256, computed while the package is built, otherwise `ERR_HF_FOLDER_CONFLICT`). Hidden files (`utils.files.task_file_visibility`) never ship. `ZIP_STORED`, ZIP64 when needed, sorted, 1980 timestamps, mode 0644, at most `NANOCOLAB_PACKAGE_MAX_BYTES` (10 GiB), 2,000 files and 16 export paths, one per notebook task and two per file task (`ERR_ENVIRONMENT_TOO_MANY_TASKS`); the version is `lb-<12 hex of the content digest>-v1`. |
| Sync | `services/environment_service.py`, beat `tasks.sync_environments` | Every `NANOCOLAB_SYNC_INTERVAL_SECONDS` (60) the beat queues one `tasks.sync_environment` per enabled environment on the `internal` queue; applying the setting queues one for each enabled environment too. A run builds and uploads the package when the files changed (signed-URL PUT with progress, then `complete`); the change check fingerprints the public files by name, size and mtime and the HF data by each task's ZIP sha256, so an unchanged package is never unzipped, PUTs the full event, publishes when "Publish automatically" is on and the start is within `NANOCOLAB_AUTO_PUBLISH_LEAD_HOURS`, caches readiness in Redis and signals `/api/challenges/<id>/environment/live`. Runs of one environment are serialized by `cache_lock`, and a run has its own Celery time limits (50 min soft), long enough to build and upload a 10 GiB package. Environments past their end plus grace are not queued. Publish first checks that the uploaded package still matches the task files; if not, it queues a sync and answers `ERR_ENVIRONMENT_PREPARING`. |
| Cancel | `cancel_events`, `reconcile_events`, beat `tasks.reconcile_nanocolab_events` | Deleting a stage or a competition cancels the nanoColab events of its environments. Every 10 minutes, under its own lock, a separate beat task lists the client's own events (`GET /v1/events`) and cancels up to 20 per run whose id has LavBench's form and whose stage or competition LavBench no longer has, which retries a cancel that failed during a delete. It assumes one LavBench per nanoColab API key. A cancel cannot be undone, so switching an environment off cancels nothing. |
| Export | `workspace_source`, `export_metadata`, `fetch_exports` | Reads files of the student's own workspace: `export/metadata`, then the streamed `export/raw` of all files at once, checked against that size and sha256 and capped at `NANOCOLAB_EXPORT_MAX_BYTES`. The transaction ends before any call, and every export is audited (`export`). |
| Event | `event_payload` | `ends_at` is the owner's end plus `DEADLINE_GRACE_PERIOD_SECONDS`. `max_attendance` is the registered students plus `NANOCOLAB_ATTENDANCE_HEADROOM_PERCENT` (at least 2), and `retention_days` runs to the archive date, which is the end plus 30 days unless the admin picks one; an extension moves a picked date along with the end. Both freeze at publish, as nanoColab requires. |

**Roles.** Admins choose the setting, publish and extend; the jury reads each environment's status, details and workspace list (aliases while double-blind); students see one word per task (not open, preparing, ready, closed, or unknown while the cached status is stale) and launch, once the task's stage has started (`ERR_NOT_AVAILABLE` before, as for the task itself). GET routes never call a writing nanoColab endpoint.

**Status.** Admins and the jury see `off`, `uploading` (with a percentage), `preparing`, `ready`, `problem` (with nanoColab's message, for admins only; the jury gets the code) or `unknown` when the cached readiness is older than `NANOCOLAB_STATUS_STALE_SECONDS`. A published environment that stays `preparing` longer than `NANOCOLAB_PREPARING_ALERT_MINUTES` carries `alert: true`.

**Locks after publish.** The start, the compute settings, the image and the archive date are fixed; a setting change while every environment is published is refused (`ERR_ENVIRONMENT_LOCKED`), otherwise only the unpublished ones take it; the end moves only later, through an extension with a reason before the current end plus grace (`ERR_EXTENSION_TOO_LATE`). Public task files, the Hugging Face data, the baseline, task moves and deletions are refused (`ERR_TASK_FILES_LOCKED`), and so is a folder rename. Until then a task's folder follows its title, unless an admin set the folder name by hand; a generated name already used in the stage gets a number (`-2`, `-3`, ...), while a taken hand-set name is refused (`ERR_TASK_FOLDER_TAKEN`). Hidden files (`labels.parquet`, `baseline_submission.parquet` and any file uploaded as hidden) and the evaluator may still be replaced, but only by an admin with a typed `reason`, which the audit entry keeps; a file task's baseline is scheduled again. Enabled environments of one competition may not overlap, counting the grace period after each end, because each student has one Hub server (`ERR_ENVIRONMENT_OVERLAP`, checked when workspaces are switched on, a stage is added or a stage moves).

**Routes.** `GET /api/environment/images` (admin) returns `available`, the images, the profiles and the `workspace_gib` range (10 to 100 GiB minus the package limit, `NANOCOLAB_PACKAGE_MAX_BYTES`, so 90 by default; default 10). `GET /api/challenges/<id>/environments` (admin, jury) lists each environment with its status, `workspace_gib`, `data_gib` and `disk_gib`. Publish, extension, the workspace list, the live stream and the task environment and launch routes act on one environment. A refused setting value names its `field` (for example `workspace.workspace_gib`) and carries extra values such as `min`, `max`, `allowed` or `stages` in the error body.

**Local stack.** `make dev-nanocolab` starts nanoColab's kind stack and API, LavBench with its workers, and prints the admin login; `make e2e-nanocolab` runs the admin, student and jury paths against it; `make dev-nanocolab-down` stops it.
