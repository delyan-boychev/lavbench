"""Main evaluation routine and custom evaluator execution for parquet-based scoring."""

from __future__ import annotations

import contextlib
import logging
import math
import os
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    adjusted_mutual_info_score,
    adjusted_rand_score,
    balanced_accuracy_score,
    brier_score_loss,
    cohen_kappa_score,
    f1_score,
    log_loss,
    matthews_corrcoef,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    normalized_mutual_info_score,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    v_measure_score,
)

from config import Config
from services.evaluation.exceptions import EvaluationError
from services.evaluation.metrics import (
    calculate_box_iou,
    compute_audio_snr,
    compute_bleu,
    compute_chrf,
    compute_map_detection,
    compute_mel_lsd,
    compute_meteor,
    compute_oks,
    compute_pck,
    compute_psnr,
    compute_retrieval_metrics,
    compute_rouge,
    compute_segmentation_dice,
    compute_segmentation_iou,
    compute_si_sdr,
    compute_ssim,
    compute_ter,
    decode_mask_bytes,
)
from services.evaluation.validation import validate_evaluation_frames

logger = logging.getLogger(__name__)
# ── 4. CUSTOM EVALUATOR EXECUTION ──

# Trusted harness run INSIDE the sandbox container. The untrusted
# Evaluator code is exec'd here — isolated from the worker host by
# --network none --cap-drop ALL --user 65534 --read-only --pids-limit
_CUSTOM_EVAL_HARNESS = '''\
"""Trusted harness: loads an admin-provided evaluator and applies it to data."""
import json
import sys


def main() -> int:
    eval_path, sub_path, labels_path, opts_path, result_path = sys.argv[1:6]
    ns: dict = {}
    with open(eval_path, encoding="utf-8") as f:
        code = f.read()
    exec(compile(code, eval_path, "exec"), ns)  # noqa: S102
    evaluate = ns.get("evaluate")
    if not callable(evaluate):
        sys.stderr.write("Custom evaluator missing 'evaluate' function\\n")
        return 1
    import pandas as pd

    df_sub = pd.read_parquet(sub_path)
    df_labels = pd.read_parquet(labels_path)
    with open(opts_path, encoding="utf-8") as f:
        options = json.load(f)
    result = evaluate(df_sub, df_labels, options or {})
    if not isinstance(result, dict):
        sys.stderr.write(
            "evaluate() must return a dict of metric -> float, got "
            + type(result).__name__
            + "\\n"
        )
        return 1
    clean = {}
    for key, val in result.items():
        try:
            clean[str(key)] = float(val)
        except (TypeError, ValueError):
            sys.stderr.write(f"Non-numeric metric value for {key!r}: {val!r}\\n")
            return 1
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(clean, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _run_custom_evaluator_sandbox(
    code: str,
    df_sub: pd.DataFrame,
    df_labels: pd.DataFrame,
    options: dict[str, Any] | None,
    image_tag: str,
) -> dict[str, float]:
    """Run the custom evaluator inside a hardened container.

    Infrastructure and evaluator failures raise :class:`EvaluationError`.
    """
    import json
    import shutil
    import tempfile

    from tasks.task_modules.docker_utils import _get_client, image_exists
    from utils.worker_utils import run_sandbox

    workdir = tempfile.mkdtemp(prefix="custom_eval_")
    try:
        eval_path = os.path.join(workdir, "evaluator.py")
        sub_path = os.path.join(workdir, "predictions.parquet")
        labels_path = os.path.join(workdir, "labels.parquet")
        opts_path = os.path.join(workdir, "options.json")
        harness_path = os.path.join(workdir, "harness.py")
        result_path = os.path.join(workdir, "result.json")

        with open(eval_path, "w", encoding="utf-8") as f:
            f.write(code)
        df_sub.to_parquet(sub_path, index=False)
        df_labels.to_parquet(labels_path, index=False)
        with open(opts_path, "w", encoding="utf-8") as f:
            json.dump(options or {}, f)
        with open(harness_path, "w", encoding="utf-8") as f:
            f.write(_CUSTOM_EVAL_HARNESS)

        if not image_exists(image_tag):
            raise EvaluationError(
                "EVALUATOR_IMAGE_MISSING",
                f"Custom evaluator image {image_tag!r} is not available.",
            )
        docker_client = _get_client()

        logs: list[str] = []
        retcode, _stdout, stderr, is_timeout = run_sandbox(
            docker_client,
            image_tag,
            [
                "python",
                "/work/harness.py",
                "/work/evaluator.py",
                "/work/predictions.parquet",
                "/work/labels.parquet",
                "/work/options.json",
                "/work/result.json",
            ],
            seed_dir=workdir,
            collect_files=[("/work/result.json", result_path)],
            logs_list=logs,
            time_limit=300,
            mem_limit="1g",
            cpu_count=1,
            working_dir="/work",
        )
        if is_timeout:
            raise EvaluationError(
                "EVALUATOR_TIMEOUT",
                "Custom evaluator exceeded the 300 second time limit.",
            )
        if retcode != 0 or not os.path.exists(result_path):
            logger.warning(
                "Custom evaluator failed in sandbox (rc=%s, timeout=%s): %s",
                retcode,
                is_timeout,
                stderr.strip() or (logs[-1] if logs else ""),
            )
            raise EvaluationError(
                "EVALUATOR_EXECUTION_FAILED",
                "Custom evaluator did not complete successfully.",
            )
        if os.path.getsize(result_path) > Config.MAX_EVALUATOR_RESULT_BYTES:
            raise EvaluationError(
                "EVALUATOR_INVALID_OUTPUT",
                "Custom evaluator output exceeds the configured size limit.",
            )
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        if not isinstance(result, dict):
            raise EvaluationError(
                "EVALUATOR_INVALID_OUTPUT",
                "Custom evaluator output must be a metric mapping.",
            )
        clean: dict[str, float] = {}
        for key, value in result.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise EvaluationError(
                    "EVALUATOR_INVALID_OUTPUT",
                    f"Custom evaluator metric {key!r} is not numeric.",
                ) from exc
            if not math.isfinite(numeric):
                raise EvaluationError(
                    "EVALUATOR_INVALID_OUTPUT",
                    f"Custom evaluator metric {key!r} is not finite.",
                )
            clean[str(key)] = numeric
        return clean
    except EvaluationError:
        raise
    except Exception as exc:
        logger.warning("Custom evaluator sandbox failed: %s", exc)
        raise EvaluationError(
            "EVALUATOR_SANDBOX_UNAVAILABLE",
            "Custom evaluator sandbox is unavailable.",
        ) from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _run_custom_evaluator(
    code: str,
    df_sub: pd.DataFrame,
    df_labels: pd.DataFrame,
    options: dict[str, Any] | None = None,
    sandbox_image: str | None = None,
) -> dict[str, float]:
    """Executes a custom evaluator script and returns its metric results.

    The script must define:
        METRIC_NAME (str)
        evaluate(df_sub, df_labels, options) -> dict[str, float]

    When *sandbox_image* is provided, the code runs inside a hardened
    container; otherwise it runs in-process (test/dev only).
    """
    if sandbox_image:
        return _run_custom_evaluator_sandbox(code, df_sub, df_labels, options, sandbox_image)
    try:
        local_ns: dict[str, Any] = {}
        exec(code, local_ns)  # noqa: S102
        evaluate = local_ns.get("evaluate")
        if not callable(evaluate):
            raise EvaluationError(
                "EVALUATOR_INVALID_SCRIPT",
                "Custom evaluator is missing a callable evaluate function.",
            )
        result = evaluate(df_sub, df_labels, options or {})
        if not isinstance(result, dict):
            raise EvaluationError(
                "EVALUATOR_INVALID_OUTPUT",
                "Custom evaluator output must be a metric mapping.",
            )
        clean: dict[str, float] = {}
        for key, value in result.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise EvaluationError(
                    "EVALUATOR_INVALID_OUTPUT",
                    f"Custom evaluator metric {key!r} is not numeric.",
                ) from exc
            if not math.isfinite(numeric):
                raise EvaluationError(
                    "EVALUATOR_INVALID_OUTPUT",
                    f"Custom evaluator metric {key!r} is not finite.",
                )
            clean[str(key)] = numeric
        return clean
    except EvaluationError:
        raise
    except Exception as exc:
        logger.warning("Custom evaluator failed: %s", exc)
        raise EvaluationError(
            "EVALUATOR_EXECUTION_FAILED",
            "Custom evaluator did not complete successfully.",
        ) from exc


# ── 5. MAIN EVALUATION & METRIC RESOLUTION ROUTINE ──


def evaluate_predictions(
    df_sub: pd.DataFrame,
    df_labels: pd.DataFrame,
    metrics_cfg: dict[str, Any] | None,
    custom_eval_code: str | None = None,
    sandbox_image: str | None = None,
) -> dict[str, Any]:
    """
    Computes all requested metrics between df_sub (submission) and df_labels (ground truth).
    metrics_cfg: dict of {metric_name: {weight: float, higher_is_better: bool}}
    custom_eval_code: optional Python code defining a custom evaluator
    sandbox_image: docker image tag to run the custom evaluator in (hardened container)
    """
    if not metrics_cfg:
        metrics_cfg = {"accuracy": {"weight": 1.0, "higher_is_better": True}}

    df_sub, df_labels = validate_evaluation_frames(df_sub, df_labels)

    if len(df_labels) == 0:
        return {}

    # Retrieval metrics use query groups instead of row-wise label alignment
    if "query_id" in df_labels.columns:
        payload = {}
        for m_name in metrics_cfg:
            m_name_clean = m_name.lower().strip()
            cfg = metrics_cfg[m_name]
            m_opts = cfg.get("options", {}) if isinstance(cfg, dict) else {}
            k_val = 10
            if "k" in m_opts:
                with contextlib.suppress(ValueError, TypeError):
                    k_val = int(m_opts["k"])
            elif "ndcg_" in m_name_clean or "recall_" in m_name_clean:
                parts = m_name_clean.split("_")
                if len(parts) > 1 and parts[1].isdigit():
                    k_val = int(parts[1])

            retrieval_results = compute_retrieval_metrics(df_labels, df_sub, k=k_val)
            if m_name_clean == "ndcg_k":
                result_key = f"ndcg_{k_val}"
            elif m_name_clean == "recall_k":
                result_key = f"recall_{k_val}"
            else:
                result_key = m_name_clean
            if result_key not in retrieval_results:
                raise EvaluationError(
                    "EVALUATION_UNKNOWN_METRIC",
                    f"Configured retrieval metric {m_name!r} is not supported.",
                )
            payload[m_name] = retrieval_results[result_key]
        return payload

    # Extract arrays per metric
    payload = {}

    for m_name in metrics_cfg:
        m_name_clean = m_name.lower().strip()
        val: float | None = 0.0
        failed = False
        cfg = metrics_cfg[m_name]
        m_opts = cfg.get("options", {}) if isinstance(cfg, dict) else {}

        custom_col = m_opts.get("column", "")
        if custom_col:
            if custom_col not in df_labels.columns or custom_col not in df_sub.columns:
                raise EvaluationError(
                    "EVALUATION_MISSING_METRIC_COLUMN",
                    f"Configured column {custom_col!r} is missing from predictions or labels.",
                )
            y_true = df_labels[custom_col].tolist()
            y_pred = df_sub[custom_col].tolist()
        else:
            non_id_cols_sub = [c for c in df_sub.columns if c not in ["id", "query_id", "doc_id"]]
            non_id_cols_label = [
                c for c in df_labels.columns if c not in ["id", "query_id", "doc_id"]
            ]
            if not non_id_cols_sub:
                raise ValueError(
                    "Submission parquet contains no prediction "
                    "columns (only metadata columns like 'id')."
                )
            if not non_id_cols_label:
                raise ValueError(
                    "Labels parquet contains no label columns (only metadata columns like 'id')."
                )
            pred_col = (
                next((c for c in non_id_cols_sub if c.lower() == "prediction"), None)
                or non_id_cols_sub[0]
            )
            label_col = next((c for c in non_id_cols_label if c.lower() == "label"), None) or (
                non_id_cols_label[0] if non_id_cols_label else df_labels.columns[-1]
            )
            y_true = df_labels[label_col].tolist()
            y_pred = df_sub[pred_col].tolist()
        if m_name_clean == "accuracy":
            try:
                sequence_types = (list, tuple, np.ndarray, dict)
                true_shapes = [isinstance(value, sequence_types) for value in y_true]
                prediction_shapes = [isinstance(value, sequence_types) for value in y_pred]
                if true_shapes != prediction_shapes or any(
                    isinstance(value, dict) for value in [*y_true, *y_pred]
                ):
                    failed = True
                elif str(m_opts.get("balanced", "false")).lower() == "true":
                    val = balanced_accuracy_score(y_true, y_pred)
                else:
                    val = accuracy_score(y_true, y_pred)
            except Exception as e:
                logger.warning("accuracy calculation failed: %s", e)
                failed = True
        elif m_name_clean == "f1":
            # Dispatch: string inputs → QA word-overlap F1; else → classification F1
            first_true = y_true[0] if len(y_true) > 0 else None
            if isinstance(first_true, str):
                f1_scores = []
                for t, p in zip(y_true, y_pred, strict=False):
                    t_words = str(t).strip().lower().split()
                    p_words = str(p).strip().lower().split()
                    if not t_words or not p_words:
                        f1_scores.append(1.0 if t_words == p_words else 0.0)
                        continue
                    overlap = set(t_words).intersection(set(p_words))
                    if len(overlap) == 0:
                        f1_scores.append(0.0)
                        continue
                    prec = len(overlap) / len(p_words)
                    rec = len(overlap) / len(t_words)
                    f1_scores.append((2 * prec * rec) / (prec + rec))
                val = np.mean(f1_scores) if f1_scores else 0.0
            else:
                try:
                    val = f1_score(y_true, y_pred, average=m_opts.get("average", "macro"))
                except Exception as e:
                    logger.warning("f1 calculation failed: %s", e)
                    failed = True
        elif m_name_clean == "precision":
            try:
                val = precision_score(
                    y_true,
                    y_pred,
                    average=m_opts.get("average", "macro"),
                    zero_division=0,
                )
            except Exception as e:
                logger.warning("precision calculation failed: %s", e)
                failed = True
        elif m_name_clean == "recall":
            # Dispatch: list entries (boxes) → detection box recall; else → classification recall
            first_true = y_true[0] if len(y_true) > 0 else None
            if isinstance(first_true, list):
                recall_scores = []
                for true_boxes, pred_boxes in zip(y_true, y_pred, strict=False):
                    if not true_boxes:
                        recall_scores.append(1.0)
                        continue
                    if not pred_boxes:
                        recall_scores.append(0.0)
                        continue
                    matched_predictions: set[int] = set()
                    hits = 0
                    for t in true_boxes:
                        best_index = -1
                        best_iou = 0.0
                        for index, p in enumerate(pred_boxes):
                            if index in matched_predictions or p.get("label") != t.get("label"):
                                continue
                            iou = calculate_box_iou(p, t)
                            if iou >= 0.5 and iou > best_iou:
                                best_iou = iou
                                best_index = index
                        if best_index >= 0:
                            matched_predictions.add(best_index)
                            hits += 1
                    recall_scores.append(hits / len(true_boxes))
                val = np.mean(recall_scores) if recall_scores else 0.0
            else:
                try:
                    val = recall_score(
                        y_true,
                        y_pred,
                        average=m_opts.get("average", "macro"),
                        zero_division=0,
                    )
                except Exception as e:
                    logger.warning("recall calculation failed: %s", e)
                    failed = True
        elif m_name_clean == "cohen_kappa":
            try:
                val = cohen_kappa_score(y_true, y_pred)
            except Exception as e:
                logger.warning("cohen_kappa calculation failed: %s", e)
                failed = True
        elif m_name_clean == "matthews_corrcoef":
            try:
                val = matthews_corrcoef(y_true, y_pred)
            except Exception as e:
                logger.warning("matthews_corrcoef calculation failed: %s", e)
                failed = True

        # 2. Probabilistic Metrics
        elif m_name_clean == "auc_roc":
            try:
                avg = m_opts.get("average", "macro")
                mc = m_opts.get("multi_class", "raise")
                val = roc_auc_score(y_true, y_pred, average=avg, multi_class=mc)
            except Exception as e:
                logger.warning(
                    "roc_auc_score failed for metric '%s': %s",
                    m_name,
                    e,
                )
                failed = True
        elif m_name_clean == "logloss":
            try:
                val = log_loss(y_true, y_pred)
            except Exception as e:
                logger.warning(
                    "log_loss failed for metric '%s': %s",
                    m_name,
                    e,
                )
                failed = True
        elif m_name_clean == "brier_score":
            try:
                val = brier_score_loss(y_true, y_pred)
            except Exception as e:
                logger.warning(
                    "brier_score_loss failed for metric '%s': %s",
                    m_name,
                    e,
                )
                failed = True

        # 3. Regression Metrics
        elif m_name_clean in ["rmse", "mse", "mae"]:
            try:
                if len(y_true) > 0 and isinstance(y_true[0], (bytes, bytearray)):
                    scores = []
                    for t, p in zip(y_true, y_pred, strict=False):
                        if not t or not p:
                            failed = True
                            break
                        min_len = min(len(t), len(p))
                        arr_t = np.frombuffer(t[:min_len], dtype=np.uint8)
                        arr_p = np.frombuffer(p[:min_len], dtype=np.uint8)
                        if m_name_clean == "rmse":
                            scores.append(math.sqrt(mean_squared_error(arr_t, arr_p)))
                        elif m_name_clean == "mse":
                            scores.append(mean_squared_error(arr_t, arr_p))
                        elif m_name_clean == "mae":
                            scores.append(mean_absolute_error(arr_t, arr_p))
                    if failed or not scores:
                        failed = True
                    else:
                        val = np.mean(scores)
                else:
                    shape_str = str(m_opts.get("shape", "0")).strip()
                    mo = m_opts.get("multioutput", "uniform_average")
                    if shape_str == "0" or not shape_str:
                        if m_name_clean == "rmse":
                            res = mean_squared_error(y_true, y_pred, multioutput=mo)
                            val = (
                                np.mean(np.sqrt(res))
                                if isinstance(res, np.ndarray)
                                else math.sqrt(res)
                            )
                        elif m_name_clean == "mse":
                            res = mean_squared_error(y_true, y_pred, multioutput=mo)
                            val = np.mean(res) if isinstance(res, np.ndarray) else res
                        elif m_name_clean == "mae":
                            res = mean_absolute_error(y_true, y_pred, multioutput=mo)
                            val = np.mean(res) if isinstance(res, np.ndarray) else res
                    else:
                        try:
                            shape_tuple = tuple(int(x.strip()) for x in shape_str.split(","))
                            scores = []
                            for t, p in zip(y_true, y_pred, strict=False):
                                arr_t = np.array(t).reshape(shape_tuple)
                                arr_p = np.array(p).reshape(shape_tuple)
                                if m_name_clean == "rmse":
                                    scores.append(math.sqrt(np.mean((arr_t - arr_p) ** 2)))
                                elif m_name_clean == "mse":
                                    scores.append(np.mean((arr_t - arr_p) ** 2))
                                elif m_name_clean == "mae":
                                    scores.append(np.mean(np.abs(arr_t - arr_p)))
                            val = np.mean(scores)
                        except Exception as e:
                            logger.warning("Shape error for metric '%s': %s", m_name, e)
                            failed = True
            except Exception as e:
                logger.warning("Regression calculation failed for metric '%s': %s", m_name, e)
                failed = True
        elif m_name_clean == "r_squared":
            try:
                val = r2_score(y_true, y_pred)
            except Exception as e:
                logger.warning("r_squared failed: %s", e)
                failed = True
        elif m_name_clean == "mape":
            try:
                val = mean_absolute_percentage_error(y_true, y_pred)
            except Exception as e:
                logger.warning("mape failed: %s", e)
                failed = True
        elif m_name_clean == "median_ae":
            try:
                val = median_absolute_error(y_true, y_pred)
            except Exception as e:
                logger.warning("median_ae failed: %s", e)
                failed = True

        # 4. NER / Tagging (SeqEval approximate fallback)
        elif m_name_clean in ["seqeval_f1", "seqeval_precision", "seqeval_recall"]:
            # Flatten lists to compare elements
            flat_true = [
                str(x)
                for sublist in y_true
                for x in (sublist if isinstance(sublist, list) else [sublist])
            ]
            flat_pred = [
                str(x)
                for sublist in y_pred
                for x in (sublist if isinstance(sublist, list) else [sublist])
            ]
            min_len = min(len(flat_true), len(flat_pred))
            if min_len == 0:
                val = 0.0
            else:
                flat_true = flat_true[:min_len]
                flat_pred = flat_pred[:min_len]
                if m_name_clean == "seqeval_f1":
                    val = f1_score(flat_true, flat_pred, average="macro", zero_division=0)
                elif m_name_clean == "seqeval_precision":
                    val = precision_score(flat_true, flat_pred, average="macro", zero_division=0)
                else:
                    val = recall_score(flat_true, flat_pred, average="macro", zero_division=0)

        # 5. Generative NLP Metrics
        elif m_name_clean == "bleu":
            val = np.mean([compute_bleu(t, p) for t, p in zip(y_true, y_pred, strict=False)])
        elif m_name_clean == "rouge":
            rouge_type = str(m_opts.get("rouge_type", "rougeL"))
            pairs = zip(y_true, y_pred, strict=False)
            val = np.mean([compute_rouge(t, p, rouge_type=rouge_type) for t, p in pairs])
        elif m_name_clean == "rouge_l":
            val = np.mean([compute_rouge(t, p) for t, p in zip(y_true, y_pred, strict=False)])
        elif m_name_clean == "meteor":
            val = np.mean([compute_meteor(t, p) for t, p in zip(y_true, y_pred, strict=False)])
        elif m_name_clean == "chrf":
            beta = m_opts.get("beta", 3)
            val = np.mean(
                [compute_chrf(t, p, beta=beta) for t, p in zip(y_true, y_pred, strict=False)]
            )
        elif m_name_clean == "ter":
            val = np.mean([compute_ter(t, p) for t, p in zip(y_true, y_pred, strict=False)])

        # 6. QA Extractive
        elif m_name_clean == "exact_match":
            em_list = [
                1.0 if str(t).strip().lower() == str(p).strip().lower() else 0.0
                for t, p in zip(y_true, y_pred, strict=False)
            ]
            val = np.mean(em_list)
        # 7. CV Object Detection
        elif m_name_clean == "map_50":
            val = compute_map_detection(y_true, y_pred, iou_threshold=0.5)
        elif m_name_clean == "map_75":
            val = compute_map_detection(y_true, y_pred, iou_threshold=0.75)
        elif m_name_clean == "map_50_95":
            thresholds = np.arange(0.5, 0.951, 0.05)
            vals = [
                compute_map_detection(y_true, y_pred, iou_threshold=float(th)) for th in thresholds
            ]
            val = np.mean(vals)

        # 8. CV Segmentation
        elif m_name_clean == "mean_iou":
            val = compute_segmentation_iou(y_true, y_pred)
        elif m_name_clean == "dice":
            val = compute_segmentation_dice(y_true, y_pred)
        elif m_name_clean == "pixel_accuracy":
            accs = []
            for t, p in zip(y_true, y_pred, strict=False):
                if not t or not p:
                    accs.append(0.0)
                    continue
                arr_t = decode_mask_bytes(t)
                arr_p = decode_mask_bytes(p)
                if len(arr_p) < len(arr_t):
                    arr_t = arr_t[: len(arr_p)]
                accs.append(accuracy_score(arr_t, arr_p))
            val = np.mean(accs)

        # 9. Keypoints
        elif m_name_clean == "oks":
            val = compute_oks(y_true, y_pred)
        elif m_name_clean == "pck":
            threshold = m_opts.get("threshold", 0.05)
            val = compute_pck(y_true, y_pred, threshold=threshold)

        # 10. Image Quality
        elif m_name_clean == "psnr":
            val = compute_psnr(y_true, y_pred)
        elif m_name_clean == "ssim":
            val = compute_ssim(y_true, y_pred)

        # 11. Audio Quality
        elif m_name_clean == "snr":
            val = compute_audio_snr(y_true, y_pred)
        elif m_name_clean == "mel_lsd":
            val = compute_mel_lsd(y_true, y_pred)
        elif m_name_clean == "si_sdr":
            val = compute_si_sdr(y_true, y_pred)

        # 12. Clustering
        elif m_name_clean == "adjusted_rand_index":
            val = adjusted_rand_score(y_true, y_pred)
        elif m_name_clean == "normalized_mutual_info":
            val = normalized_mutual_info_score(y_true, y_pred)
        elif m_name_clean == "adjusted_mutual_info":
            val = adjusted_mutual_info_score(y_true, y_pred)
        elif m_name_clean == "v_measure":
            val = v_measure_score(y_true, y_pred)

        # 13. Custom evaluator dispatch
        elif custom_eval_code:
            custom_result = _run_custom_evaluator(
                custom_eval_code, df_sub, df_labels, m_opts, sandbox_image
            )
            if m_name_clean not in custom_result:
                raise EvaluationError(
                    "EVALUATOR_METRIC_MISSING",
                    f"Custom evaluator did not return configured metric {m_name!r}.",
                )
            val = custom_result[m_name_clean]
        else:
            raise EvaluationError(
                "EVALUATION_UNKNOWN_METRIC",
                f"Configured metric {m_name!r} is not supported.",
            )

        if failed:
            raise EvaluationError(
                "EVALUATION_METRIC_FAILED",
                f"Configured metric {m_name!r} could not be calculated.",
            )
        elif val is not None:
            numeric = float(val)
            if not math.isfinite(numeric):
                raise EvaluationError(
                    "EVALUATION_METRIC_FAILED",
                    f"Configured metric {m_name!r} returned a non-finite value.",
                )
            payload[m_name] = numeric

    return payload
