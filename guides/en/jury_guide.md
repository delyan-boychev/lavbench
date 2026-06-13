# Jury & Grader Complete Guide

Welcome to the NAI Platform Jury Portal. Your elevated access allows you to monitor cluster health, audit code integrity, provide manual scoring assessments, and export verified results.

## Table of Contents
1. [Role Capabilities & Privacy Constraints](#1-role-capabilities--privacy-constraints)
2. [Leaderboard Auditing & Manual Points](#2-leaderboard-auditing--manual-points)
3. [Submission Diagnostics & Code Review](#3-submission-diagnostics--code-review)
4. [Post-Finalization Audits & Reporting](#4-post-finalization-audits--reporting)
5. [Cluster Telemetry](#5-cluster-telemetry)

---

## 1. Role Capabilities & Privacy Constraints

Jury members act as impartial referees during the competition lifecycle.
* **Double-Blind Anonymization:** While the competition is active, competitors see only pseudonyms (e.g., `Stellar-Voyager-101`). As a Jury member, your dashboard reveals the competitor's true identity, school, and demographics for verification purposes.
* **Access Control:** You cannot modify task constraints or Docker environments, but you have full read access to student code and system logs.

---

## 2. Leaderboard Auditing & Manual Points

The Leaderboard computes real-time standings based on automated metric evaluations and your manual scoring inputs.

### Applying Manual Points
Certain tasks require subjective evaluation (e.g., code efficiency, mathematical elegance). 
1. Navigate to the **Leaderboard**.
2. Locate the competitor and the specific task column.
3. Click the score field to open the manual input modifier.
4. Input a value between `0` and `100`. The change saves automatically on blur (`Enter` or clicking away).
> [!WARNING]
> **Constraint Check:** The system strictly rejects manual point assignments if the competitor has not made at least one valid, completed submission for the selected task. You cannot score empty entries.

### Tie-Breaking Logic
In the event two competitors hold the exact same mathematical score, the system automatically resolves the tie by ranking the submission with the fastest `execution_time_ms`, or if execution times match, the earliest `created_at` timestamp.

---

## 3. Submission Diagnostics & Code Review

Monitor the queue to identify struggling students or broken tasks.

### Reviewing a Code Run
1. Open the **Submissions** tab.
2. Select an entry to expand its metadata. 
3. The UI provides a syntax-highlighted inspector for the exact code cells extracted from the student's notebook.

### Common Error Triage
* **AttributeError ('predict' missing):** The student forgot to name their entry function `predict(inputs_list)` or failed to apply the `# SUBMIT` tag to the correct cell.
* **TIMEOUT EXPIRED:** The execution exceeded the wall-clock limit. Advise the student to optimize their algorithm complexity.
* **Out-Of-Memory (OOM):** The Docker container was killed by the OS. The student's dataset handling or matrix allocations are too large for the task's RAM constraint.

---

## 4. Post-Finalization Audits & Reporting

Once a competition reaches `scores_finalized=True`, standard submissions and scoring lock.

### Making Score Corrections (Audit Trail)
If a manual scoring mistake is identified after finalization:
1. Click the manual score cell on the finalized leaderboard.
2. A **Correction Modal** will appear.
3. You must provide a mandatory textual **Reason/Justification** for the change.
4. The system logs your Admin ID, the user, the old/new scores, and the justification to a permanent `AuditLog` table.

### Exporting Final Results
To generate documentation for awards or external review:
* Navigate to the Challenge settings and click **Export Comprehensive Report**.
* This triggers a secure `GET /export-results` request, downloading a detailed CSV/Excel file containing true identities, highest public/private scores, all manual points, final calculated rankings, and the appended Post-Finalization Audit Log.

---

## 5. Cluster Telemetry

Use the **Cluster** navigation badge to monitor the health of remote execution nodes.
* **Node Status:** Green indicates a healthy connection to the Redis broker; Red indicates a disconnected or crashed remote worker.
* **Capacity:** Review the active concurrency limits and available GPU VRAM across the worker fleet to anticipate processing delays during high-volume submission periods.