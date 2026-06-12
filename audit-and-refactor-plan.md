# Comprehensive Implementation Plan: AI Competition System Audit, Refactor & Feature Expansion

## 1. Executive Summary & Core System Design
The goal of this initiative is to resolve technical debt, fix critical UI bugs, and solidify a robust, feature-rich architecture for the AI Competition Platform. This system must be bug-free, highly responsive, and strictly enforce the following design requirements:

### Core System Design Requirements
*   **Anonymization & Privacy:** 
    *   Competitors are assigned auto-generated aliases. Real names are strictly visible only to Jury/Admins until finalization.
*   **Final Submission Selection:**
    *   Competitors must explicitly select **1 Final Submission** per task to prevent overfitting.
*   **Leaderboard & Tie-Breaking:**
    *   **Score Direction:** The system supports both "Higher is Better" (e.g., Accuracy) and "Lower is Better" (e.g., Mean Squared Error) for leaderboard sorting.
    *   Identical scores are broken by **Execution Time** (faster ranks higher).
*   **Scheduling & Competition Lifecycle:**
    *   Strict `start_time`, `end_time`, and `freeze_time`.
*   **Optional Rate Limiting:**
    *   Admins can *optionally* define limits (e.g., 5 submissions per 24 hours) to prevent queue hogging.

---

## 2. Distributed Celery Architecture & Hugging Face Data
**Constraint:** Transferring large datasets from the main server to remote workers is slow. 
**Resolution:** Remote workers will download datasets *directly* from Hugging Face, utilizing aggressive local disk caching.

### Strict "Blind Evaluation" Data Security Model
To guarantee students cannot cheat by writing logic tailored to the test set, the platform will enforce a **Blind Evaluation** model. Students *never* get access to the evaluation inputs or labels. Their code runs entirely on the server.

**How it works per Task:**
1.  **Two Repositories:** The Admin defines two Hugging Face repo URLs for the task:
    *   `Public Train Repo:` Contains the training data. This URL is visible to competitors so they can build their models locally or in notebooks.
    *   `Private Eval Repo:` Contains the hidden evaluation data (inputs + labels). This is kept entirely secret.
2.  **Secret API Key:** The system securely stores a Hugging Face API Token provided by the Admin to access the `Private Eval Repo`.
3.  **Dynamic Splits:** The Admin sets a `public_eval_percentage` (e.g., 30%). 

### Priority-Based Queue Processing
To ensure fairness during peak submission times (e.g., 1 hour before the deadline), the backend dynamically calculates Celery task priority:
1.  **Admin Evals:** Priority 1 (Highest).
2.  **First Submission (Today):** Priority 2.
3.  **Frequent Submitters:** Users who have submitted recently get progressively lower priority to prevent queue monopolization.

---

## 3. Evaluation Mechanics & Rule Violations (The Sandbox)
### Phase 1: Pre-Execution Rule Engine (UI-Driven Checks)
The **Admin Task UI** will feature a dedicated "Execution Rules" section:
*   `[Checkbox]` **Require `# SUBMIT` Tag:** If missing, Score 0.
*   `[Checkbox]` **Ban Jupyter Magic Commands:** If `!` or `%` found, Score 0.
*   `[Text Input]` **Banned Libraries:** AST check blocks imports (e.g., `os, requests`).

### Phase 2: Granular Docker Configuration (Per-Task Environments)
To ensure the sandbox environment perfectly matches the task requirements, Admins can define the exact Docker environment:
*   `Base Image:` e.g., `python:3.10-slim` or `pytorch/pytorch:2.0.0-cuda11.7-cudnn8-runtime`.
*   `APT Packages:` e.g., `libgl1-mesa-glx, ffmpeg` (for OpenCV tasks).
*   `PIP Requirements:` A standard `requirements.txt` string.
*The remote worker dynamically builds/caches this image before running the student's code securely (`--network none`, `--pids-limit 64`, `--tmpfs`).*

### Phase 3: Live Status Tracking (Competitor UX)
The UI will poll (or use Server-Sent Events) to display granular live status updates to the competitor, reducing anxiety during long evaluations:
1.  `Queued`: Waiting in the Celery broker.
2.  `Building Env`: Worker is installing apt/pip requirements.
3.  `Running Inference`: Executing `submission.predict()`.
4.  `Evaluating`: Running the Judge's `evaluator.py`.
5.  `Completed` / `Failed`.

---

## 4. Database Schema Updates (Backend Phase 1)
Expand `backend/models.py`:

