"""Jinja2 templates for Dockerfiles used in sandbox execution."""

from jinja2 import Environment

DEFAULT_EVALUATION_TEMPLATE = """\

import os
import sys
import json
import traceback
import time
import subprocess
from datasets import load_dataset
from sklearn.metrics import accuracy_score, f1_score, mean_squared_error

# Inject HF cache directory if defined
if os.environ.get("HF_CACHE_DIR"):
    os.environ["HF_HOME"] = os.environ.get("HF_CACHE_DIR")
    os.environ["HF_DATASETS_CACHE"] = os.environ.get("HF_CACHE_DIR")

def predict(inputs):
    # Serialize inputs to inputs.json
    with open("inputs.json", "w") as f:
        json.dump(inputs, f)

    # Run the student code in a separate subprocess
    env = os.environ.copy()
    env.pop("RESULTS_KEY", None)

    runner_code = \"\"\"
import json
import sys
import os

os.environ.pop("RESULTS_KEY", None)

try:
    import student_actual
    if not hasattr(student_actual, 'predict'):
        raise AttributeError("No predict function found in student code.")

    with open("inputs.json", "r") as f:
        inputs = json.load(f)

    preds = student_actual.predict(inputs)

    with open("predictions.json", "w") as f:
        json.dump(preds, f)
except Exception as e:
    import traceback
    with open("predictions.json", "w") as f:
        json.dump({ "error": str(e), "traceback": traceback.format_exc() }, f)
\"\"\"
    with open("run_student.py", "w") as f:
        f.write(runner_code)

    proc = subprocess.run([sys.executable, "run_student.py"],
        env=env, capture_output=True, text=True)

    if os.path.exists("run_student.py"):
        try: os.remove("run_student.py")
        except OSError: pass
    if os.path.exists("inputs.json"):
        try: os.remove("inputs.json")
        except OSError: pass

    # Clean up any potential eval_results spoofing attempt by the student code
    results_key = os.environ.get("RESULTS_KEY", "")
    for f_name in ["eval_results.json", f"eval_results_{results_key}.json"]:
        if os.path.exists(f_name):
            try: os.remove(f_name)
            except OSError: pass

    if not os.path.exists("predictions.json"):
        raise RuntimeError(f"Student code subprocess failed to run. Stderr: {proc.stderr}")

    with open("predictions.json", "r") as f:
        preds_data = json.load(f)

    if isinstance(preds_data, dict) and "error" in preds_data:
        raise RuntimeError(
            f"Error in student predict:"
            f" {preds_data['error']}\\n{preds_data.get('traceback', '')}"
        )

    try: os.remove("predictions.json")
    except OSError: pass

    return preds_data

def run_evaluation():
    try:
        # Load Hugging Face dataset
        public_pct = [[public_eval_percentage]]

        dataset = load_dataset("default", split="[[hf_dataset_split]]")

        total_len = len(dataset)
        if total_len == 0:
            raise ValueError("The Hugging Face dataset split has 0 rows.")

        # Define public vs private split
        public_size = int(total_len * (public_pct / 100.0))
        if public_size == 0:
            public_size = 1
        if public_size >= total_len:
            public_size = total_len - 1

        # Determine column names (defaults to 'text' and 'label')
        input_col = "text"
        label_col = "label"

        # Fallbacks for column inspection if columns do not exist
        if input_col not in dataset.column_names:
            cols = [c for c in dataset.column_names if c != label_col]
            if cols:
                input_col = cols[0]
            else:
                input_col = dataset.column_names[0]

        if label_col not in dataset.column_names:
            if "label" in dataset.column_names:
                label_col = "label"
            elif "labels" in dataset.column_names:
                label_col = "labels"
            else:
                label_col = dataset.column_names[-1]

        # Split indexes
        public_dataset = dataset.select(range(0, public_size))
        private_dataset = dataset.select(range(public_size, total_len))

        # Evaluate Public Split
        public_inputs = public_dataset[input_col]
        public_labels = public_dataset[label_col]

        start_time = time.time()
        public_preds = predict(public_inputs)
        public_time = time.time() - start_time

        if len(public_preds) != len(public_labels):
            raise ValueError(
                f"predict returned {len(public_preds)} "
                "items, but expected {len(public_labels)}."
            )

        # Evaluate Private Split
        private_inputs = private_dataset[input_col]
        private_labels = private_dataset[label_col]

        start_time = time.time()
        private_preds = predict(private_inputs)
        private_time = time.time() - start_time

        # Calculate scores
        # metrics_cfg e.g. {"accuracy": {"weight": 1.0, "higher_is_better": true}}
        metrics_cfg = [[metrics_config_str]]

        if not metrics_cfg:
            metrics_cfg = {"accuracy": {"weight": 1.0, "higher_is_better": True}}

        def eval_metric(metric_name, y_true, y_pred):
            m_name = metric_name.lower()
            if m_name == "accuracy":
                return accuracy_score(y_true, y_pred)
            elif m_name == "f1":
                return f1_score(y_true, y_pred, average="weighted")
            elif m_name in ["mse", "mean_squared_error"]:
                return mean_squared_error(y_true, y_pred)
            else:
                return accuracy_score(y_true, y_pred)

        pub_payload = {}
        priv_payload = {}

        pub_weighted = 0.0
        priv_weighted = 0.0
        total_weight = 0.0

        for m_name, m_info in metrics_cfg.items():
            weight = m_info.get("weight", 1.0)
            total_weight += weight

            val_pub = eval_metric(m_name, public_labels, public_preds)
            val_priv = eval_metric(m_name, private_labels, private_preds)

            pub_payload[m_name] = float(val_pub)
            priv_payload[m_name] = float(val_priv)

            pub_weighted += float(val_pub) * weight
            priv_weighted += float(val_priv) * weight

        if total_weight > 0:
            final_pub_score = pub_weighted / total_weight
            final_priv_score = priv_weighted / total_weight
        else:
            final_pub_score = 0.0
            final_priv_score = 0.0

        # Output results JSON directly to file
        results_key = os.environ.get("RESULTS_KEY", "")
        results_file = f"eval_results_{results_key}.json" if results_key else "eval_results.json"
        with open(results_file, "w") as f_res:
            json.dump({
                "status": "success",
                "public_score": final_pub_score,
                "private_score": final_priv_score,
                "metrics_payload_public": pub_payload,
                "metrics_payload_private": priv_payload,
                "execution_time_ms": int((public_time + private_time) * 1000)
            }, f_res)

    except Exception as e:
        results_key = os.environ.get("RESULTS_KEY", "")
        results_file = f"eval_results_{results_key}.json" if results_key else "eval_results.json"
        with open(results_file, "w") as f_res:
            json.dump({
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }, f_res)

if __name__ == "__main__":
    run_evaluation()
"""

