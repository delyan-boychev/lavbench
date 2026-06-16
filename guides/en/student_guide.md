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

- **Title and Description** — explains the problem you need to solve
- **Rules & Configuration** — resource limits (RAM, time, GPU), banned imports, and submission rate limits
- **Files** — downloadable datasets and helper files. Click the **Download** button next to any file and save it locally

### Key Files
- **Dataset files** (`.csv`, `.parquet`, `.json`) — the test data you'll run your model on
- **Helper files** (`.py`, `.pkl`) — pre-trained models or utility code provided by the organizer
- **Labels.parquet is NOT provided** — this file contains the answer key and stays on the server. Your code will be scored against it automatically

### Checking Your Limits
Look at the "Execution Rules" section to see:
- **RAM Limit** — maximum memory your code can use
- **Time Limit** — maximum runtime in seconds
- **GPU Required** — whether your code will run on GPU or CPU
- **Banned Imports** — libraries you cannot use (if any)
- **Daily Submissions** — how many times you can submit per day
- **Task Rate Limit** — some tasks have per-hour limits

---

## 3. How Evaluation Works

Your code runs in a secure Docker container with the datasets you downloaded. The platform evaluates your work by **comparing a file your code produces against the hidden answer key**.

### What You Need to Do

1. Read the task description to understand what you're predicting
2. Download the task files (datasets) to your computer
3. Build a model that makes predictions
4. Write code that saves your predictions as a file named **`submission.parquet`**
5. Upload your Jupyter notebook and select the cells with your code

### The Output File: `submission.parquet`

Your code must create a file named exactly **`submission.parquet`** in the current working directory. This file must contain your predictions in a specific format.

### Required Columns

Your `submission.parquet` **must** include:
- An **`id`** column — integer IDs that match the test data rows
- One or more **prediction columns** — your model's output (usually named `prediction`, `label`, or a name specified in the task description)

The system compares your `submission.parquet` against the hidden `labels.parquet` row by row, matching on the `id` column.

### Example — Binary Classification

```python
import pandas as pd

# 1. Load the test data (from the files you downloaded)
test_data = pd.read_csv("test.csv")

# 2. Your model makes predictions
predictions = my_model.predict(test_data)

# 3. Save as submission.parquet
submission = pd.DataFrame({
    "id": test_data["id"],
    "prediction": predictions
})
submission.to_parquet("submission.parquet", index=False)
```

### Example — Multi-Column Output

If your task requires multiple prediction columns:

```python
submission = pd.DataFrame({
    "id": test_ids,
    "score": probability_scores,
    "class": class_labels
})
submission.to_parquet("submission.parquet", index=False)
```

**Check your task description** for the exact column names and format required by your specific task.

---

## 4. Submitting Your Notebook

### What to Include
Your Jupyter notebook should contain:
- All necessary imports (pandas, scikit-learn, torch, etc.)
- Your model definition and training code **OR** code that loads a pre-trained model
- The code that generates and saves `submission.parquet`

### What NOT to Include
- **Data exploration cells** — charts, print statements, head() calls
- **pip install commands** — the Docker environment already has the required libraries
- **Large output tables** — keep notebooks under 5 MB

### Step-by-Step

1. **Open the task** in the Challenge tab
2. Click **Upload Notebook** and select your `.ipynb` file
3. The interface parses your notebook and shows all cells. **Check the boxes** next to the cells that contain your model and prediction code
4. Review the selected cells — they will be concatenated and run as a single Python script
5. Click **Submit**

### File Requirements
- Only `.ipynb` files are accepted
- Maximum file size: **5 MB**
- Supported cell types: code cells only (markdown cells are ignored)

### Tracking Your Submission

After submitting, check the **Submissions** tab for your status:

