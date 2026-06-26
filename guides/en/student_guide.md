# Student Guide

Welcome to the LavBench Platform! This guide walks you through everything you need to compete — from logging in to submitting your final notebook.

---

## 1. Getting Started

### Logging In

1. Open the LavBench web app in your browser
2. Enter the username and password provided by your competition organizer
3. After logging in, you'll see the main dashboard with tabs in the competition bar: **Challenge**, **Leaderboard**, and **Submissions**

### The Competition Bar

Below the navbar, you'll find a bar with:

- **Competition selector** — shows which competition you're registered for. If it says "No competition", contact your organizer
- **Navigation tabs** — Challenge (tasks and submission), Leaderboard (rankings), Submissions (your submission history)

### The Countdown Timer

In the navbar, a timer shows how much time is left in the current competition or stage. When it turns:

- **Green** — plenty of time remaining (>30 minutes)
- **Yellow** — getting close (≤30 minutes)
- **Red** — almost over (≤15 minutes)
- **Flashing Red** — final minutes (≤5 minutes)
- **Orange** — grace period active (last-second submissions still accepted)

### Finding Your Task

1. Click the **Challenge** tab in the competition bar
2. The left sidebar lists all available tasks. If the list is empty, the competition hasn't started yet
3. Click a task to see its description, rules, and attached files

---

## 2. Understanding Your Task

Each task shows:

- **Title and Description** — explains the ML problem you need to solve
- **Rules & Configuration** — resource limits (RAM, time, GPU), banned imports, and rate limits
- **Files** — downloadable datasets and helper files. Click the **Download** button next to any file and save it locally

### Key Files

- **Dataset files** (`.csv`, `.parquet`, `.json`) — the test set you'll run inference on with your model
- **Helper files** (`.py`, `.pkl`) — pre-trained models or utility code provided by the organizer
- **Labels.parquet is NOT provided** — this file contains the ground truth (labels) and stays on the server. Your code will be automatically evaluated against it

### Checking Your Limits

Look at the "Execution Rules" section to see:

- **RAM Limit** — maximum memory your code can use
- **Time Limit** — maximum runtime in seconds
- **GPU Required** — whether your code will run on a hardware accelerator or CPU
- **Banned Imports** — libraries you cannot use (if any)
- **Daily Submissions** — how many times you can submit per day
- **Task Rate Limit** — some tasks have per-hour submission limits

---

## 3. How Evaluation Works

Your code runs in a hardened Docker container (sandbox) with the datasets you downloaded. The sandbox is fully isolated: no network access, no Linux capabilities, no privilege escalation, and a read-only filesystem (only `/app/` and `/tmp/` are writable). The platform calculates your metrics by **comparing the file with your predictions against the hidden ground truth file**.

### What You Need to Do

1. Read the task description to understand the target variable
2. Download the task files (datasets) **and the baseline notebook** to your computer
3. The baseline notebook contains starter code, including the cell that creates and saves `submission.parquet`. **Build your model around this cell — do not modify it**
4. Upload your completed notebook and select all cells containing your code

### The Output File: `submission.parquet`

Your code must create a file named exactly **`submission.parquet`** in the current working directory. This file must contain your predictions in a specific format.

### Required Columns

Your `submission.parquet` **must** include:

- An **`id`** column — integer IDs that match the test set rows
- One or more **prediction columns** — your model's output (usually named `prediction`, `label`, or a name specified in the task description)

The system calculates your score by comparing your `submission.parquet` against the hidden `labels.parquet` row by row, joining them on the `id` column.

### Example — Binary Classification

```python
import pandas as pd

# 1. Load the test set (from the files you downloaded)
test_data = pd.read_csv("test.csv")

# 2. Inference: your model generates predictions
predictions = my_model.predict(test_data)

# 3. Save as submission.parquet
submission = pd.DataFrame({
    "id": test_data["id"],
    "prediction": predictions
})
submission.to_parquet("submission.parquet", index=False)
```

### Example — Multi-Column Output

If your task requires multiple prediction columns (e.g., class probabilities):

```python
submission = pd.DataFrame({
    "id": test_ids,
    "score": probability_scores,
    "class": predicted_classes
})
submission.to_parquet("submission.parquet", index=False)
```

**Check your task description** for the exact column names and schema required by your specific task.

---

## 4. Submitting Your Notebook

### What to Include

Your Jupyter notebook should contain:

- All necessary dependencies (pandas, scikit-learn, torch, etc.)
- Your model definition and training loop **OR** code that loads pre-trained model weights
- The code that generates and saves `submission.parquet` (**must come from the baseline notebook — do not change this cell to maintain the correct schema**)

### What NOT to Include

- **Exploratory Data Analysis (EDA) cells** — charts, print statements, head() calls
- **pip install commands** — the Docker environment already has the required dependencies
- **Large output tables** — keep notebooks under 5 MB

### Step-by-Step