### `Task` Model:
*   Add overrides (`ram_limit_mb`, `time_limit_sec`, `gpu_required`).
*   **Docker Config:** `base_docker_image` (String), `apt_packages` (Text), `pip_requirements` (Text).
*   **Add Rule Settings:** `require_submit_tag` (Boolean), `ban_magic_commands` (Boolean), `banned_imports` (String).
*   Add `metrics_config` (JSON) - e.g., `{"accuracy": {"weight": 1.0, "higher_is_better": true}}`.
*   Add `evaluator_script_path`, `baseline_notebook_path`, `solution_notebook_path`.
*   **Add HF & Evaluation:** 
    *   `hf_train_repo` (String, Public).
    *   `hf_eval_repo` (String, Private).
    *   `hf_api_key` (String, Encrypted/Secret).
    *   `public_eval_percentage` (Integer, 0-100).
    *   `max_submissions_per_period` (Integer, Optional).
    *   `submission_period_hours` (Integer, Optional).
*   Remove legacy `custom_eval_code`.

### `Submission` Model:
*   Add `metrics_payload_public` (JSON) and `metrics_payload_private` (JSON).
*   Add `final_weighted_score_public` (Float) and `final_weighted_score_private` (Float).
*   Add flags: `is_final_selection`, `is_disqualified`.
*   Add `celery_task_id`, `plagiarism_score`, `llm_probability`.
*   Add `detailed_status` (String) - Maps to the live status tracking states.

---

## 5. API Routes & Celery Sandbox Architecture (Backend Phase 2)
1.  **Rule Engine:** Implement the AST parser before queueing.
2.  **Worker Image Builder:** Worker parses `apt_packages` and `pip_requirements`, writes a dynamic Dockerfile, builds/caches it, and runs it.
3.  **Status Callbacks:** Worker updates the `detailed_status` column in the DB at every phase.
4.  **Distributed Dispatching:** Explicit `queue` routing based on `gpu_required` with dynamic `priority`.

---

## 6. Frontend Routing Architecture (Frontend Phase 1)
**Constraint:** The current `App.jsx` handles all navigation via conditional state rendering.
**Resolution:** Introduce **React Router v6** to provide distinct, deep-linkable URLs.

**Target Route Structure:**
*   `/` -> `Home.jsx`
*   `/challenges/:id/leaderboard` -> `LeaderboardTable.jsx`
*   `/challenges/:id/submissions` -> `SubmissionsView.jsx`
*   `/admin` -> `AdminPanel.jsx` (Protected Route)

---

## 7. UI Component Standardization (Frontend Phase 2)
*   Overwrite `src/components/ui/Button.jsx`, `InputField.jsx`, `SelectField.jsx`, and `Badge.jsx` with the Tailwind-based implementations.

---

## 8. Submissions Module & Bug Fixes (Frontend Phase 3)
### Bug Fixes:
*   In `SubmissionViewer.jsx`, change `{submission.execution_log}` to `{submission.logs}`.
*   Change `{submission.alias_id}` to `{submission.user?.alias_id}`.

### Feature Additions:
*   **Live Status Badges:** Render `Building Env`, `Running`, etc.
*   **Final Selection Checkbox.**
*   **Jury Demographics & Integrity View.**

---

## 9. Admin Panel Extraction & Upgrades (Frontend Phase 4)
*   Build the new `AdminPanel.jsx` route.
*   **Add "Docker Config" UI:** Fields for `base_docker_image`, `apt_packages`, and `pip_requirements`.
*   **Add "Execution Rules" UI:** Checkboxes for `# SUBMIT` tags, Magic Commands, and a Text Input for Banned Libraries.
*   **Add Data Integration UI:** Fields for `hf_train_repo`, `hf_eval_repo`, `hf_api_key` (password field), and a slider for `public_eval_percentage`.
*   **Add Config UI:** Upload buttons for `evaluator.py`, Baseline Notebook, and Solution Notebook. Optional rate limits.

---

## 10. Verification & QA Protocol
1.  **Dynamic Priority:** Submit from User A (first submission) and User B (5th submission). Verify User A's task executes first via Celery inspection.
2.  **Docker Build:** Provide `libgl1-mesa-glx` in `apt_packages` and `opencv-python` in `pip_requirements`. Verify the sandbox successfully builds and imports `cv2`.
3.  **Live Status:** Verify the UI updates from `Queued` -> `Building Env` -> `Running Inference` in real-time.
4.  **HF Caching:** Submit 3 tasks in a row. Verify task 2 and 3 evaluate instantly without re-downloading the Hugging Face dataset.
5.  **UI Rule Enforcement:** Enter `os` in the Banned Libraries field. Submit code with `import os`. Verify instant Score 0.