| Status | Meaning |
|--------|---------|
| **Queued** | Waiting for an available worker |
| **Running** | Your code is executing in the sandbox |
| **Evaluating** | Your `submission.parquet` is being scored against `labels.parquet` |
| **Completed** | Evaluation finished — check your score on the leaderboard |
| **Failed** | Something went wrong — click the submission to expand and read the full error log |

You can also see **live logs** by clicking on a running submission — the log output from your code streams in real-time.

---

## 5. Understanding the Leaderboard

### Anonymity
During the competition, you see only **pseudonyms** (like `Quantum-Falcon-402`). Your real name is hidden from other competitors. Identities are revealed to everyone only after the competition is finalized.

### Reading the Leaderboard
- Each row shows a competitor's rank, alias, and scores per task
- Click on a row to expand and see detailed scores per task
- **Public Score** — calculated from the public portion of the test data (visible to all)
- **Private Score** — calculated from the hidden portion of the test data (visible after finalization)

### Tie-Breaking
If two competitors have the same score:
1. The one with **faster execution time** ranks higher
2. If execution times also match, the **earlier submission** wins

### Selecting Your Final Submission
You can submit multiple times. When you're satisfied with a result:
1. Go to the **Submissions** tab
2. Find your best submission
3. Click the **star icon** (☆) to mark it as your **Final Selection**
4. The star turns solid (★) — only this submission counts toward your ranking

**Important**: Make your final selection before the window closes. The selection window ends shortly after the deadline — check the countdown timer. If you don't select a final submission, your last submission is used automatically.

---

## 6. Rules and Restrictions

### Banned Imports
Some tasks restrict certain libraries (like `os`, `sys`, `subprocess`, `requests`) for security. These restrictions are **per-task** — not all tasks have the same rules. Check your task details to see what's banned.

### The `# SUBMIT` Tag
If the task rules say "Require Submit Tag", at least one of your selected cells must contain the comment `# SUBMIT`. Place it in the cell with your main prediction logic:

```python
# SUBMIT
import pandas as pd
...
```

### Magic Commands
Jupyter magic commands (`!pip install`, `%timeit`, `%matplotlib inline`) are incompatible with the evaluation system. Your submission will be **rejected** if any selected cell contains these commands. Remove them before submitting.

### Submission Limits
- **Daily limit**: Maximum submissions per calendar day across all tasks in your competition
- **Task-specific limit**: Some tasks have per-hour limits (check task details)

If you hit a limit, wait until the next day (or next window) and try again. Failed submissions that are rejected during pre-check (rule violations, banned imports) do NOT count toward your limit.

---

## 7. Troubleshooting

If your submission fails, click on it in the **Submissions** tab to expand and read the full error log. Common issues:

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `submission.parquet not found` | Your code didn't create the output file | Add `submission.to_parquet("submission.parquet")` to your code |
| `Submission schema validation failed` | Missing `id` column or wrong format | Ensure your DataFrame has an `id` column with integer values |
| `TIMEOUT EXPIRED` | Your code ran longer than the time limit | Optimize your algorithm, use smaller batches, or a lighter model |
| `Out of Memory (OOM)` | Your model used too much RAM | Reduce batch sizes, use smaller datasets, or a lighter model |
| `ImportError: No module named 'X'` | You're importing a library not available | Check which libraries are installed in the task description; only use standard ML libraries |
| `Banned import detected: os` | You imported a restricted library | Remove the import or check if it's allowed for your task |
| `Submit tag required` | Your selected cells don't contain `# SUBMIT` | Add `# SUBMIT` comment to at least one selected cell |
| `AttributeError / ValueError` | Bug in your code logic | Read the full traceback in the logs; test locally first |

### The Grace Period
After the official deadline, the countdown timer turns **orange** and shows a grace period. During this brief window, last-second submissions are still accepted. Once the grace period expires, no more submissions can be made — plan to submit well before the deadline to avoid last-minute issues.

### Need Help?
- Check the task description for expected output format and column names
- Review the error log — it contains the full Python traceback
- If you're stuck, ask your competition organizer for help
