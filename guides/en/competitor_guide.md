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
| **Orange** | **Grace Period Active** | Official deadline passed. Last-second pending submissions accepted during buffer. |

> [!WARNING]
> Once the Grace Period buffer expires, the submission pipeline closes completely and incoming notebook uploads will be rejected.

---

## 2. Stage and Task Overview

### Stage Selector Navigation

Competitions on LavBench can feature multiple stages (e.g., *Stage 1 - Feature Engineering*, *Stage 2 - Fine-Tuning*). 
- Use the **Stage Selector** tab bar on the **Challenge** page to navigate between active stages.
- Each stage exposes its own start/end countdown deadlines and assigned machine learning tasks.

### Task Specifications and Rules

Clicking a task displays full details:
- **Problem Description & Rules**: Target objectives, input formats, evaluation metric weighting.
- **Resource Allocations**: Container memory cap (RAM), wall-clock time limit, GPU hardware accelerator requirement, CPU core allocation.
- **Security & Import Rules**: Banned modules (e.g., `os, sys, subprocess, requests`) or strict whitelisted libraries.
- **Submission Limits**: Maximum daily submissions per user and hourly task rate limits.
- **Downloadable Assets**: Training/test datasets and starter baseline notebooks.

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
3. Click **Upload Notebook** in the **Challenge** view and select your `.ipynb` file (max 5 MB).
4. **Cell Selection Workflow**:
   - The cell parser modal lists all code cells detected in your notebook.
   - Check the selection boxes next to the cells required for model execution and `submission.parquet` export.
   - Omit exploratory visualization cells, print statements, or unneeded training scratchpad cells.
5. Click **Submit Selected Cells**.

```
[ Upload .ipynb ] ➔ [ Parse Cells ] ➔ [ Select Code Cells ] ➔ [ AST Check ] ➔ [ Queue Job ]
```

### AST Pre-Validation & Quota Preservation

Before your code is dispatched to execution workers, it undergoes server-side Static Application Security Testing (AST):

- **IPython Magic Stripping**: Shell commands (`!pip install`, `%matplotlib inline`, `%timeit`) are automatically stripped.
- **Security Inspection**: Validates syntax and checks against `banned_imports` or `whitelisted_imports`.

> [!IMPORTANT]
> **Quota Preservation**: If a submission fails AST pre-validation (e.g., syntax error or forbidden import), the upload is rejected immediately with error feedback, and **your daily/hourly submission quota is NOT consumed**.

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
| **Queued** | Job waiting for an available evaluation worker node slot. |
| **Running** | Code executing inside the isolated Docker sandbox environment. |
| **Evaluating** | `submission.parquet` generated; server evaluating public & private metrics against ground-truth labels. |
| **Completed** | Pipeline finished successfully; public score calculated and displayed. |
| **Failed** | Execution error or missing output; click entry to inspect full log traceback. |

### Live Streaming Logs

Click on any active (`Running` / `Evaluating`) or finished submission to open the log viewer:
- Real-time stdout and stderr execution output streams directly from the Docker container.
- Use live logs to monitor batch iteration progress, memory allocation warnings, and debugging prints.

---

## 6. Leaderboard, Double-Blind Privacy and Final Selection

### Pseudonyms & Double-Blind Privacy

- During active competitions, competitors appear on leaderboards under auto-generated pseudonyms (e.g., `Quantum-Falcon-402`).
- Real competitor names and institutional affiliations remain hidden from peer competitors to maintain double-blind fairness.
- Real identities are revealed on public leaderboards only after official competition **Finalization**.

### Public vs Private Scores

- **Public Score**: Calculated on a subset split of test labels (`public_eval_percentage`). Visible on the live leaderboard during the competition.
- **Private Score**: Calculated on the remaining hidden test split. Kept hidden until competition finalization and determines final official rankings.

### Star Icon Final Submission Selection (☆ ➔ ★)

You can submit multiple solutions during a competition stage. To designate which completed submission should be evaluated for final private standings:

1. Open the **Submissions** tab.
2. Find your desired submission entry.
3. Click the **Star Icon** (☆) next to the submission.
4. The icon highlights to solid (★), marking it as your active **Final Selection**.

> [!IMPORTANT]
> **Automatic Default**: If you do not manually star a final submission before the selection window closes, the platform **automatically selects your latest completed submission** as your default final entry.

### Tie-Breaking Rules

When two competitors achieve identical score values:
1. **Inference Wall-Clock Runtime**: The submission with the shorter execution runtime in the sandbox ranks higher.
2. **Submission Timestamp**: If execution times are identical, the earlier submission timestamp wins.

---

## 7. Troubleshooting and Error Matrix

| Error Message / Failure State | Root Cause | Solution & Troubleshooting |
| :--- | :--- | :--- |
| `submission.parquet not found` | Notebook executed without error, but failed to create `submission.parquet` in root. | Ensure `submission.to_parquet("submission.parquet", index=False)` executes at the end of your selected cells. |
| `Submission schema validation failed` | Output file exists but has incorrect columns, missing `id` column, or bad dtypes. | Compare your output DataFrame schema against task description specifications and baseline starter code. |
| `TIMEOUT EXPIRED` | Wall-clock execution exceeded task time limit. | Optimize inference code, reduce batch overhead, or switch to lighter pre-trained backbone models. |
| `Out of Memory (OOM)` | Memory footprint exceeded container RAM cap. | Free intermediate tensors, invoke `gc.collect()`, or process test data in smaller batches. |
| `Banned import detected: module` | Code imported a restricted library (e.g., `os`, `subprocess`). | Remove forbidden module calls. Use standard scientific Python libraries (numpy, pandas, torch, scikit-learn). |
| `ImportError: No module named 'X'` | Library requested is not pre-installed in container image. | Check task description for available image libraries. Package installation inside container is disabled (`--network none`). |
| `AST Syntax Error / Parsing Error` | Selected notebook cells contain invalid Python syntax. | Verify notebook executes cleanly locally before uploading. |
| `Submission quota exceeded` | Reached daily limit or hourly rate limit for task. | Wait for quota window reset before submitting additional notebooks. |

---


