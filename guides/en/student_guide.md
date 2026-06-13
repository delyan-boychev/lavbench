# Student (Competitor) Complete Guide

Welcome to the NAI Platform! This guide explains how to authenticate, prepare your Jupyter notebooks, and successfully submit your machine learning models to the evaluation cluster.

## Table of Contents
1. [Authentication & Account Security](#1-authentication--account-security)
2. [Notebook Submission Workflow](#2-notebook-submission-workflow)
3. [Writing the `predict` Function](#3-writing-the-predict-function)
4. [Rules Engine & Banned Imports](#4-rules-engine--banned-imports)
5. [Queue Tracking & Grace Periods](#5-queue-tracking--grace-periods)
6. [Leaderboard Visibility](#6-leaderboard-visibility)

---

## 1. Authentication & Account Security

1. Navigate to the `/login` portal.
2. Enter your assigned username or email and password.
3. **Security Constraints:** The login system utilizes brute-force protection to prevent unauthorized access. For on-site competitions sharing a single IP, the system intelligently limits rapid sequential failures targeting your specific account rather than broadly blocking the school network.
4. **Session Lifetime:** Your secure JWT session remains active for exactly **24 hours**.

> [!NOTE]
> You are strictly bound to your assigned Challenge. Attempting to navigate to or submit code for other active or archived competitions will result in a `403 Forbidden` error.

---

## 2. Notebook Submission Workflow

You do not need to convert your code into Python scripts. The platform natively processes `.ipynb` Jupyter Notebooks.

1. **Upload:** Click the "Upload Notebook" button in the task portal and select your file. (Note: File sizes are strictly limited to prevent server exhaustion; keep notebooks under 5MB).
2. **Select Code:** The UI will display all cells. Check the boxes next to the cells that contain your model logic and imports. You should *exclude* data exploration charts, massive print outputs, or pip install commands.
3. **Submit:** The backend concatenates your selected cells and dispatches them to a secure, isolated Docker container.

---

## 3. Writing the `predict` Function

The automated evaluator relies on a standard entry point. Somewhere in your selected cells, you must define a function exactly named `predict`.

### Example: Text Classification
```python
# SUBMIT

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer

# Assuming these files were provided in the task's dataset folder
vectorizer = joblib.load("vectorizer.pkl")
model = joblib.load("model.pkl")

def predict(inputs_list):
    """
    Inputs: A list of text strings.
    Returns: A list of integer predictions.
    """
    features = vectorizer.transform(inputs_list)
    predictions = model.predict(features)
    
    # Ensure you return a standard Python list
    return list(predictions)
```

---

## 4. Rules Engine & Banned Imports

Before your code enters the queue, it passes through an Abstract Syntax Tree (AST) scanner.

### The `# SUBMIT` Tag
If the task specifies "Require Submit Tag", at least one of your selected cells must contain the comment `# SUBMIT`.

### Magic Commands
Jupyter magic commands (`!pip install`, `%timeit`) are incompatible with standard Python execution and will cause your submission to be rejected instantly. Remove them from your selected cells.

### Banned System Imports
To ensure cluster security, you cannot import operating system libraries. Attempting to use `os`, `sys`, `subprocess`, `requests`, `socket`, or `multiprocessing` will result in a validation block.

---

## 5. Queue Tracking & Grace Periods

### Real-Time Updates
Once submitted, you can track the status in your submission history:
* **Queued:** Waiting for an available worker node.
* **Running:** The Docker container is executing your code.
* **Evaluating:** Your predictions are being compared against the hidden test dataset.
* **Completed / Failed:** Execution finished. If failed, click to expand the error log for a detailed stack trace.

### The Deadline Grace Period
To account for network latency or slow parsing during the final seconds of a competition, the platform provides a short **Grace Period** immediately following the official deadline. 
* The countdown timer UI will shift to an **Amber/Orange** color and display a warning text when the grace period is active. 
* Submissions received after this exact grace window expires are strictly rejected.

---

## 6. Leaderboard Visibility

* **Anonymity:** During active competitions, the leaderboard protects your privacy by displaying randomly generated aliases (e.g., `Quantum-Falcon-402`).
* **Final Selection:** You must explicitly mark your best submission as your "Final Selection" by clicking the star icon. Only this submission is used to calculate your official ranking.
* **Tie-Breakers:** In the rare event of identical mathematical scores, the platform rewards efficiency: the submission with the fastest execution time wins the tie.