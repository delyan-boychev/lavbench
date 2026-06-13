# Developer API Complete Reference

This comprehensive specification outlines the REST endpoints and Server-Sent Events (SSE) utilized by the NAI Web Platform backend.

## Table of Contents
1. [Authentication & Access Control](#1-authentication--access-control)
2. [Admin & Configuration Endpoints](#2-admin--configuration-endpoints)
3. [Tasks & Submissions Processing](#3-tasks--submissions-processing)
4. [Leaderboard & Scoring Endpoints](#4-leaderboard--scoring-endpoints)
5. [Real-Time SSE Streaming](#5-real-time-sse-streaming)

---

## 1. Authentication & Access Control

### POST `/api/auth/login`
Authenticates a user and issues a JWT.
* **Rate Limiting:** Protected against brute-force attacks via hybrid account/IP token-bucket limits.
* **Request:** `{"username": "student_1", "password": "secure_password"}`
* **Response (200 OK):** Returns the JWT `token` and a subset of the `user` demographic data.
* **Response (403 Forbidden):** Triggered if a competitor attempts to log into an `is_archived=True` challenge.

### GET `/api/auth/me`
* **Headers:** `Authorization: Bearer <token>`
* **Description:** Retrieves full session demographics for the currently authenticated token.

---

## 2. Admin & Configuration Endpoints

### POST `/api/admin/register-user`
* **Role:** Admin Only
* **Request:** JSON object containing `username`, `email`, `password`, `role`, and `alias_id`.
* **Response (201 Created):** `{"message": "User registered", "user_id": X}`

### POST `/api/admin/import-competitors-csv`
* **Role:** Admin Only
* **Request:** Multipart Form-Data containing `file` (.csv).
* **Description:** Bulk provisions user accounts and assigns them to the mapped `challenge_id`.

### GET `/api/challenges/<challenge_id>/export-results`
* **Role:** Admin / Jury Only
* **Description:** Generates a comprehensive CSV/Excel/JSON export containing true competitor identities, highest public/private scores, all manual points, final calculated rankings, and the appended `AuditLog` of any post-finalization score corrections.

---

## 3. Tasks & Submissions Processing

### POST `/api/challenges/<challenge_id>/parse-notebook`
* **Role:** Authenticated
* **Request:** Multipart Form-Data containing `file` (.ipynb).
* **Security Constraints:** Enforces a strict 5MB payload limit to prevent Out-Of-Memory (OOM) Denial of Service attacks.
* **Response (200 OK):** Returns a JSON array of `cells` detailing the `type` and `source` code.

### POST `/api/challenges/<challenge_id>/submit`
* **Role:** Authenticated (Student/Admin/Jury)
* **Request:** `{"selected_cells": ["def predict..."], "task_id": 1}`
* **Validation Pipeline:**
  1. Verifies the challenge `is_frozen` toggle is `False`.
  2. Verifies the timestamp is within `start_time` and `end_time` (inclusive of the configurable `deadline_grace_period_seconds`).
  3. Executes the AST Rules Engine (bans `os`, `sys`, requires `# SUBMIT`).
* **Response (202 Accepted):** Submission written to DB and successfully queued in Celery.
* **Response (429 Too Many Requests):** Daily execution limit reached.

### GET `/api/tasks/<task_id>/submissions`
* **Role:** Authenticated
* **Query Params:** `page`, `per_page`
* **Performance Note:** Utilizes lightweight list serialization (`to_dict_light()`). The massive `code_cells` and execution `logs` fields are stripped from the response body to minimize network payloads. A secondary `GET /submissions/<id>` call is required to view full details.

---

## 4. Leaderboard & Scoring Endpoints

### GET `/api/tasks/<task_id>/leaderboard`
* **Role:** Authenticated
* **Description:** Returns the cached leaderboard standings.
* **Tie-Breaking Algorithm:** If aggregated scores match perfectly, the JSON array is sorted by `execution_time_ms` (ascending) as a secondary fallback.

### POST `/api/challenges/<challenge_id>/manual-points`
* **Role:** Admin / Jury Only
* **Request:** `{"user_id": 42, "points": {"1": 95, "2": 80}, "reason": "Optional unless finalized"}`
* **Validation Logic:** 
  * Rejects `400 Bad Request` if the target `user_id` possesses zero completed submissions for the requested task.
  * If the challenge has `scores_finalized=True`, a `reason` text payload is strictly required. The backend automatically records this change into the `AuditLog` table.

---

## 5. Real-Time SSE Streaming

All WebSockets/SSEs are served asynchronously using `gevent` Gunicorn workers to prevent synchronous thread deadlocking.

### GET `/api/tasks/<task_id>/submissions/live`
* **Headers:** `Accept: text/event-stream`
* **Event:** `submission_status`
* **Description:** Pushes real-time Celery pipeline state transitions (`queued` -> `building_env` -> `running_inference` -> `evaluating` -> `completed`/`failed`). 
* *Note: To mitigate DB/SSE DDoS, workers are configured to only broadcast major state transitions under high load.*

### GET `/api/tasks/<task_id>/leaderboard/live`
* **Headers:** `Accept: text/event-stream`
* **Event:** `leaderboard_update`
* **Description:** Triggers a frontend refetch signal when the cached leaderboard ranking array changes (e.g., when a student updates their final selection or a jury member assigns manual points).