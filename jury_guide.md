# Jury Grader Complete Guide

This guide is designed for Jury members on the NAI Platform, detailing leaderboard audits, submission code reviews, execution traceback inspections, and worker node telemetry monitoring.

---

## 1. Role Capabilities & Security

Jury accounts have elevated view-only permissions to audit grading integrity and verify submission execution:
* **Competitor De-anonymization:** Students view the leaderboard with randomized aliases (e.g., `Stellar-Voyager-101`), whereas the Jury dashboard displays actual student names, class numbers, schools, and cities.
* **Submission Logging:** Access to detailed console outputs, sandbox execution logs, and runtime resource stats.
* **Diagnostics:** Telemetry data from the celery queue broker and cluster nodes.

---

## 2. Leaderboard Audits & Grading

Official challenge standings are calculated automatically by the scoring metrics pipeline:
1. Navigate to the **Leaderboard** from the navigation bar.
2. Filter the view by selecting your target Challenge and Task.
3. Ranks are based on the competitor's chosen **Final Submission** score.
4. If a competitor has not set a final selection, their highest-scoring run is NOT used automatically. They must select a run to appear on the standings.

> [!NOTE]
> Leaderboards are cached to minimize query times. Standings automatically update when a student sets or changes their final selection.

---

## 3. Reviewing Submission Details & Code

To review a submission:
1. Open the submissions dashboard.
2. Select the ID of the submission to inspect.
3. Review the code block in the center inspector window. This contains the exact combined cells parsed from the student's notebook.
4. Review the metadata panel:
   * **Priority:** Execution priority rank (1 to 9).
   * **Node:** The host name of the container node that processed the task.
   * **Execution Time:** Wall clock time (in milliseconds) used during model inference.

---

## 4. Troubleshooting Run Diagnostics

When a student’s submission fails (status `Failed`), you can inspect the error trace in the **Logs** tab:

### 1. Syntax & Entry Point Errors
* **Problem:** The student's code contains parse errors or lacks the `predict` function.
* **Log Sample:**
  ```python
  AttributeError: Your notebook code must define a function 'predict(inputs_list)' that takes a list of data points and returns predictions.
  ```
* **Solution:** Advise the student to correct the syntax or ensure their notebook contains a valid `def predict(inputs_list):` function definition inside their selected cells.

### 2. Time Limit Expired (Timeout)
* **Problem:** Inference took longer than the task’s allowed execution time.
* **Log Sample:**
  ```python
  TIMEOUT EXPIRED: Executed code exceeded the 150s limit.
  ```
* **Solution:** The model's time complexity is too high. The competitor must optimize loop structures, simplify pre-processing features, or select faster heuristics.

### 3. Out-Of-Memory Error (OOM)
* **Problem:** The container exceeded its allocated RAM.
* **Log Sample:**
  ```python
  Failed to execute Docker command: Container killed by Out-Of-Memory (OOM) agent.
  ```
* **Solution:** The student's model is loading too many weights or allocating excessive memory space in arrays. Recommend reducing dictionary sizes or cleaning up cache variables.

---

## 5. Live Cluster Resources Monitoring

In the Navbar, click the **Cluster** badge to inspect active system resource allocations:
* **Node Name:** Connected Celery worker host ID (e.g. `celery@worker-node-1`).
* **Concurrency:** The maximum number of tasks the worker can process concurrently.
* **GPU Model & VRAM:** Connected host graphics card and VRAM availability.
* **Status indication:** A green pulsing indicator represents active communication with the rabbitmq/redis broker; a red indicator means a node is unresponsive or has lost network connection.
