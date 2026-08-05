"""Robust metric computations for the Parquet evaluation engine.

Decompression helpers, the available-metrics registry, and every standard
metric function (classification, regression, image, audio, NLP, detection,
retrieval).
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Caps for mask images decoded host-side. PIL's own default
# DecompressionBombWarning threshold is ~89M pixels; enforce explicit,
# Configurable caps before any pixel data is decoded
MAX_MASK_IMAGE_PIXELS = int(os.environ.get("MAX_MASK_IMAGE_PIXELS", 50 * 1024 * 1024))
MAX_MASK_IMAGE_DIM = int(os.environ.get("MAX_MASK_IMAGE_DIM", 16384))

# ── 0. DECOMPRESSION HELPERS ──


def decode_mask_bytes(b: bytes) -> Any:
    """Decode mask bytes to raw pixel array, handling compressed image formats."""
    if not b:
        return np.array([], dtype=np.uint8)
    if b[:4] == b"\x89PNG" or b[:2] == b"\xff\xd8":
        try:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(b)) as pil_img:
                # Guard against decompression bombs: cap total pixels and
                # Per-axis dimensions before the image is ever decoded
                if (
                    pil_img.width > 0
                    and pil_img.height > 0
                    and pil_img.width * pil_img.height <= MAX_MASK_IMAGE_PIXELS
                    and pil_img.width <= MAX_MASK_IMAGE_DIM
                    and pil_img.height <= MAX_MASK_IMAGE_DIM
                ):
                    return np.array(pil_img.convert("L"), dtype=np.uint8)
                logger.warning(
                    "Rejecting oversized mask image (%dx%d) exceeding caps %dx%d / %d pixels",
                    pil_img.width,
                    pil_img.height,
                    MAX_MASK_IMAGE_DIM,
                    MAX_MASK_IMAGE_DIM,
                    MAX_MASK_IMAGE_PIXELS,
                )
                return np.array([], dtype=np.uint8)
        except Exception:
            logger.debug("Failed to decode image with PIL, falling back to raw bytes")
    return np.frombuffer(b, dtype=np.uint8)


# ── 1. TASK TYPE SCHEMAS & METRICS CONFIG ──


AVAILABLE_METRICS = {
    "accuracy": {"balanced": ["false", "true"]},
    "f1": {"average": ["macro", "micro", "weighted", "binary"]},
    "precision": {"average": ["macro", "micro", "weighted", "binary"]},
    "recall": {"average": ["macro", "micro", "weighted", "binary"]},
    "cohen_kappa": {},
    "matthews_corrcoef": {},
    "auc_roc": {
        "average": ["macro", "micro", "weighted"],
        "multi_class": ["raise", "ovr", "ovo"],
    },
    "logloss": {},
    "brier_score": {},
    "rmse": {"shape": "string", "multioutput": ["uniform_average", "raw_values"]},
    "mse": {"shape": "string", "multioutput": ["uniform_average", "raw_values"]},
    "mae": {"shape": "string", "multioutput": ["uniform_average", "raw_values"]},
    "r_squared": {},
    "mape": {},
    "median_ae": {},
    "seqeval_f1": {},
    "seqeval_precision": {},
    "seqeval_recall": {},
    "bleu": {},
    "rouge": {"rouge_type": ["rouge1", "rouge2", "rougeL"]},
    "meteor": {},
    "chrf": {"beta": ["1", "2", "3"]},
    "ter": {},
    "exact_match": {},
    "map_50": {},
    "map_75": {},
    "map_50_95": {},
    "mean_iou": {},
    "dice": {},
    "pixel_accuracy": {},
    "oks": {},
    "pck": {"threshold": ["0.01", "0.02", "0.05", "0.1", "0.15", "0.2"]},
    "psnr": {},
    "ssim": {},
    "snr": {},
    "mel_lsd": {},
    "si_sdr": {},
    "ndcg_k": {"k": ["5", "10", "20", "50", "100"]},
    "mrr": {},
    "recall_k": {"k": ["5", "10", "20", "50", "100"]},
    "adjusted_rand_index": {},
    "normalized_mutual_info": {},
    "adjusted_mutual_info": {},
    "v_measure": {},
}

# ── 3. ROBUST METRIC COMPUTATIONS WITH FALLBACKS ──


# Basic String/NLP Helpers
def calculate_lcs(x: str, y: str) -> int:
    """Computes the Longest Common Subsequence of tokens for ROUGE-L fallback."""
    x_tokens = x.split()
    y_tokens = y.split()
    m, n = len(x_tokens), len(y_tokens)
    lcsl = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        for j in range(n + 1):
            if i == 0 or j == 0:
                lcsl[i][j] = 0
            elif x_tokens[i - 1] == y_tokens[j - 1]:
                lcsl[i][j] = lcsl[i - 1][j - 1] + 1
            else:
                lcsl[i][j] = max(lcsl[i - 1][j], lcsl[i][j - 1])
    return lcsl[m][n]


# NLP Metric Fallbacks
def compute_bleu(ref: str, hyp: str) -> float:
    """Compute BLEU score for machine translation quality."""
    try:
        from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu

        cc = SmoothingFunction()
        return float(sentence_bleu([ref.split()], hyp.split(), smoothing_function=cc.method1))
    except ImportError:
        # Simplistic word overlap ratio as fallback
        ref_words = set(ref.split())
        hyp_words = set(hyp.split())
        if not ref_words or not hyp_words:
            return 0.0
        overlap = len(ref_words.intersection(hyp_words))
        return overlap / max(len(ref_words), len(hyp_words))


def compute_rouge(ref: str, hyp: str, rouge_type: str = "rougeL") -> float:
    """Compute ROUGE score for summarization evaluation."""
    try:
        from rouge_score import rouge_scorer

        scorer = rouge_scorer.RougeScorer([rouge_type], use_stemmer=True)
        scores = scorer.score(ref, hyp)
        return float(scores[rouge_type].fmeasure)
    except ImportError:
        if rouge_type != "rougeL":
            return 0.0
        lcs = calculate_lcs(ref, hyp)
        ref_len = len(ref.split())
        hyp_len = len(hyp.split())
        if ref_len == 0 or hyp_len == 0:
            return 0.0
        precision = lcs / hyp_len
        recall = lcs / ref_len
        if precision + recall == 0:
            return 0.0
        return (2 * precision * recall) / (precision + recall)


def compute_meteor(ref: str, hyp: str) -> float:
    """Compute METEOR score for machine translation evaluation."""
    try:
        from nltk.translate.meteor_score import meteor_score

        # Nltk meteor_score expects token lists
        return float(meteor_score([ref.split()], hyp.split()))
    except Exception:
        # Fallback to Jaccard similarity
        r = set(ref.split())
        h = set(hyp.split())
        if not r and not h:
            return 1.0
        return len(r.intersection(h)) / len(r.union(h))


def compute_chrf(ref: str, hyp: str, beta: int = 3) -> float:
    """Compute chrF (character n-gram F-score) for translation quality."""
    try:
        from nltk.translate.chrf_score import sentence_chrf

        return float(sentence_chrf(ref, hyp, beta=beta))
    except ImportError:
        ref_chars = set(ref)
        hyp_chars = set(hyp)
        if not ref_chars or not hyp_chars:
            return 0.0
        return len(ref_chars.intersection(hyp_chars)) / len(ref_chars.union(hyp_chars))


def compute_ter(ref: str, hyp: str) -> float:
    """Compute Translation Edit Rate (TER) — higher is worse, 0 = perfect."""
    ref_words = ref.split()
    hyp_words = hyp.split()
    m, n = len(ref_words), len(hyp_words)
    if m == 0:
        return 1.0 if n > 0 else 0.0
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]) + 1
    return min(1.0, dp[m][n] / m)


# Object Detection IoU Matcher
def calculate_box_iou(box1: dict[str, Any], box2: dict[str, Any]) -> float:
    """box = {x_min, y_min, x_max, y_max}"""
    x_min = max(box1.get("x_min", 0), box2.get("x_min", 0))
    y_min = max(box1.get("y_min", 0), box2.get("y_min", 0))
    x_max = min(box1.get("x_max", 0), box2.get("x_max", 0))
    y_max = min(box1.get("y_max", 0), box2.get("y_max", 0))

    inter_area = max(0, x_max - x_min) * max(0, y_max - y_min)
    box1_area = (box1.get("x_max", 0) - box1.get("x_min", 0)) * (
        box1.get("y_max", 0) - box1.get("y_min", 0)
    )
    box2_area = (box2.get("x_max", 0) - box2.get("x_min", 0)) * (
        box2.get("y_max", 0) - box2.get("y_min", 0)
    )

    union_area = box1_area + box2_area - inter_area
    if union_area == 0:
        return 0.0
    return float(inter_area / union_area)


def compute_map_detection(
    y_true: list[list[dict[str, Any]]],
    y_pred: list[list[dict[str, Any]]],
    iou_threshold: float = 0.5,
) -> float:
    """
    Computes Average Precision (AP) at IoU threshold.
    y_true: list of list of boxes (ground truth)
    y_pred: list of list of boxes (predictions with confidence score)
    """
    all_ap = []
    # Loop over class labels if present, otherwise treat as class-agnostic
    # Simplified class-agnostic mAP calculation
    for true_boxes, pred_boxes in zip(y_true, y_pred, strict=False):
        if not true_boxes:
            all_ap.append(1.0 if not pred_boxes else 0.0)
            continue
        if not pred_boxes:
            all_ap.append(0.0)
            continue

        # Sort predictions by confidence
        sorted_preds = sorted(pred_boxes, key=lambda x: x.get("score", 1.0), reverse=True)
        detected = [False] * len(true_boxes)
        tp, fp = 0, 0

        for p in sorted_preds:
            best_iou = 0.0
            best_idx = -1
            for idx, t in enumerate(true_boxes):
                if p.get("label") != t.get("label"):
                    continue
                iou = calculate_box_iou(p, t)
                if iou > best_iou:
                    best_iou = iou
                    best_idx = idx

            if best_iou >= iou_threshold and best_idx != -1 and not detected[best_idx]:
                tp += 1
                detected[best_idx] = True
            else:
                fp += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / len(true_boxes)
        all_ap.append(precision * recall)  # Simple approximation

    return float(np.mean(all_ap))


# CV Signal Quality / Image & Audio Quality Metrics
def compute_psnr(ref_bytes_list: list[bytes], hyp_bytes_list: list[bytes]) -> float:
    """Compute Peak Signal-to-Noise Ratio for image reconstruction quality."""
    psnr_scores = []
    for ref, hyp in zip(ref_bytes_list, hyp_bytes_list, strict=False):
        if not ref or not hyp:
            psnr_scores.append(0.0)
            continue
        try:
            # Try loading via PIL
            import io

            from PIL import Image

            img_ref = np.array(Image.open(io.BytesIO(ref)).convert("RGB"))
            img_hyp = np.array(Image.open(io.BytesIO(hyp)).convert("RGB"))
            if img_ref.shape != img_hyp.shape:
                # Resize hyp to match ref
                img_hyp = np.array(
                    Image.open(io.BytesIO(hyp))
                    .resize((img_ref.shape[1], img_ref.shape[0]))
                    .convert("RGB")
                )
            mse = np.mean((img_ref - img_hyp) ** 2)
            if mse == 0:
                psnr_scores.append(100.0)
            else:
                psnr_scores.append(20 * math.log10(255.0) - 10 * math.log10(mse))
        except Exception:
            # Fallback to direct byte comparison
            min_len = min(len(ref), len(hyp))
            if min_len == 0:
                psnr_scores.append(0.0)
                continue
            arr_ref = np.frombuffer(ref[:min_len], dtype=np.uint8)
            arr_hyp = np.frombuffer(hyp[:min_len], dtype=np.uint8)
            mse = np.mean((arr_ref - arr_hyp) ** 2)
            if mse == 0:
                psnr_scores.append(100.0)
            else:
                psnr_scores.append(20 * math.log10(255.0) - 10 * math.log10(mse))
    return float(np.mean(psnr_scores))


def compute_ssim(ref_bytes_list: list[bytes], hyp_bytes_list: list[bytes]) -> float:
    """Compute Structural Similarity Index for image quality assessment."""
    ssim_scores = []
    for ref, hyp in zip(ref_bytes_list, hyp_bytes_list, strict=False):
        if not ref or not hyp:
            ssim_scores.append(0.0)
            continue
        try:
            import io

            from PIL import Image
            from skimage.metrics import structural_similarity

            img_ref = np.array(Image.open(io.BytesIO(ref)).convert("L"))
            img_hyp = np.array(Image.open(io.BytesIO(hyp)).convert("L"))
            if img_ref.shape != img_hyp.shape:
                img_hyp = np.array(
                    Image.open(io.BytesIO(hyp))
                    .resize((img_ref.shape[1], img_ref.shape[0]))
                    .convert("L")
                )
            ssim_val = structural_similarity(img_ref, img_hyp)
            ssim_scores.append(ssim_val)
        except Exception:
            # Fallback to normalized cross-correlation
            min_len = min(len(ref), len(hyp))
            if min_len == 0:
                ssim_scores.append(0.0)
                continue
            arr_ref = np.frombuffer(ref[:min_len], dtype=np.float32)
            arr_hyp = np.frombuffer(hyp[:min_len], dtype=np.float32)
            norm_ref = arr_ref - np.mean(arr_ref)
            norm_hyp = arr_hyp - np.mean(arr_hyp)
            std_ref = np.std(arr_ref)
            std_hyp = np.std(arr_hyp)
            if std_ref * std_hyp == 0:
                ssim_scores.append(0.0)
            else:
                ssim_scores.append(float(np.mean(norm_ref * norm_hyp) / (std_ref * std_hyp)))
    return float(np.mean(ssim_scores))


def compute_audio_snr(ref_bytes_list: list[bytes], hyp_bytes_list: list[bytes]) -> float:
    """Compute Signal-to-Noise Ratio for audio quality assessment."""
    snr_scores = []
    for ref, hyp in zip(ref_bytes_list, hyp_bytes_list, strict=False):
        if not ref or not hyp:
            snr_scores.append(0.0)
            continue
        try:
            # Interpret as audio float arrays
            arr_ref = np.frombuffer(ref, dtype=np.int16).astype(np.float32)
            arr_hyp = np.frombuffer(hyp[: len(ref)], dtype=np.int16).astype(np.float32)
            if len(arr_hyp) < len(arr_ref):
                arr_ref = arr_ref[: len(arr_hyp)]

            signal_power = np.mean(arr_ref**2)
            noise_power = np.mean((arr_ref - arr_hyp) ** 2)
            if noise_power == 0:
                snr_scores.append(100.0)
            else:
                snr_scores.append(10 * np.log10(signal_power / noise_power))
        except Exception:
            snr_scores.append(0.0)
    return float(np.mean(snr_scores))


def compute_si_sdr(ref_bytes_list: list[bytes], hyp_bytes_list: list[bytes]) -> float:
    """Compute true Scale-Invariant Signal-to-Distortion Ratio (SI-SDR).

    Projects the estimate onto the reference: ``alpha = <est, ref> / <ref, ref>``,
    then ``target = alpha * ref`` and ``SI-SDR = 10*log10(||target||^2 /
    ||est - target||^2)``. Scale-invariance means a constant-scaled estimate is a
    perfect score, unlike plain SNR.
    """
    sdr_scores = []
    for ref, hyp in zip(ref_bytes_list, hyp_bytes_list, strict=False):
        if not ref or not hyp:
            sdr_scores.append(0.0)
            continue
        try:
            arr_ref = np.frombuffer(ref, dtype=np.int16).astype(np.float32)
            arr_hyp = np.frombuffer(hyp[: len(ref)], dtype=np.int16).astype(np.float32)
            if len(arr_hyp) < len(arr_ref):
                arr_ref = arr_ref[: len(arr_hyp)]

            ref_power = float(np.dot(arr_ref, arr_ref))
            if ref_power == 0:
                sdr_scores.append(0.0)
                continue
            alpha = float(np.dot(arr_hyp, arr_ref)) / ref_power
            target = alpha * arr_ref
            noise = arr_hyp - target
            target_power = float(np.dot(target, target))
            noise_power = float(np.dot(noise, noise))
            if noise_power == 0:
                sdr_scores.append(100.0)
            elif target_power == 0:
                sdr_scores.append(0.0)
            else:
                sdr_scores.append(10 * np.log10(target_power / noise_power))
        except Exception:
            sdr_scores.append(0.0)
    return float(np.mean(sdr_scores))


def compute_mel_lsd(ref_bytes_list: list[bytes], hyp_bytes_list: list[bytes]) -> float:
    """Compute Mel-scale Log Spectral Distance for audio quality."""
    lsd_scores = []
    for ref, hyp in zip(ref_bytes_list, hyp_bytes_list, strict=False):
        if not ref or not hyp:
            lsd_scores.append(10.0)  # High distance fallback
            continue
        try:
            import scipy.fftpack as fft

            arr_ref = np.frombuffer(ref, dtype=np.int16).astype(np.float32)
            arr_hyp = np.frombuffer(hyp[: len(ref)], dtype=np.int16).astype(np.float32)
            if len(arr_hyp) < len(arr_ref):
                arr_ref = arr_ref[: len(arr_hyp)]

            spec_ref = np.abs(fft.fft(arr_ref))
            spec_hyp = np.abs(fft.fft(arr_hyp))

            # Prevent log(0)
            spec_ref = np.clip(spec_ref, 1e-6, None)
            spec_hyp = np.clip(spec_hyp, 1e-6, None)

            log_ratio = 20 * np.log10(spec_ref / spec_hyp)
            lsd = np.sqrt(np.mean(log_ratio**2))
            lsd_scores.append(lsd)
        except Exception:
            # Fallback distance
            lsd_scores.append(5.0)
    return float(np.mean(lsd_scores))


# Segmentation Helpers
def compute_segmentation_iou(y_true: list[bytes], y_pred: list[bytes]) -> float:
    """Compute Intersection over Union for image segmentation."""
    iou_scores = []
    for t, p in zip(y_true, y_pred, strict=False):
        if not t or not p:
            iou_scores.append(0.0)
            continue
        arr_t = decode_mask_bytes(t)
        arr_p = decode_mask_bytes(p)
        if len(arr_p) < len(arr_t):
            arr_t = arr_t[: len(arr_p)]
        intersection = np.logical_and(arr_t > 0, arr_p > 0).sum()
        union = np.logical_or(arr_t > 0, arr_p > 0).sum()
        iou_scores.append(intersection / union if union > 0 else 0.0)
    return float(np.mean(iou_scores))


def compute_segmentation_dice(y_true: list[bytes], y_pred: list[bytes]) -> float:
    """Compute Dice coefficient for image segmentation overlap."""
    dice_scores = []
    for t, p in zip(y_true, y_pred, strict=False):
        if not t or not p:
            dice_scores.append(0.0)
            continue
        arr_t = decode_mask_bytes(t)
        arr_p = decode_mask_bytes(p)
        if len(arr_p) < len(arr_t):
            arr_t = arr_t[: len(arr_p)]
        intersection = np.logical_and(arr_t > 0, arr_p > 0).sum()
        total = (arr_t > 0).sum() + (arr_p > 0).sum()
        dice_scores.append((2 * intersection) / total if total > 0 else 0.0)
    return float(np.mean(dice_scores))


# Keypoints / OKS
def compute_oks(y_true: list[Any], y_pred: list[Any]) -> float:
    """Compute Object Keypoint Similarity for pose estimation."""
    oks_scores = []
    for t, p in zip(y_true, y_pred, strict=False):
        try:
            # Expected format is list/array of coordinates
            arr_t = np.array(t, dtype=np.float32).reshape(-1, 2)
            arr_p = np.array(p, dtype=np.float32).reshape(-1, 2)
            if arr_t.shape != arr_p.shape:
                oks_scores.append(0.0)
                continue

            dists_sq = np.sum((arr_t - arr_p) ** 2, axis=1)
            # Scale estimation (box area)
            scale = 1.0  # Assume normalized keypoints
            sigmas = 0.05  # Standard constant
            oks = np.mean(np.exp(-dists_sq / (2 * (scale**2) * (sigmas**2))))
            oks_scores.append(oks)
        except Exception:
            oks_scores.append(0.0)
    return float(np.mean(oks_scores))


def compute_pck(y_true: list[Any], y_pred: list[Any], threshold: float = 0.05) -> float:
    """Compute Percentage of Correct Keypoints for pose estimation."""
    pck_scores = []
    for t, p in zip(y_true, y_pred, strict=False):
        try:
            arr_t = np.array(t, dtype=np.float32).reshape(-1, 2)
            arr_p = np.array(p, dtype=np.float32).reshape(-1, 2)
            if arr_t.shape != arr_p.shape or len(arr_t) == 0:
                pck_scores.append(0.0)
                continue
            dists = np.sqrt(np.sum((arr_t - arr_p) ** 2, axis=1))
            correct = np.sum(dists <= threshold)
            pck_scores.append(correct / len(arr_t))
        except Exception:
            pck_scores.append(0.0)
    return float(np.mean(pck_scores))


# Retrieval NDCG/MRR
def compute_ndcg_at_k(relevance_scores: list[float] | np.ndarray[Any, Any], k: int = 10) -> float:
    """Compute Normalized Discounted Cumulative Gain for ranking quality."""
    relevance_scores = np.asarray(relevance_scores, dtype=np.float64)[:k]
    if relevance_scores.size == 0:
        return 0.0

    # DCG
    dcg = np.sum(relevance_scores / np.log2(np.arange(2, relevance_scores.size + 2)))

    # IDCG (sorted desc)
    idcg_scores = np.sort(relevance_scores)[::-1]
    idcg = np.sum(idcg_scores / np.log2(np.arange(2, idcg_scores.size + 2)))

    if idcg == 0:
        return 0.0
    return float(dcg / idcg)


def compute_retrieval_metrics(
    df_true: pd.DataFrame, df_pred: pd.DataFrame, k: int = 10
) -> dict[str, float]:
    """
    df_true: Columns query_id, doc_id
    df_pred: Columns query_id, doc_id, score
    """
    # Group by query_id
    queries = df_true["query_id"].unique()
    ndcg_list = []
    mrr_list = []
    recall_list = []

    for q in queries:
        true_docs = set(df_true[df_true["query_id"] == q]["doc_id"])
        pred_df = df_pred[df_pred["query_id"] == q].sort_values("score", ascending=False)
        pred_docs = list(pred_df["doc_id"])

        # 1. NDCG@K
        relevance = [1.0 if doc in true_docs else 0.0 for doc in pred_docs[:k]]
        ndcg_list.append(compute_ndcg_at_k(relevance, k=k))

        # 2. MRR
        mrr = 0.0
        for rank, doc in enumerate(pred_docs):
            if doc in true_docs:
                mrr = 1.0 / (rank + 1)
                break
        mrr_list.append(mrr)

        # 3. Recall@K
        recall = 0.0
        if len(true_docs) > 0:
            hits = len(set(pred_docs[:k]).intersection(true_docs))
            recall = hits / len(true_docs)
        recall_list.append(recall)

    return {
        f"ndcg_{k}": float(np.mean(ndcg_list)) if ndcg_list else 0.0,
        "mrr": float(np.mean(mrr_list)) if mrr_list else 0.0,
        f"recall_{k}": float(np.mean(recall_list)) if recall_list else 0.0,
    }
