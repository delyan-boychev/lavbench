# Developer API Complete Reference

This document provides a detailed specifications guide for all REST API endpoints and real-time Server-Sent Events (SSE) streaming connections.

---

## 1. Authentication Service

### Login User
* **Endpoint:** `POST /api/auth/login`
* **Request Body:**
  ```json
  {
    "username": "competitor_user",
    "password": "hashed_password"
  }
  ```
* **Response (200 OK):**
  ```json
  {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwicm9sZSI6ImNvbXBldGl0b3IiLCJleHAiOjE3ODE0MTgwMDB9...",
    "user": {
      "id": 2,
      "username": "competitor_user",
      "role": "competitor",
      "alias_id": "Quantum-Falcon-402"
    }
  }
  ```
* **Response (400 Bad Request):**
  ```json
  {
    "error": "Missing username/email or password"
  }
  ```
* **Response (401 Unauthorized):**
  ```json
  {
    "error": "Invalid credentials"
  }
  ```

### Get Session Demographics
* **Endpoint:** `GET /api/auth/me`
* **Headers:** `Authorization: Bearer <token>`
* **Response (200 OK):**
  ```json
  {
    "id": 2,
    "username": "competitor_user",
    "email": "comp1@competition.ai",
    "role": "competitor",
    "alias_id": "Quantum-Falcon-402",
    "name": "Alice",
    "surname": "Lovelace",
    "class_number": "11",
    "school": "AI High",
    "city": "Sofia"
  }
  ```

---

## 2. Admin Actions Service

### Register Single User
* **Endpoint:** `POST /api/admin/register-user`
* **Headers:** `Authorization: Bearer <token>` (Admin only)
* **Request Body:**
  ```json
  {
    "username": "new_grader",
    "email": "grader@competition.ai",
    "password": "temporary_password",
    "role": "jury",
    "alias_id": "Jury-Oracle-202"
  }
  ```
* **Response (201 Created):**
  ```json
  {
    "message": "User registered successfully",
    "user_id": 15
  }
  ```

### Import CSV Competitors List
* **Endpoint:** `POST /api/admin/import-competitors-csv`
* **Headers:** `Authorization: Bearer <token>` (Admin only)
* **Request Format:** Multipart Form-Data (file parameter named `file`)
* **Response (200 OK):**
  ```json
  {
    "message": "Successfully imported 24 competitors and created tasks associations."
  }
  ```

---

## 3. Notebooks & Submission Service

### Parse Jupyter Notebook
* **Endpoint:** `POST /api/challenges/<int:challenge_id>/parse-notebook`
* **Headers:** `Authorization: Bearer <token>` (Student registered for challenge, Jury, Admin)
* **Request Format:** Multipart Form-Data (file parameter named `file`)
* **Response (200 OK):**
  ```json
  {
    "filename": "heuristic_model.ipynb",
    "cells": [
      {
        "id": 0,
        "type": "code",
        "source": "import pandas as pd\nimport numpy as np"
      },
      {
        "id": 1,
        "type": "code",
        "source": "def predict(inputs_list):\n    # # SUBMIT\n    return [1 if 'good' in x else 0 for x in inputs_list]"
      }
    ]
  }
  ```

### Submit Selected Code
* **Endpoint:** `POST /api/challenges/<int:challenge_id>/submit`
* **Headers:** `Authorization: Bearer <token>`
* **Request Body:**
  ```json
  {
    "selected_cells": [
      "def predict(inputs_list):\n    # # SUBMIT\n    return [1 if 'good' in x else 0 for x in inputs_list]"
    ],
    "task_id": 1
  }
  ```
* **Response (202 Accepted):**
  ```json
  {
    "message": "Submission received and queued for execution.",
    "submission_id": 42,
    "status": "queued"
  }
  ```
* **Response (400 Bad Request - Missing Task ID):**
  ```json
  {
    "error": "task_id is required."
  }
  ```
* **Response (400 Bad Request - AST Rule Blocked):**
  ```json
  {
    "error": "Rule Violation: Import of library 'os' is banned."
  }
  ```
* **Response (429 Too Many Requests - Daily Limit Reached):**
  ```json
  {
    "error": "Daily limit reached. You can only make 5 submissions per day."
  }
  ```

---

## 4. Leaderboard & Stats Service

### Get Leaderboard Standings
* **Endpoint:** `GET /api/tasks/<int:task_id>/leaderboard`
* **Headers:** `Authorization: Bearer <token>`
* **Response (200 OK):**
  ```json
  [
    {
      "rank": 1,
      "alias_id": "Quantum-Falcon-402",
      "public_score": 0.88,
      "execution_time_ms": 120,
      "submission_id": 42,
      "created_at": "2026-06-13T09:12:00Z"
    }
  ]
  ```

---

## 5. Live Server-Sent Events (SSE)

Real-time streaming uses standard SSE event connections:

### Live Submission Execution Updates
* **Endpoint:** `GET /api/tasks/<int:task_id>/submissions/live`
* **Headers:** `Accept: text/event-stream`
* **Returned Events:**
  * Event: `submission_status`
  * Data payload format:
    ```json
    {
      "submission_id": 42,
      "status": "running",
      "detailed_status": "running_inference",
      "logs": ["Preparing Docker image...", "Running inference split..."]
    }
    ```

### Live Leaderboard Real-Time Rank Changes
* **Endpoint:** `GET /api/tasks/<int:task_id>/leaderboard/live`
* **Headers:** `Accept: text/event-stream`
* **Returned Events:**
  * Event: `leaderboard_update`
  * Data payload format:
    ```json
    {
      "task_id": 1,
      "timestamp": "2026-06-13T09:53:00Z"
    }
    ```
