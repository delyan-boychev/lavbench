# Security Audit Report: National AI Competition Platform

This document outlines critical and high-priority vulnerabilities identified during a scale-readiness security audit.

## 1. Critical Vulnerabilities

### 1.1 Evaluation Manipulation (Same-Process Execution)
*   **Location:** `backend/tasks.py` (Evaluation Templates)
*   **Description:** The platform currently injects user-provided code into the same Python process that performs the ground-truth comparison and writes the results to `eval_results.json`.
*   **Vulnerability:** A malicious competitor can "monkey-patch" the scoring logic (e.g., overriding `accuracy_score`) or hijack the `json.dump` call to spoof their own results.
*   **Impact:** Complete loss of competition integrity. Cheating cannot be detected automatically.
*   **Recommendation:** Decouple execution from scoring. 
    1.  Run user code in a container to produce a `predictions.json` file.
    2.  Run a separate, isolated scoring script that reads the predictions and compares them against the hidden dataset.

---

## 2. High-Priority Vulnerabilities

### 2.1 Account Lockout DoS (Username-Based Rate Limiting)
*   **Location:** `backend/routes/auth.py` (`check_rate_limit`)
*   **Description:** The login rate limiter tracks failed attempts using only the `username` as a key in Redis.
*   **Vulnerability:** An attacker can intentionally trigger failed logins for known usernames, locking legitimate users out of their accounts.
*   **Impact:** A single malicious actor can prevent all participants from logging in during a competition.
*   **Recommendation:** Change the rate-limiting key to a combination of `username` and `IP Address`.

### 2.2 Unrestricted Docker Build Resource Usage
*   **Location:** `backend/tasks.py` (`evaluate_submission` build phase)
*   **Description:** When tasks require custom `apt` or `pip` packages, the worker executes `docker build`.
*   **Vulnerability:** The build phase has full network access and no CPU/RAM constraints, unlike the `docker run` phase.
*   **Impact:** A malicious task configuration can be used to scan internal networks, exfiltrate data from the worker, or crash the worker via resource exhaustion during the build.
*   **Recommendation:** Implement strict timeouts for `docker build` and restrict custom environment creation to trusted administrator accounts.

---

## 3. Medium-Priority Vulnerabilities

### 3.1 Shared Worker Secrets
*   **Location:** `backend/tasks.py`, `backend/routes/tasks.py`
*   **Description:** All worker nodes share a single global `WORKER_SECRET_KEY`.
*   **Vulnerability:** Compromise of any single worker node grants access to all task files and allows spoofing reports for any submission in the system.
*   **Impact:** Reduced resilience in a distributed environment.
*   **Recommendation:** Move to a per-worker authentication model or use short-lived, submission-specific tokens.

### 3.2 Shared Hugging Face Cache Poisoning
*   **Location:** `backend/tasks.py` (`HF_CACHE_DIR`)
*   **Description:** All Docker containers on a specific worker node mount the same host directory for the Hugging Face cache.
*   **Vulnerability:** A malicious submission could write to or modify files in the shared cache, poisoning models or datasets used by subsequent submissions from other users.
*   **Impact:** Data integrity risk for multi-tenant worker nodes.
*   **Recommendation:** Mount the cache as read-only for student submissions or use isolated cache subdirectories per user.

---

## 4. Next Steps & Mitigations

| Vulnerability | Action | Status |
| :--- | :--- | :--- |
| **Evaluation Manipulation** | Refactor `tasks.py` to use a two-stage evaluation pipeline. | ⏳ Pending |
| **Account Lockout DoS** | Update `auth.py` to include IP in the rate-limit key. | ⏳ Pending |
| **Docker Build Limits** | Add `--ulimit` or timeouts to the build subprocess call. | ⏳ Pending |
| **Worker Secrets** | Implement per-submission JWTs for workers. | ⏳ Pending |
