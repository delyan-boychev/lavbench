# Jury Portal Complete Guide

Welcome to the LavBench Platform Jury Portal. As a member of the competition jury, you oversee competition progress, register competitors, inspect live submission logs, audit task environment build statuses, analyze custom evaluator metrics, conduct score audits, and issue final competition results.

---

## Table of Contents

1. [Jury Role and Permission Matrix](#1-jury-role-and-permission-matrix)
2. [Challenge Assignment and JuryChallenge Mapping](#2-challenge-assignment-and-jurychallenge-mapping)
3. [Competitor Onboarding and PDF Credential Slips](#3-competitor-onboarding-and-pdf-credential-slips)
4. [Live Submission Tracking and Baseline Verification](#4-live-submission-tracking-and-baseline-verification)
5. [Task Environment Build Error Diagnostics](#5-task-environment-build-error-diagnostics)
6. [Custom Evaluator Scoring and Leaderboard Inspection](#6-custom-evaluator-scoring-and-leaderboard-inspection)
7. [Manual Scoring and Score Justification Audit Trail](#7-manual-scoring-and-score-justification-audit-trail)
8. [Competitor Disqualification and Data Exports](#8-competitor-disqualification-and-data-exports)

---

## 1. Jury Role and Permission Matrix

Jury members possess specialized operational privileges to manage competitors, review submissions, and audit scores without full administrative system privileges.

### Permission Comparison Matrix

| Feature / Action | Jury Role | Administrator Role |
| :--- | :--- | :--- |
| View assigned competition submissions, code cells & execution logs | **Yes** | **Yes** |
| Register individual competitors & perform bulk CSV onboarding | **Yes** | **Yes** |
| Generate printable PDF credential slips (`/api/admin/.../credentials-pdf`) | **Yes** | **Yes** |
| Reset competitor credentials & passwords | **Yes** | **Yes** |
| Monitor live submission progress via SSE & inspect cluster telemetry | **Yes** | **Yes** |
| Inspect baseline solutions (`is_baseline`) | **Yes** | **Yes** |
| Disqualify submissions or competitors (`is_disqualified`) | **Yes** | **Yes** |
| Assign manual score points (0–100) per task | **Yes** | **Yes** |
| Edit finalized scores with mandatory audit justifications | **Yes** | **Yes** |
| Download Scores CSV and Submissions ZIP archives | **Yes** | **Yes** |
| Create, edit, or delete challenges, stages, tasks, or Docker images | **No** | **Yes** |
| Manage admin or jury user accounts | **No** | **Yes** |
| Trigger database backups or configure worker nodes | **No** | **Yes** |

---

## 2. Challenge Assignment and JuryChallenge Mapping

### Access Scoping via `JuryChallenge`

Access for jury members is strictly controlled by explicit challenge assignments:

- A jury member is linked to specific competitions via the **`JuryChallenge`** mapping database model.
- Upon logging into `/admin` or navigating competition views, jury members can only see and access competitions explicitly assigned to their account.
- Competitions not assigned to the jury member via `JuryChallenge` remain completely hidden and return HTTP 403 Forbidden if accessed directly.

---

## 3. Competitor Onboarding and PDF Credential Slips

### CSV Bulk Competitor Onboarding

Jury members can register entire student cohorts or competition teams in bulk using CSV files.

#### CSV Header Format:
```csv
name,surname,middle_name,birth_date,grade,school,city
```

#### Optional Header Fields:
`email` and `is_anonymous` may be included in the CSV header.

#### Example CSV Payload:
```csv
name,surname,middle_name,birth_date,grade,school,city,email,is_anonymous
Alice,Smith,Ivanova,2008-05-12,11,Tech High,Sofia,alice@example.com,false
Bob,Jones,Petrov,2007-09-20,12,Math Gym,Plovdiv,,false
```

### Generating Printable Credential PDF Slips

For on-site live competitions, jury members can generate printable paper slips:

1. Open **Admin Panel** → **User Management** (or **Competitor Registration**).
2. Select the target challenge and click **Print Credentials PDF**.
3. The server invokes `/api/admin/challenges/<id>/credentials-pdf` and returns a formatted PDF document.
4. Each printable slip includes the competitor's real name, assigned alias, username, auto-generated password, login URL, and QR code.

---

## 4. Live Submission Tracking and Baseline Verification

### Double-Blind Privacy Protections

The platform enforces double-blind privacy controls during active competition:

- **Private Score Access**: Jury members **CAN view `private_score`** values and private metric breakdowns on both the Leaderboard and Submission detail views at all times. (Only competitors are shielded from private scores until competition finalization).
- **Competitor Anonymity (`double_blind=True`)**: When double-blind mode is enabled for a competition, Jury members see competitor **pseudonyms/aliases** (`alias_id`) during active competition. Real competitor names (`name`, `surname`, `email`) remain hidden from Jury until the competition is officially **Finalized** (`scores_finalized=True`). (Admins can view real names at all times).

### Live Submission Log Streaming

1. Navigate to the **Submissions** tab.
2. View real-time state changes (`Queued` → `Running` → `Evaluating` → `Completed` / `Failed`).
3. Click any submission entry to expand details:
   - Concatenated Python code cells executed in the container.
   - Real-time stdout and stderr execution logs streaming from the worker sandbox.
   - Execution duration and memory usage telemetry.

### Baseline Solution Verification (`is_baseline`)

Jury members can review organizer baseline submissions:
- Baseline entries are flagged with `is_baseline=True`.
- Reviewing baseline runs enables the jury to verify that dataset paths, evaluation metric scripts, and starter baseline notebooks execute without error prior to competition launch.

---

## 5. Task Environment Build Error Diagnostics

During competition monitoring, jury members must quickly identify whether submission issues stem from competitor code defects or platform environment failures.

### Distinguishing Build Errors from Competitor Submission Errors

| Diagnostic Parameter | Competitor Submission Error | Task Environment Build Error (`ERR_IMAGE_BUILD_FAILED`) |
| :--- | :--- | :--- |
| **Failure Scope** | Isolated to a single competitor submission or notebook file. | Affects **all** competitor submissions for the target task. |
| **Status Indicator** | Marked as `Failed` on the submission list view. | Task environment badge displays red pill **`ERR_IMAGE_BUILD_FAILED`**. |
| **Root Causes** | Syntax errors, unhandled Python exceptions, missing `submission.parquet`, kernel OOM, or wall-clock runtime timeouts. | Invalid APT packages, Pip requirement version conflicts, base image pull failures, or Hugging Face dataset download timeouts. |
| **Log Locations** | **Submission Execution Logs** tab (notebook stdout/stderr output inside container). | **Task Overview Build Logs** or worker log feed (`[build lavbench_task_<id>]`). |
| **Quota Impact** | Competitor submission quota is decremented (unless AST syntax validation caught it pre-execution). | Competitor submission quota **is NOT decremented** or should be manually restored if affected. |

---

### Step-by-Step Guide for Inspecting Execution & Build Logs

When troubleshooting a failed submission or blocked task queue:

1. **Check Task Environment Status**:
   - Open **Task Overview** or **Submissions** tab.
   - Look for the environment indicator pill. If it reads **`ERR_IMAGE_BUILD_FAILED`**, the task image failed to compile on the worker.
2. **Inspect Submission Logs**:
   - Click the failed submission row to open the submission detail modal.
   - Select **Execution Logs** to examine stdout/stderr output produced during container execution.
   - If the log indicates `Docker image lavbench_task_<id> not found` or `Environment setup failed`, the issue is a task environment failure.
3. **Escalation Protocol to System Administrators**:
   - When a task environment build failure occurs, copy the build error snippet from the submission log or task overview.
   - Request an administrator to inspect **Task Settings** → **Environment Logs**, clear stuck build locks, or trigger **"Rebuild Task Environment"**.

---

## 6. Custom Evaluator Scoring and Leaderboard Inspection

For tasks employing custom evaluation scripts (`evaluator.py`), jury members must understand how score values are computed and presented across the platform.

### Custom Evaluator Scoring Logic

Custom evaluators run dynamic Python functions (`evaluate(predictions_df, labels_df, options)`) inside the worker environment:

- **Primary Metric Output**: The score value associated with `METRIC_NAME` forms the competitor's primary task score.
- **Directionality Convention**: All evaluation metrics on LavBench are normalized such that **higher values represent better performance**.
- **Secondary Metrics**: Custom scripts may compute auxiliary indicators (e.g., `raw_accuracy`, `latency_penalty`, `f1_score`, `precision`).

---

### Viewing Custom Metrics on Leaderboard & Submission Views

1. **Public Leaderboard View**:
   - Displays the primary score key (`METRIC_NAME`) for each competitor's best submission per task.
   - Columns dynamically update based on task configuration.
2. **Submission Detail Modal View**:
   - Clicking any completed submission entry opens the full evaluation report.
   - Under **Metric Breakdown**, jury members can inspect all primary and secondary metric values returned by the custom `evaluate()` function in JSON key-value format.

---

### Verifying Baseline Solutions (`is_baseline=True`)

Jury members should verify custom evaluator scoring using organizer baseline runs:
- Ensure the baseline entry displays non-zero, plausible metric values on the leaderboard.
- Validate that secondary metric keys align with competition rules before competition launch.

---

## 7. Manual Scoring and Score Justification Audit Trail

### Assigning Manual Score Points (0–100)

For tasks incorporating subjective or qualitative evaluation (e.g., code efficiency review, architecture analysis):

1. Open the **Leaderboard** tab.
2. Locate the competitor row and task column.
3. Click the score field to open the manual scoring input modal.
4. Enter a point value between **0 and 100**.
5. Save the score — it will be weighted into the competitor's composite stage total according to task rules.

> [!NOTE]
> Manual scoring requires at least one completed submission for the corresponding task.

### Post-Finalization Score Modifications & Audit Justifications

Once a competition transitions to the **Finalized** state (`scores_finalized=True`), leaderboard rankings lock. If a score correction is required (e.g., post-competition appeal review):

1. Clicking a score cell opens the **Audit Justification Modal**.
2. The jury member must enter a textual justification reason.
3. Upon confirmation, the backend records an immutable log entry in the **`AuditLog`** table containing:
   - Jury User ID & Role
   - Target Competitor & Submission ID
   - Original Score vs Updated Score
   - ISO Timestamp
   - Textual Justification Reason

---

## 8. Competitor Disqualification and Data Exports

### Competitor & Submission Disqualification (`is_disqualified`)

If a competitor violates rules (e.g., unauthorized collaboration, attempted container escape, system abuse):

1. Jury members or admins can flag individual submissions or competitor accounts as disqualified (`is_disqualified=True`).
2. Disqualified entries are immediately excluded from official standings and highlighted on the jury dashboard.

### Data Exports

Jury members can export competition artifacts at any time:

- **Scores CSV**: Click **Download Scores CSV** in Challenge Management to obtain a CSV containing final ranks, real names, pseudonyms, task scores, manual points, and total scores.
- **Submissions ZIP**: Click **Download Submissions ZIP** to download a compressed archive containing all successfully evaluated competitor Jupyter notebooks (`.ipynb`).
