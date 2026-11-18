# Jury Portal Complete Guide

Welcome to the LavBench Platform Jury Portal. As a member of the competition jury, you oversee competition progress, register competitors, inspect live submission logs, audit task environment build statuses, analyze custom evaluator metrics, conduct score audits, and issue final competition results.

---

## Table of Contents

1. [Jury Role and Permission Matrix](#1-jury-role-and-permission-matrix)
2. [Challenge Assignment and JuryChallenge Mapping](#2-challenge-assignment-and-jurychallenge-mapping)
3. [Competitor Onboarding and One-Time Credential Slips](#3-competitor-onboarding-and-one-time-credential-slips)
4. [Live Submission Tracking and Baseline Verification](#4-live-submission-tracking-and-baseline-verification)
5. [Task Environment Build Error Diagnostics](#5-task-environment-build-error-diagnostics)
6. [Custom Evaluator Scoring and Leaderboard Inspection](#6-custom-evaluator-scoring-and-leaderboard-inspection)
7. [Manual Scoring and Score Justification Audit Trail](#7-manual-scoring-and-score-justification-audit-trail)
8. [Data Exports](#8-data-exports)
9. [Student Workspaces (nanoColab)](#9-student-workspaces-nanocolab)
10. [Task Evaluation Modes](#10-task-evaluation-modes)

---

## 1. Jury Role and Permission Matrix

Jury members possess specialized operational privileges to manage competitors, review submissions, and audit scores without full administrative system privileges.

### Permission Comparison Matrix

| Feature / Action | Jury Role | Administrator Role |
| :--- | :--- | :--- |
| View assigned competition submissions, code cells & execution logs | **Yes** | **Yes** |
| Register individual competitors & perform bulk CSV onboarding | **Yes** | **Yes** |
| Bulk password reset and its credentials file | **No** | **Yes** |
| Reset competitor credentials & passwords | **Yes** | **Yes** |
| Monitor live submission progress & inspect the system status panel (workers, queues) | **Yes** | **Yes** |
| Inspect baseline solutions (`is_baseline`) | **Yes** | **Yes** |
| Assign manual score points (0–100) per task | **Yes** | **Yes** |
| View private scores before the results are finalised | **No** | **Yes** |
| Edit finalized scores with mandatory audit justifications | **Yes** | **Yes** |
| Finalize a stage or the whole competition (locks the ranking) | **Yes** | **No** |
| Download Scores CSV and Submissions ZIP archives | **Yes** | **Yes** |
| Create, edit, or delete challenges, stages, tasks, or Docker images | **No** | **Yes** |
| Manage admin or jury user accounts | **No** | **Yes** |
| Trigger database backups or configure worker nodes | **No** | **Yes** |
| View student workspaces (nanoColab): status, details and the workspace list | **Yes** | **Yes** |
| Set up, publish or extend student workspaces | **No** | **Yes** |

---

## 2. Challenge Assignment and JuryChallenge Mapping

### Access Scoping via `JuryChallenge`

Access for jury members is strictly controlled by explicit challenge assignments:

- A jury member is linked to specific competitions via the **`JuryChallenge`** mapping database model.
- Upon logging into `/admin` or navigating competition views, jury members can only see and access competitions explicitly assigned to their account.
- Competitions not assigned to the jury member via `JuryChallenge` remain completely hidden and return HTTP 403 Forbidden if accessed directly.
- An administrator creates jury accounts and must assign at least one competition, both when creating and when editing the account.

---

## 3. Competitor Onboarding and One-Time Credential Slips

### CSV Bulk Competitor Onboarding

Jury members can register entire student cohorts or competition teams in bulk using CSV files.

#### CSV Header Format:
```text
name,surname,middle_name,birth_date,grade,school,city
```

#### Optional Header Fields:
`email` and `is_anonymous` may be included in the CSV header.

#### Example CSV Payload:
```text
name,surname,middle_name,birth_date,grade,school,city,email,is_anonymous
Alice,Smith,Ivanova,2008-05-12,11,Tech High,Sofia,alice@example.com,false
Bob,Jones,Petrov,2007-09-20,12,Math Gym,Plovdiv,,false
```

In **Competitor Registrations**, the **Manual Competitor Registration** and **Import Competitors CSV** forms show each problem (for example a missing competition or file) under its field. **Edit** on a registered competitor opens an editor in place of the list, with **Back** and **Cancel**, and **Save Changes** at the bottom; with unsaved changes, leaving asks "Discard unsaved changes?".

### Generating Printable Credential Slips

For on-site live competitions, an administrator generates the credential slips with a bulk
password reset (**Admin Panel** → **Competitor Registrations** → **Reset All Passwords in
Challenge**, then the competition in the dialog). The browser saves a CSV with each competitor's name, username and new password, and
the server keeps no copy. Only administrators can run it, so jury members never hold working
credentials for competitors; ask an administrator when slips are needed.

---

## 4. Live Submission Tracking and Baseline Verification

### Double-Blind Privacy Protections

The platform enforces double-blind privacy controls during active competition:

- **Private Score Access**: Jury members see `private_score` values and private metric breakdowns only once a task's scores are final: when its stage or the whole competition is **Finalized**. Until then the Leaderboard, the submission lists and the submission detail show public scores only, so private results cannot steer manual points. Admins see private scores at all times; competitors see them once the results are finalised and revealed.
- **Competitor Anonymity (`double_blind=True`)**: When double-blind mode is enabled for a competition, Jury members see competitor **pseudonyms/aliases** (`alias_id`) during active competition. Real competitor names (`name`, `surname`, `email`) remain hidden from Jury until the competition is officially **Finalized** (`scores_finalized=True`). (Admins can view real names at all times).

### Live Submission Log Streaming

1. Navigate to the **Submissions** tab.
2. View real-time state changes (`Queued` → `Running` → `Evaluating` → `Completed` / `Failed`).
   A failure caused by the platform rather than the competitor's code (the submission could not be
   enqueued, no worker took it, its worker was lost, or the environment could not be prepared) also
   shows a **Platform error** badge (`failed_infra`); it never counts toward the competitor's limits.
3. Click any submission entry to show it in the submission viewer, which scrolls into view when it is below the list (on narrow screens):
   - The code cells executed in the container (**Submitted Code**).
   - The **Execution Log**: stdout and stderr streaming live from the worker sandbox while it runs, the stored log once it has finished.
   - **Timing**: **Execution**, the sandbox run of a notebook task, and **Evaluation**, the scoring of any task. Competitors see only the execution time; neither time affects the ranking.
   - A badge with how the submission arrived: **Cells** (a notebook task), **Workspace** or **Emergency upload** (a file task).

### File-Task Submissions

A file task scores the `submission.parquet` a student submits from the workspace, together with the `solution.ipynb` that made it. In the submission's details, **Submitted files** shows:

1. the time, the size of `submission.parquet` and the SHA-256 of both files, to check that a file is the one the student sent;
2. **Download Parquet** and **Download notebook**. While the competition is double-blind, the files are named after the student's alias, for example `Quiet-Owl_image-classification_sub_<id>.parquet`.

### Baseline Solution Verification (`is_baseline`)

Jury members can review organizer baseline submissions:
- Baseline entries are flagged with `is_baseline=True`.
- Reviewing baseline runs enables the jury to verify that dataset paths, evaluation metric scripts, and starter baseline notebooks execute without error prior to competition launch.
- Baseline runs are queued ahead of every competitor submission, like admin and jury test runs.
- A baseline that ends with a **Platform error** (`failed_infra`) is retried automatically as a new baseline run, at most 2 times; each attempt stays in the submission list with its own logs. A baseline that fails, is killed or is cleared from the queue (or whose last retry fails) sets `ERR_BASELINE_FAILED` on the task, which blocks competitor submissions until a later baseline run completes.

---

## 5. Task Environment Build Error Diagnostics

During competition monitoring, jury members must quickly identify whether submission issues stem from competitor code defects or platform environment failures.

### Distinguishing Build Errors from Competitor Submission Errors

| Diagnostic Parameter | Competitor Submission Error | Task Environment Build Error (problem registry) |
| :--- | :--- | :--- |
| **Failure Scope** | Isolated to a single competitor submission or notebook file. | Affects **all** competitor submissions for the target task. |
| **Status Indicator** | Marked as `Failed` on the submission list view. | Task shows a warning indicator; problem codes like `ERR_TASK_BUILD_FAILED` or `ERR_BASELINE_FAILED` are listed in the task overview. Submissions are blocked with `ERR_TASK_NOT_READY`. |
| **Root Causes** | Syntax errors, unhandled Python exceptions, missing `submission.parquet`, kernel OOM, or wall-clock runtime timeouts. | Invalid APT packages, Pip requirement version conflicts, or base image pull failures. |
| **Log Locations** | **Execution Log** in the submission viewer (notebook stdout/stderr output inside container). | **Task Overview** problems banner or worker log feed (`[build lavbench_task_<id>]`). |
| **Quota Impact** | The submission counts toward the competitor's limits. A notebook rejected by AST validation creates no submission and does not count. | Submissions are blocked before they are created, so nothing counts. A run that failed on the platform's side (**Platform error**, `failed_infra`) never counts either. |

---

### Step-by-Step Guide for Inspecting Execution & Build Logs

When troubleshooting a failed submission or blocked task queue:

1. **Check Task Environment Status**:
   - Open **Task Overview** or **Submissions** tab.
   - Look for the environment warning indicator. If the problem registry lists **`ERR_TASK_BUILD_FAILED`**, the task image failed to compile on the worker; **`ERR_BASELINE_FAILED`** means the baseline run failed, was killed or was cleared from the queue.
2. **Inspect Submission Logs**:
   - Click the failed submission row to show it in the submission viewer.
   - Read its **Execution Log** to examine stdout/stderr output produced during container execution.
   - If the log indicates `Docker image lavbench_task_<id> not found` or `Environment setup failed`, the issue is a task environment failure.
3. **Escalation Protocol to System Administrators**:
   - When a task environment build failure occurs, copy the build error snippet from the submission log or task overview.
   - Ask an administrator to fix the task's environment settings. Saving the fix queues a new baseline run about 60 seconds after the last change, and its success clears the task's build and baseline problem codes.

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
2. **Submission Viewer**:
   - Clicking any completed submission entry on the **Submissions** page shows it in the submission viewer, which scrolls into view.
   - The viewer shows the **Public Score** (and the **Private Score** once the scores are final), the execution log and the submitted code.

---

### Verifying Baseline Solutions (`is_baseline=True`)

Jury members should verify custom evaluator scoring using organizer baseline runs:
- Ensure the **Baseline** row on the task's leaderboard tab displays non-zero, plausible metric values. The row has no rank, never appears on the general or stage tabs, and is hidden once the results are finalized and revealed.
- Validate that secondary metric keys align with competition rules before competition launch.

---

## 7. Manual Scoring and Score Justification Audit Trail

### Assigning Manual Score Points (0–100)

For tasks incorporating subjective or qualitative evaluation (e.g., code efficiency review, architecture analysis):

1. Open the **Leaderboard** tab.
2. Locate the competitor row and task column.
3. Click the points (with a pencil icon, for example **0 pts**). The **Grading Competitor** dialog opens.
4. Enter a point value between **0 and 100**, with up to 2 decimal places (e.g. `87.5` or `12.25`). An invalid value is shown under the field.
5. Click **Save** or press Enter in the points field — the score will be weighted into the competitor's composite stage total according to task rules.

> [!NOTE]
> Manual scoring requires at least one completed submission for the corresponding task.

### Finalizing a Stage or the Competition

1. Open **Manage Competitions & Tasks**. A stage that has ended shows **Finalize** on its row; a competition that has ended shows **Finalize** on its card, available once every stage is finalized.
2. Click **Finalize**. A dialog opens over the list (**Finalize Stage** or **Finalize Competition** with its title).
3. Choose with the switch whether competitors see the results now (for a stage: **Reveal results and points to competitors (otherwise finalization is jury-internal only)**, on by default; for the competition: **Reveal private scores and competitor identities immediately**, off by default).
4. Click **Finalize Stage** or **Finalize** to confirm, or **Cancel**.

### Post-Finalization Score Modifications & Audit Justifications

Jury members and admins can both assign and change manual points; every change is recorded in the audit log.

Once a competition transitions to the **Finalized** state (`scores_finalized=True`), leaderboard rankings lock. If a score correction is required (e.g., post-competition appeal review):

1. Clicking the points opens the same **Grading Competitor** dialog, now with a mandatory **Reason / Changelog note** field.
2. The jury member or admin must enter a textual justification reason; without it the dialog does not save and shows the message under the field.
3. Upon confirmation, the backend records an immutable log entry in the **`AuditLog`** table containing:
   - The acting jury member's or admin's user ID
   - Target Competitor & Submission ID
   - Original Score vs Updated Score
   - ISO Timestamp
   - Textual Justification Reason

---

## 8. Data Exports

Exports are available only once the results allow it:

- **Scores CSV**: Click **Download Scores CSV** in Challenge Management once the competition is **Finalized**; before that the download is refused (`ERR_SCORES_NOT_FINALIZED`). The CSV lists ranks, pseudonyms, real names, usernames, emails, schools, cities, grades, the score per task (the private score where one exists) and the total.
- **Submissions ZIP**: Click **Download Submissions ZIP** once the competition (or, for a single stage, that stage) has ended or been finalised. Until the competition is finalised the notebooks are anonymised.

---

## 9. Student Workspaces (nanoColab)

When the platform is connected to nanoColab, students can work in a JupyterLab workspace per stage, or per competition when it has no stages. The jury sees the workspaces read-only; only administrators set them up, publish and extend them.

- **Where:** click **Workspaces** on the competition card in **Manage Competitions & Tasks**. The view lists each stage, or the whole competition when it has no stages, opening at its top; **Back** returns to the competition card.
- **Status chip and phase line:** the same as the administrators see. The chip is **Off**, **Uploading**, **Preparing**, **Ready**, **Problem** or **Unknown**, with how old the status is ("Checked 20 seconds ago"); the line under the stage's title gives the phase, for example "Not published - opens ...", "Not published yet" (the start has passed without a publish), "Open - closes ..." or "Ended ...". For a problem the jury sees the reason without nanoColab's technical details; ask an administrator to fix it.
- **Facts:** **Open** (the window, its end including the grace period), **Image** (by name), **Machine** (vCPU, memory and disk), **Places** and **Task folders**; **More details** shows **Keep archives until**. The jury has no **Publish**, **Extend** or **Edit settings** buttons.
- **Show student workspaces:** every registered student with **First opened** (or **Not opened**), **Last opened** and the **Latest submission**. While the competition is double-blind, students appear by alias only.

---

## 10. Task Evaluation Modes

Jury members create and edit tasks like administrators. The task editor starts with **Evaluation mode**: **Notebook** (the student's selected cells run in the sandbox) or **File** (the student's `submission.parquet` is scored directly). The steps are in the administrator guide, section 11; in short:

- A file task needs `labels.parquet` and `baseline_submission.parquet` in **Hidden: labels, baseline submission**; a notebook task needs `labels.parquet` there and a baseline notebook in **Students get these**. A missing file shows under **Task Problems** until it is uploaded; until then the task refuses every submission, your test runs included.
- Saving sends the settings and notebooks first; the **Uploads** list at the top of the editor then removes the files marked for deletion and uploads the data files and the Hugging Face ZIP, one at a time, with progress, **Cancel** and **Retry** per row (administrator guide, "The Upload List").
- The **Environment** tab holds the task's **Hugging Face data**, one ZIP of `models/<org>/<name>` and `datasets/<org>/<name>` folders (administrator guide, section 3). The jury can upload and remove it like an administrator until the workspaces are published; **Remove** takes effect on **Save Changes**.
- The mode is locked once a competitor has submitted.
- After the workspaces are published, the folder and the public files are fixed, and only an administrator can replace hidden files or the evaluator. The jury sees **Reason for changing hidden files** disabled; ask an administrator for such a fix.
- Assigned jury members can download every task file, hidden ones included, at any time.