CUSTOM_EVAL_WRAPPER = """\
import os
import json
import subprocess
import sys

def predict(inputs):
    # Serialize inputs to inputs.json
    with open("inputs.json", "w") as f:
        json.dump(inputs, f)

    # Run the student code in a separate subprocess
    env = os.environ.copy()
    env.pop("RESULTS_KEY", None)

    runner_code = \"\"\"
import json
import sys
import os

os.environ.pop("RESULTS_KEY", None)

try:
    import student_actual
    if not hasattr(student_actual, 'predict'):
        raise AttributeError("No predict function found in student code.")

    with open("inputs.json", "r") as f:
        inputs = json.load(f)

    preds = student_actual.predict(inputs)

    with open("predictions.json", "w") as f:
        json.dump(preds, f)
except Exception as e:
    import traceback
    with open("predictions.json", "w") as f:
        json.dump({"error": str(e), "traceback": traceback.format_exc()}, f)
\"\"\"
    with open("run_student.py", "w") as f:
        f.write(runner_code)

    proc = subprocess.run([sys.executable, "run_student.py"],
        env=env, capture_output=True, text=True)

    if os.path.exists("run_student.py"):
        try: os.remove("run_student.py")
        except OSError: pass
    if os.path.exists("inputs.json"):
        try: os.remove("inputs.json")
        except OSError: pass

    # Clean up any potential eval_results spoofing attempt by the student code
    results_key = os.environ.get("RESULTS_KEY", "")
    for f_name in ["eval_results.json", f"eval_results_{results_key}.json"]:
        if os.path.exists(f_name):
            try: os.remove(f_name)
            except OSError: pass

    if not os.path.exists("predictions.json"):
        raise RuntimeError(f"Student code subprocess failed to run. Stderr: {proc.stderr}")

    with open("predictions.json", "r") as f:
        preds_data = json.load(f)

    if isinstance(preds_data, dict) and "error" in preds_data:
        raise RuntimeError(
            f"Error in student predict:"
            f" {preds_data['error']}\\n{preds_data.get('traceback', '')}"
        )

    try: os.remove("predictions.json")
    except OSError: pass

    return preds_data
"""


def render_eval_template(template_str, **kwargs):
    env = Environment(
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        autoescape=True,
    )
    return env.from_string(template_str).render(**kwargs)