1. **Download the files** for your task: datasets and the baseline notebook
2. Open the baseline notebook and build your model code in new cells above or below the existing ones
3. **Do not edit the cell that creates and saves `submission.parquet`** — the evaluation system depends on it producing the correct output schema
4. Click **Upload Notebook** in the Challenge tab and select your `.ipynb` file
5. The interface parses your notebook and shows all cells. **Check the boxes** next to all cells that contain your model code AND the `submission.parquet` output cell
6. Review the selected cells — they will be concatenated and run as a single Python script (AST validation)
7. Click **Submit**

### File Requirements

- Only `.ipynb` files are accepted
- Maximum file size: **5 MB**
- Supported cell types: code cells only (markdown cells are ignored)

### Tracking Your Submission

After submitting, check the **Submissions** tab for your status:

| Status         | Meaning                                                                                       |
| -------------- | --------------------------------------------------------------------------------------------- |
| **Queued**     | Waiting for an available worker node                                                          |
| **Running**    | Your code is executing in the isolated environment (sandbox)                                  |
| **Evaluating** | Your `submission.parquet` metrics are being calculated against `labels.parquet`               |
| **Completed**  | Evaluation finished — check your score on the leaderboard                                     |
| **Failed**     | Something went wrong — click the submission to expand and read the full error log (traceback) |

You can also see **live logs** by clicking on a running submission — the standard output (stdout/stderr) from your code streams in real-time.

---

## 5. Understanding the Leaderboard

### Anonymity

During the competition, you see only **pseudonyms** (like `Quantum-Falcon-402`). Your real name is hidden from other competitors. Identities are de-anonymized for everyone only after the competition is finalized.

### Reading the Leaderboard

- Each row shows a competitor's rank, alias, and scores per task
- Click on a row to expand and see detailed scores per task
- **Public Score** — calculated from the public split of the test set. Visible to all during the competition.
- **Private Score** — calculated from the private split of the test set. Used for the final ranking and visible after finalization.

### Tie-Breaking

If two competitors have the same score:

1. The one with **faster execution time** (more efficient inference) ranks higher
2. If execution times also match, the **earlier submission** wins

### Selecting Your Final Submission

You can submit multiple times. When you're satisfied with a result:

1. Go to the **Submissions** tab
2. Find your best submission
3. Click the **star icon** (☆) to mark it as your **Final Selection**. This prevents overfitting to the public score.
4. The star turns solid (★) — only this submission counts toward your final ranking.

**Important**: Make your final selection before the window closes. The selection window ends shortly after the deadline — check the countdown timer. If you don't select a final submission, your last submission is used automatically.

---

## 6. Rules and Restrictions

### Banned Imports

Some tasks restrict certain libraries (like `os`, `sys`, `subprocess`, `requests`) for security. These restrictions are **per-task** — not all tasks have the same rules. Check your task details to see what's banned.

### Magic Commands

Jupyter magic commands (`!pip install`, `%timeit`, `%matplotlib inline`) are **automatically stripped** before execution. You can leave them in your notebook, but they will have no effect inside the sandbox — do not rely on `!pip install` to add packages; all required libraries must already be in the Docker environment.

### Submission Limits

- **Daily limit**: Maximum submissions per calendar day across all tasks in your competition
- **Task-specific limit**: Some tasks have per-hour rate limits (check task details)

If you hit a limit, wait until the next day (or next window) and try again. Failed submissions that are rejected during the preliminary AST check (rule violations, banned imports) do NOT count toward your limit.

---

## 7. Troubleshooting

If your submission fails, click on it in the **Submissions** tab to expand and read the full error log. Common issues:

| Error                                 | Likely Cause                                             | Fix                                                                                             |
| ------------------------------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `submission.parquet not found`        | Your code didn't create the output file                  | Add `submission.to_parquet("submission.parquet")` at the end of your pipeline                   |
| `Submission schema validation failed` | Missing `id` column or wrong format (dtype)              | Ensure your DataFrame has an `id` column with integer values                                    |
| `TIMEOUT EXPIRED`                     | Your code ran longer than the time limit                 | Optimize your algorithm, use larger batch sizes for inference (if on GPU), or a lighter model   |
| `Out of Memory (OOM)`                 | Your process exceeded the allocated RAM/VRAM             | Reduce batch sizes, free up memory (garbage collection), or use a quantized model               |
| `ImportError: No module named 'X'`    | You're trying to import a library not in the environment | Check which libraries are available in the Docker environment according to the task description |
| `Banned import detected: os`          | You imported a restricted library                        | Remove the import; the system uses a static analyzer to catch banned modules                    |
| `AttributeError / ValueError`         | Bug in your code logic                                   | Read the full traceback in the logs; validate your pipeline locally before submitting           |

### The Grace Period

After the official deadline, the countdown timer turns **orange** and shows a grace period. During this brief window, submissions are still accepted. Once the grace period expires, the submission pipeline closes — plan to submit your solutions well before the deadline to avoid issues with long inference times at the last minute.

### Need Help?

- Check the task description for the expected schema of the output file and column definitions.
- Review the error log — it contains the full Python traceback.
- If you have a system issue, contact the jury.
