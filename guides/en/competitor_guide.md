# Competitor Complete Guide

Welcome to the LavBench Platform! This guide walks you through everything you need to compete — from logging in to navigating competition stages, submitting Jupyter notebooks, monitoring real-time execution logs, and marking your final selected submission.

---

## Table of Contents

1. [Getting Started and Interface Navigation](#1-getting-started-and-interface-navigation)
2. [Stage and Task Overview](#2-stage-and-task-overview)
3. [Baseline Notebooks and Output Schema](#3-baseline-notebooks-and-output-schema)
4. [Notebook Submission Workflow and AST Pre-Validation](#4-notebook-submission-workflow-and-ast-pre-validation)
5. [Submission Pipeline and Live Streaming Logs](#5-submission-pipeline-and-live-streaming-logs)
6. [Leaderboard, Double-Blind Privacy and Final Selection](#6-leaderboard-double-blind-privacy-and-final-selection)
7. [Troubleshooting and Error Matrix](#7-troubleshooting-and-error-matrix)
8. [Your Workspace (nanoColab)](#8-your-workspace-nanocolab)
9. [File Tasks: Submitting from the Workspace](#9-file-tasks-submitting-from-the-workspace)

---

## 1. Getting Started and Interface Navigation

### Logging In

1. Open the LavBench web application in your browser.
2. Enter the account username and password provided by your competition organizer or jury.
3. Upon authentication, you will be redirected to the main competition dashboard.

### The Competition Bar

The top competition bar provides primary navigation across competition sections:

- **Competition Selector**: Displays your assigned competition.
- **Stage Selector Bar**: Switch between multi-stage phases (e.g., *Qualification*, *Finals*).
- **Navigation Tabs**:
  - **Challenge**: View stage task descriptions, dataset assets, baseline notebooks, and submission upload controls.
  - **Leaderboard**: View anonymized scores, ranking, and task breakdowns.
  - **Submissions**: Track your submission history, execution logs, and final selection stars.

### The Countdown Timer

The countdown timer in the navbar displays remaining competition or stage time:

| Timer Color State | Remaining Time / Status | Behavior & Guidelines |
| :--- | :--- | :--- |
| **Green** | > 30 minutes | Competition phase actively open; plenty of remaining execution window. |
| **Yellow** | 15 to 30 minutes | Closing phase approaching; finish model training and test inference scripts. |
| **Red** | ≤ 15 minutes | Final submission window; submit candidate notebooks. |
| **Flashing Red** | ≤ 5 minutes | Deadline imminent; upload final notebooks immediately. |
| **Orange** | **Grace Period Active** | The official deadline has passed. For 3 more minutes (the grace period) new submissions are still accepted. |

> [!WARNING]
> Once the 3-minute grace period ends, new submissions are rejected. A submission accepted during the grace period still runs to the end, and you can follow it and see its result like any other.

---

## 2. Stage and Task Overview

### Stage Selector Navigation

Competitions on LavBench can feature multiple stages (e.g., *Stage 1 - Feature Engineering*, *Stage 2 - Fine-Tuning*). 
- Use the **Stage Selector** tab bar on the **Challenge** page to navigate between active stages.
- Each stage exposes its own start/end countdown deadlines and assigned machine learning tasks.

### Task Specifications and Rules

Clicking a task displays full details (on a narrow screen such as a phone, the page scrolls down to them):
- **Problem Description & Rules**: Target objectives, input formats, evaluation metric weighting.
- **Resource Allocations**: Container memory cap (RAM), wall-clock time limit, GPU hardware accelerator requirement, CPU core allocation.
- **Security & Import Rules**: Banned modules (e.g., `os, sys, subprocess, requests`) or strict whitelisted libraries.
- **Submission Limits**: a maximum number of submissions per day for the competition, and optionally a per-task limit over a period of hours. The daily count resets at midnight in the competition's timezone.
- **Downloadable Assets**: Training/test datasets and starter baseline notebooks.
- **Hugging Face data**: models and datasets the organisers prepared for the task, listed with the path your notebook opens them by (see [Hugging Face Models and Datasets](#hugging-face-models-and-datasets)).

> [!NOTE]
> `labels.parquet` contains hidden ground-truth target values and is strictly kept server-side inside evaluation nodes.

---

## 3. Baseline Notebooks and Output Schema

### Baseline Notebook Usage

Each task includes an official **Baseline Notebook** downloadable directly from the task assets panel (`baseline_task_X.ipynb`).

- The baseline notebook provides starter code for loading test data, initializing standard baselines, and building the required output format.
- The cell generating `submission.parquet` is pre-configured with the exact required schema. **Do not modify the schema generation structure in this cell.**

### Output File Schema (`submission.parquet`)

Your submitted code must write a file named exactly **`submission.parquet`** into the current working directory.

#### Required Columns:
1. **`id`**: Integer identifiers exactly matching row order and keys of the test dataset.
2. **Prediction Column(s)**: Model predictions matching target column names specified in task details (e.g., `prediction`, `label`, class probabilities).

### Python Schema Code Examples

#### Single Target Classification / Regression:
```python
import pandas as pd

# Load test dataset
test_df = pd.read_csv("test.csv")

# Run inference with your trained model
predictions = model.predict(test_df)

# Construct submission DataFrame
submission = pd.DataFrame({
    "id": test_df["id"],
    "prediction": predictions
})

# Save to parquet (must disable index)
submission.to_parquet("submission.parquet", index=False)
```

#### Multi-Column / Probabilistic Output:
```python
# Multi-class probability predictions
prob_scores = model.predict_proba(test_df)

submission = pd.DataFrame({
    "id": test_df["id"],
    "prob_class_0": prob_scores[:, 0],
    "prob_class_1": prob_scores[:, 1],
    "prob_class_2": prob_scores[:, 2]
})

submission.to_parquet("submission.parquet", index=False)
```

---

## 4. Notebook Submission Workflow and AST Pre-Validation

### Step-by-Step Submission Process

1. Download task datasets and the starter baseline notebook.
2. Develop your ML pipeline locally or in your Jupyter environment.
3. In the **Submit Solution** panel of the task, click **Upload Jupyter Notebook (.ipynb)** (or drag the file onto it) and select your `.ipynb` file (max 16 MB, including saved outputs such as plots).
4. **Cell Selection Workflow**:
   - The cells of your notebook appear under the upload area (**Select Cells**). Cells marked `# SUBMIT` are selected automatically; **Select all code** selects every code cell.
   - Check the selection boxes next to the cells required for model execution and `submission.parquet` export.
   - Omit exploratory visualization cells, print statements, or unneeded training scratchpad cells.
5. Click **Submit N cells for Evaluation**.

```
[ Upload .ipynb ] ➔ [ Parse Cells ] ➔ [ Select Code Cells ] ➔ [ AST Check ] ➔ [ Queue Job ]
```

### AST Pre-Validation & Quota Preservation

Before your code is dispatched to execution workers, it undergoes server-side Static Application Security Testing (AST):

- **IPython Magic Stripping**: Shell commands (`!pip install`, `%matplotlib inline`, `%timeit`) are automatically stripped.
- **Security Inspection**: Validates syntax and checks against `banned_imports` or `whitelisted_imports`.

> [!IMPORTANT]
> **Quota Preservation**: If code fails AST pre-validation (for example, a syntax error or
> forbidden import), the request is rejected immediately with diagnostics. **No submission entry
> is created and your submission limits are not consumed.** A submission that fails because of
> the platform (shown as **Platform error**) does not count either. The daily count resets at
> midnight in the competition's timezone.

---

## 5. Submission Pipeline and Live Streaming Logs

### Submission Status Lifecycle

Track your submission progress on the **Submissions** tab:

```
┌──────────┐     ┌──────────┐     ┌────────────┐     ┌───────────┐
│  Queued  │ ──► │  Running │ ──► │ Evaluating │ ──► │ Completed │
└──────────┘     └──────────┘     └────────────┘     └───────────┘
                                                           │
                                                           ▼
                                                     ┌───────────┐
                                                     │  Failed   │
                                                     └───────────┘
```

| Status | Meaning |
| :--- | :--- |
| **Queued** | Job waiting for an available evaluation worker node slot. A submission sent before the deadline is scored even if its turn comes after the deadline. |
| **Running** | Code executing inside the isolated Docker sandbox environment. |
| **Evaluating** | `submission.parquet` generated; server evaluating public & private metrics against ground-truth labels. |
| **Completed** | Pipeline finished successfully; public score calculated and displayed. |
| **Failed** | Execution error or missing output; click entry to inspect full log traceback. |
| **Platform error** | The platform could not run the submission (for example, no worker took it or the environment could not be prepared). It is shown as failed but does not count toward your submission limits; submit again. |

### Live Streaming Logs

Click any submission to show it in the submission viewer, with its log. The page scrolls to the viewer when it is out of view (on narrow screens it is below the list):
- While the submission is running, stdout and stderr stream live from the Docker container. Use them to monitor iteration progress, memory warnings and debugging prints.
- A finished submission shows its stored log.
- The Submissions list refreshes by itself every 15 to 30 seconds while one of your submissions is queued or running; the open submission's status updates as soon as its run ends.
- You can have at most 2 submissions queued or running at once, across all tasks. Submit the next one when one of them finishes.
- Students who have used fewer runs today on a task are scored first, so your first tries of the day wait less than later ones.
- Your submissions, their logs and their results stay viewable until the competition is finalised, including submissions sent during the grace period.

---

## 6. Leaderboard, Double-Blind Privacy and Final Selection

### Pseudonyms & Double-Blind Privacy

- During active competitions, competitors appear on leaderboards under auto-generated pseudonyms (e.g., `Quantum-Falcon-402`).
- Real competitor names and institutional affiliations remain hidden from peer competitors to maintain double-blind fairness.
- Real identities are revealed on public leaderboards only after official competition **Finalization**, and only as name and surname. The leaderboard never shares other competitors' email, username, school, city, grade or other profile details.

### Public vs Private Scores

- **Public Score**: Calculated on a subset split of test labels (`public_eval_percentage`). Visible on the live leaderboard during the competition.
- **Private Score**: Calculated on the remaining hidden test split. It stays hidden until the results are finalised and revealed. After finalisation, the leaderboard ranks competitors by the points the jury awards for each task.

### Star Icon Final Submission Selection (☆ ➔ ★)

You can submit multiple solutions during a competition stage. To designate which completed submission should be evaluated for final private standings:

1. Open the **Submissions** tab.
2. Click your desired completed submission to show it in the submission viewer.
3. Turn on **Select as final submission (enforces anti-overfitting rules).**
4. The viewer shows **FINAL SELECTION** and the list marks the submission with a star and **Final**. A submission created after the stage deadline cannot be selected.

> [!IMPORTANT]
> **Automatic Selection**: Among completed submissions that are eligible under the deadline and
> grace period, an eligible starred submission wins. If none is starred, the platform selects the
> highest score currently allowed to be visible (public before private results are revealed;
> private after reveal), breaking equal scores by shorter execution runtime and then by the
> earlier submission.

### Tie-Breaking Rules

When two competitors achieve identical score values (or, after finalisation, identical points),
they share the same rank number on the leaderboard (e.g. 1, 1, 3) and are listed alphabetically by
pseudonym. Execution runtime matters only when the platform picks which of your own submissions
counts (see **Automatic Selection** above).

Competitors without a scored submission have no rank; after finalisation, a competitor with jury
points is ranked. Each task's tab also shows a **Baseline** row with the score of the organisers'
baseline notebook. It has no rank and sits where its score falls, so the best competitor is always
#1. It does not appear on the general or stage tabs and is hidden once the results are finalised
and revealed.

---

## 7. Troubleshooting and Error Matrix

| Error Message / Code | Root Cause | Solution & Troubleshooting |
| :--- | :--- | :--- |
| `submission.parquet not found` | Notebook executed without error, but failed to create `submission.parquet` in root. | Ensure `submission.to_parquet("submission.parquet", index=False)` executes at the end of your selected cells. |
| `Submission schema validation failed` | Output file exists but has incorrect columns, missing `id` column, or bad dtypes. | Compare your output DataFrame schema against task description specifications and baseline starter code. |
| `TIMEOUT EXPIRED` | Wall-clock execution exceeded task time limit. | Optimize inference code, reduce batch overhead, or switch to lighter pre-trained backbone models. |
| `Out of Memory (OOM)` | Memory footprint exceeded container RAM cap. | Free intermediate tensors, invoke `gc.collect()`, or process test data in smaller batches. |
| `ERR_AST_RULE_FAILED`: banned import | Code imported a restricted library (e.g., `os`, `subprocess`). No submission is created. | Remove forbidden module calls. Use standard scientific Python libraries (numpy, pandas, torch, scikit-learn). |
| `ImportError: No module named 'X'` | Library requested is not pre-installed in container image. | Check task description for available image libraries. Package installation inside container is disabled (`--network none`). |
| `ERR_AST_RULE_FAILED`: syntax error | Selected notebook cells contain invalid Python syntax. No submission is created. | Verify notebook executes cleanly locally before uploading. |
| `ERR_DAILY_LIMIT_REACHED` / `ERR_TASK_LIMIT_REACHED` | Reached the daily limit, or the task's limit for its period of hours. | Wait for the reset: midnight in the competition's timezone for the daily limit. |
| `ERR_TASK_NOT_READY` | The organisers' setup for this task has a recorded problem (for example, its reference solution failed). | Wait; the organisers fix the task and submissions open again. |
| `ERR_TOO_MANY_ACTIVE_RUNS` | You already have 2 submissions waiting or running. No submission is created and nothing counts toward your limits. | Submit again when one of them finishes. |
| `ERR_QUEUE_FULL` | Too many evaluations are waiting. | Try again in a few minutes. |
| `ERR_SERVICE_BUSY` | The server is busy for a moment. Nothing is created. | Try again in a few seconds. |
| `ERR_STAGE_DEADLINE_PASSED` / `ERR_COMPETITION_ENDED` | The deadline and its 3-minute grace period are over. | Submissions are closed for this stage or competition. |
| **Platform error** (failed) | The platform could not run the submission. | Submit again; it did not count toward your limits. |
| "The workspace is being prepared. Please try again shortly." | Your workspace is still starting. | Wait until **Open workspace** is available again, then click it. |
| "The workspaces have no free places left." | Every workspace place is taken. | Tell an organiser. |
| "The workspace service is unavailable. Please try again shortly." | nanoColab did not answer. | Try again in a minute; tell an organiser if it keeps failing. |

---

## 8. Your Workspace (nanoColab)

When the organisers give your stage a workspace, the task page shows a **Workspace** card above the task description. It is a JupyterLab in your browser that already holds the task files. If you see no card, the stage has no workspace.

### The Card

The card shows one status and one line under it; it updates by itself:

| Status | Line | Meaning |
| :--- | :--- | :--- |
| **Not open yet** | "Opens ..." | The workspace opens at that time. Without a time, the organisers have not opened it yet; check again later. |
| **Preparing** | "Starting your workspace" | Your workspace is being prepared. |
| **Ready** | "Files in `image-classification/` · Closes ..." | Click **Open workspace**. The workspace closes at that time, which includes the grace period. |
| **Unknown** | "Status unavailable. You can still try to open it." | You can still click **Open workspace**. |
| **Closed** | "Closed ..." | The stage and its grace period are over. |

The countdown in the navbar shows how long the stage stays open.

### Opening the Workspace

1. Click **Open workspace** (the arrow icon means it opens in a new tab). JupyterLab opens in a new tab. If your browser blocks the tab, the card asks you to allow pop-ups for this site; allow them and click **Open workspace** again.
2. The first start takes about a minute on the progress page. Later openings are quicker and bring back your files as you left them.
3. Keep LavBench open in its own tab. Click **Open workspace** again whenever you closed the JupyterLab tab.

### Your Files

- The workspace root holds one folder per task. The card names the folder of the task you are viewing, for example `image-classification/`.
- Each folder holds the task's public files and `solution.ipynb`, the starter notebook. Work in that folder and keep relative paths, so your notebook finds its data.
- JupyterLab saves your notebook automatically every few minutes; save it yourself (**Ctrl+S**) before the end.

### Hugging Face Models and Datasets

Some tasks come with Hugging Face models or datasets. The task page then shows **Hugging Face data** with one line per folder, for example `../models/demo-org/tiny-model`.

- In the workspace, these folders sit at the root next to the task folders: `models/<org>/<name>/` and `datasets/<org>/<name>/`.
- Open them by the path shown, relative to your task folder, for example `AutoModel.from_pretrained("../models/demo-org/tiny-model")` or `load_dataset("../datasets/demo-org/tiny-data")`. The same relative path works when your notebook runs for scoring, so do not use absolute paths.
- The folders are read-only: save anything you produce in your task folder instead.
- Everything works offline: there is no internet, so nothing can be downloaded from the Hugging Face Hub. Load only the folders listed for the task.

How you submit depends on the task:

- **Notebook task** (the task page shows **Upload Jupyter Notebook (.ipynb)**): save `solution.ipynb` in JupyterLab, then on the task page click **Load from workspace**. Its cells appear in the cell picker; select them and click **Submit N cells for Evaluation**, as in [section 4](#4-notebook-submission-workflow-and-ast-pre-validation). Uploading a downloaded notebook still works.
- **File task** (the task page shows **Submit from workspace**): see [section 9](#9-file-tasks-submitting-from-the-workspace).

---

## 9. File Tasks: Submitting from the Workspace

In a file task your notebook runs in your workspace, not on LavBench. You submit the file it writes, `submission.parquet`, together with the notebook that made it, `solution.ipynb`. Both must be in the task's folder, for example `image-classification/`.

### Step by Step

1. On the task page, click **Open workspace** on the **Workspace** card.
2. In JupyterLab, open `solution.ipynb` in the task folder, write your solution and run it so that it saves `submission.parquet` next to the notebook. Save the notebook (**Ctrl+S**).
3. Back on the LavBench tab, click **Submit from workspace** under **Submit Solution**. LavBench reads both files from your workspace; this takes a few seconds ("Reading your workspace...").
4. The **Submissions** page opens on your new submission. **Submitted files** is your receipt: the time and the size of `submission.parquet`. The status moves from **Queued** to **Completed** with a score.

### When Submit Does Not Work

The reason appears next to the button. Nothing is submitted and no attempt is used.

| Message | What to do |
| :--- | :--- |
| "No submission.parquet in image-classification/ of your workspace. Save it from solution.ipynb, then Submit again." | Run the notebook so that it saves `submission.parquet` in the task folder, not elsewhere. |
| "No solution.ipynb in image-classification/ of your workspace." | Keep the notebook's name and place; rename it back if you changed it. |
| "The submission file cannot be scored: ..." | The columns or ids do not match the task; the message says how many ids are missing or unexpected. Fix the file and submit again. |
| "You already submitted this exact file for this task." | Change your solution first; the same file is not scored twice. |
| "The file exceeds the 20 MB limit." | Write a smaller file, for example without extra columns. |
| "Your workspace files cannot be read right now. Please try again shortly." | The button is disabled with a countdown ("Try again in N seconds."); press it again when it ends. |
| "The file could not be checked because of a platform problem. Please try again shortly." | Not your file's fault. Wait for the countdown, then press the button again; tell an organiser if it keeps failing. |
| "The workspace service is unavailable. Please try again shortly." | Try again after the countdown; tell an organiser if it keeps failing. |

### Emergency Upload During an Outage

If the workspaces are down, the organisers can allow an emergency upload for the task. A notice then appears under **Submit from workspace**:

1. Choose your `submission.parquet` and your `solution.ipynb` in the two upload areas (or drag them there).
2. Click **Upload and submit**. The same checks and limits apply, and the **Submissions** page opens as above.

