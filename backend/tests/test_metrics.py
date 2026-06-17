import os
import sys
import math
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from evaluation_engine import (
    calculate_lcs, compute_bleu, compute_rouge_l, compute_meteor,
    compute_chrf, compute_ter, compute_bertscore, calculate_box_iou,
    compute_map_detection, compute_psnr, compute_ssim, compute_audio_snr,
    compute_mel_lsd, compute_segmentation_iou, compute_segmentation_dice,
    compute_oks, compute_pck, compute_ndcg_at_k, compute_retrieval_metrics,
    evaluate_predictions, validate_parquet_schema, validate_parquet_schema_columns
)


class TestCalculateLcs(unittest.TestCase):
    def test_empty_strings(self):
        self.assertEqual(calculate_lcs("", ""), 0)

    def test_one_empty(self):
        self.assertEqual(calculate_lcs("", "hello"), 0)
        self.assertEqual(calculate_lcs("hello", ""), 0)

    def test_identical(self):
        self.assertEqual(calculate_lcs("the cat sat on the mat", "the cat sat on the mat"), 6)

    def test_no_common(self):
        self.assertEqual(calculate_lcs("abc", "xyz"), 0)

    def test_partial_overlap(self):
        self.assertEqual(calculate_lcs("the cat sat", "the dog sat"), 2)


class TestComputeBleu(unittest.TestCase):
    def test_identical(self):
        score = compute_bleu("the cat sat on the mat", "the cat sat on the mat")
        self.assertGreater(score, 0.9)

    def test_no_overlap(self):
        score = compute_bleu("the cat sat", "xyz abc def")
        self.assertAlmostEqual(score, 0.0, places=2)

    def test_partial(self):
        score = compute_bleu("the cat sat", "the dog ran")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_ref(self):
        score = compute_bleu("", "the cat")
        self.assertEqual(score, 0.0)

    def test_empty_hyp(self):
        score = compute_bleu("the cat", "")
        self.assertEqual(score, 0.0)


class TestComputeRougeL(unittest.TestCase):
    def test_identical(self):
        score = compute_rouge_l("the cat sat on the mat", "the cat sat on the mat")
        self.assertAlmostEqual(score, 1.0)

    def test_no_overlap(self):
        score = compute_rouge_l("the cat", "xyz abc")
        self.assertEqual(score, 0.0)

    def test_partial_lcs(self):
        score = compute_rouge_l("the cat sat", "the dog sat")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_ref(self):
        score = compute_rouge_l("", "the cat")
        self.assertEqual(score, 0.0)

    def test_empty_hyp(self):
        score = compute_rouge_l("the cat", "")
        self.assertEqual(score, 0.0)


class TestComputeMeteor(unittest.TestCase):
    def test_identical(self):
        score = compute_meteor("the cat sat", "the cat sat")
        self.assertAlmostEqual(score, 1.0)

    def test_no_overlap(self):
        score = compute_meteor("the cat", "xyz abc")
        self.assertEqual(score, 0.0)

    def test_both_empty(self):
        score = compute_meteor("", "")
        self.assertEqual(score, 1.0)

    def test_one_empty(self):
        score = compute_meteor("the cat", "")
        self.assertEqual(score, 0.0)

    def test_partial_jaccard(self):
        score = compute_meteor("the cat sat", "the dog ran")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)


class TestComputeChrf(unittest.TestCase):
    def test_identical(self):
        score = compute_chrf("the cat", "the cat")
        self.assertAlmostEqual(score, 1.0)

    def test_no_overlap(self):
        score = compute_chrf("abc", "xyz")
        self.assertEqual(score, 0.0)

    def test_empty_ref(self):
        score = compute_chrf("", "abc")
        self.assertEqual(score, 0.0)

    def test_empty_hyp(self):
        score = compute_chrf("abc", "")
        self.assertEqual(score, 0.0)

    def test_custom_beta(self):
        score = compute_chrf("the cat", "the dog", beta=1)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)


class TestComputeTer(unittest.TestCase):
    def test_identical(self):
        score = compute_ter("the cat sat", "the cat sat")
        self.assertEqual(score, 0.0)

    def test_completely_different(self):
        score = compute_ter("the cat", "xyz abc")
        self.assertEqual(score, 1.0)

    def test_empty_ref(self):
        score = compute_ter("", "the cat")
        self.assertEqual(score, 1.0)

    def test_empty_hyp(self):
        score = compute_ter("the cat sat", "")
        self.assertEqual(score, 1.0)

    def test_partial_edit(self):
        score = compute_ter("the cat sat", "the dog sat")
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestComputeBertscore(unittest.TestCase):
    def test_identical(self):
        score = compute_bertscore(["hello world"], ["hello world"])
        self.assertAlmostEqual(score, 1.0)

    def test_no_overlap(self):
        score = compute_bertscore(["hello world"], ["xyz abc"])
        self.assertAlmostEqual(score, 0.0)

    def test_partial(self):
        score = compute_bertscore(["the cat sat"], ["the dog ran"])
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_ref(self):
        score = compute_bertscore([""], ["hello"])
        self.assertEqual(score, 0.0)

    def test_empty_hyp(self):
        score = compute_bertscore(["hello"], [""])
        self.assertEqual(score, 0.0)

    def test_multiple_pairs(self):
        score = compute_bertscore(["hello world", "cat dog"], ["hello world", "cat dog"])
        self.assertAlmostEqual(score, 1.0)


class TestCalculateBoxIou(unittest.TestCase):
    def test_identical_boxes(self):
        box = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        self.assertAlmostEqual(calculate_box_iou(box, box), 1.0)

    def test_no_overlap(self):
        box1 = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        box2 = {"x_min": 20, "y_min": 20, "x_max": 30, "y_max": 30}
        self.assertEqual(calculate_box_iou(box1, box2), 0.0)

    def test_partial_overlap(self):
        box1 = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        box2 = {"x_min": 5, "y_min": 0, "x_max": 15, "y_max": 10}
        iou = calculate_box_iou(box1, box2)
        self.assertGreater(iou, 0.0)
        self.assertLess(iou, 1.0)

    def test_contained(self):
        box1 = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        box2 = {"x_min": 2, "y_min": 2, "x_max": 8, "y_max": 8}
        iou = calculate_box_iou(box1, box2)
        self.assertGreater(iou, 0.0)
        self.assertLess(iou, 1.0)

    def test_zero_area_box(self):
        box1 = {"x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0}
        box2 = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        self.assertEqual(calculate_box_iou(box1, box2), 0.0)

    def test_both_zero_area(self):
        box1 = {"x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0}
        box2 = {"x_min": 0, "y_min": 0, "x_max": 0, "y_max": 0}
        self.assertEqual(calculate_box_iou(box1, box2), 0.0)

    def test_missing_keys_default_zero(self):
        box1 = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
        box2 = {}
        self.assertEqual(calculate_box_iou(box1, box2), 0.0)


class TestComputeMapDetection(unittest.TestCase):
    def test_empty_true(self):
        ap = compute_map_detection([[]], [[{"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10, "score": 0.9, "label": "cat"}]])
        self.assertEqual(ap, 0.0)

    def test_empty_pred(self):
        ap = compute_map_detection([[{"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10, "label": "cat"}]], [[]])
        self.assertEqual(ap, 0.0)

    def test_both_empty(self):
        ap = compute_map_detection([[]], [[]])
        self.assertEqual(ap, 1.0)

    def test_perfect_match(self):
        true_box = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10, "label": "cat"}
        pred_box = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10, "score": 0.9, "label": "cat"}
        ap = compute_map_detection([[true_box]], [[pred_box]])
        self.assertGreater(ap, 0.0)

    def test_wrong_label(self):
        true_box = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10, "label": "cat"}
        pred_box = {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10, "score": 0.9, "label": "dog"}
        ap = compute_map_detection([[true_box]], [[pred_box]])
        self.assertEqual(ap, 0.0)


class TestComputePsnr(unittest.TestCase):
    def test_identical_bytes(self):
        data = b"hello world"
        score = compute_psnr([data], [data])
        self.assertAlmostEqual(score, 100.0)

    def test_empty_ref(self):
        score = compute_psnr([b""], [b"hello"])
        self.assertEqual(score, 0.0)

    def test_empty_hyp(self):
        score = compute_psnr([b"hello"], [b""])
        self.assertEqual(score, 0.0)

    def test_different_bytes(self):
        score = compute_psnr([b"\x00\x01\x02\x03"], [b"\xff\xfe\xfd\xfc"])
        self.assertGreater(score, 0.0)
        self.assertLess(score, 100.0)

    def test_empty_lists(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            score = compute_psnr([], [])
        self.assertTrue(math.isnan(score) or score == 0.0)


class TestComputeSsim(unittest.TestCase):
    def test_identical_bytes(self):
        data = np.arange(8, dtype=np.float32).tobytes()  # 32 bytes, valid float32 values
        score = compute_ssim([data], [data])
        self.assertAlmostEqual(score, 1.0)

    def test_empty_ref(self):
        score = compute_ssim([b""], [b"hello"])
        self.assertEqual(score, 0.0)

    def test_empty_hyp(self):
        score = compute_ssim([b"hello"], [b""])
        self.assertEqual(score, 0.0)

    def test_different_bytes(self):
        score = compute_ssim([b"\x00\x01\x02\x03"], [b"\xff\xfe\xfd\xfc"])
        self.assertGreaterEqual(score, 0.0)

    def test_constant_identical(self):
        # Non-constant varying data so std > 0 for the fallback path
        data = np.arange(25, dtype=np.float32).tobytes()  # 100 bytes, 25 float32 values
        score = compute_ssim([data], [data])
        self.assertAlmostEqual(score, 1.0)


class TestComputeAudioSnr(unittest.TestCase):
    def test_identical(self):
        data = np.array([1, 2, 3, 4], dtype=np.int16).tobytes()
        score = compute_audio_snr([data], [data])
        self.assertAlmostEqual(score, 100.0)

    def test_empty_ref(self):
        score = compute_audio_snr([b""], [b"\x01\x02"])
        self.assertEqual(score, 0.0)

    def test_empty_hyp(self):
        score = compute_audio_snr([b"\x01\x02"], [b""])
        self.assertEqual(score, 0.0)

    def test_noisy(self):
        ref = np.ones(100, dtype=np.int16).tobytes()
        hyp = (np.ones(100, dtype=np.int16) + 1).tobytes()
        score = compute_audio_snr([ref], [hyp])
        self.assertGreaterEqual(score, 0.0)


class TestComputeMelLsd(unittest.TestCase):
    def test_identical(self):
        data = np.array([1, 2, 3, 4], dtype=np.int16).tobytes()
        score = compute_mel_lsd([data], [data])
        self.assertAlmostEqual(score, 0.0, places=1)

    def test_empty_ref(self):
        score = compute_mel_lsd([b""], [b"\x01\x02"])
        self.assertEqual(score, 10.0)

    def test_empty_hyp(self):
        score = compute_mel_lsd([b"\x01\x02"], [b""])
        self.assertEqual(score, 10.0)


class TestComputeSegmentationIoU(unittest.TestCase):
    def test_identical(self):
        arr = np.array([0, 1, 0, 1], dtype=np.uint8).tobytes()
        score = compute_segmentation_iou([arr], [arr])
        self.assertAlmostEqual(score, 1.0)

    def test_no_overlap(self):
        t = np.array([0, 1, 0, 1], dtype=np.uint8).tobytes()
        p = np.array([1, 0, 1, 0], dtype=np.uint8).tobytes()
        score = compute_segmentation_iou([t], [p])
        self.assertEqual(score, 0.0)

    def test_empty_true(self):
        score = compute_segmentation_iou([b""], [b"\x01"])
        self.assertEqual(score, 0.0)

    def test_empty_pred(self):
        score = compute_segmentation_iou([b"\x01"], [b""])
        self.assertEqual(score, 0.0)

    def test_both_empty(self):
        score = compute_segmentation_iou([b""], [b""])
        self.assertEqual(score, 0.0)


class TestComputeSegmentationDice(unittest.TestCase):
    def test_identical(self):
        arr = np.array([0, 1, 0, 1], dtype=np.uint8).tobytes()
        score = compute_segmentation_dice([arr], [arr])
        self.assertAlmostEqual(score, 1.0)

    def test_no_overlap(self):
        t = np.array([0, 1, 0, 1], dtype=np.uint8).tobytes()
        p = np.array([1, 0, 1, 0], dtype=np.uint8).tobytes()
        score = compute_segmentation_dice([t], [p])
        self.assertEqual(score, 0.0)

    def test_empty_true(self):
        score = compute_segmentation_dice([b""], [b"\x01"])
        self.assertEqual(score, 0.0)

    def test_empty_pred(self):
        score = compute_segmentation_dice([b"\x01"], [b""])
        self.assertEqual(score, 0.0)

    def test_partial_overlap(self):
        t = np.array([0, 1, 1, 0], dtype=np.uint8).tobytes()
        p = np.array([0, 1, 0, 0], dtype=np.uint8).tobytes()
        score = compute_segmentation_dice([t], [p])
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)


class TestComputeOks(unittest.TestCase):
    def test_identical_keypoints(self):
        kp = [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]
        score = compute_oks([kp], [kp])
        self.assertAlmostEqual(score, 1.0)

    def test_far_apart(self):
        t = [[0.0, 0.0], [0.0, 0.0]]
        p = [[100.0, 100.0], [100.0, 100.0]]
        score = compute_oks([t], [p])
        self.assertAlmostEqual(score, 0.0, places=5)

    def test_shape_mismatch(self):
        t = [[0.0, 0.0], [1.0, 1.0]]
        p = [[0.0, 0.0]]
        score = compute_oks([t], [p])
        self.assertEqual(score, 0.0)

    def test_empty(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            score = compute_oks([[]], [[]])
        self.assertTrue(math.isnan(score))


class TestComputePck(unittest.TestCase):
    def test_all_correct(self):
        t = [[0.0, 0.0], [1.0, 1.0]]
        p = [[0.0, 0.0], [1.0, 1.0]]
        score = compute_pck([t], [p], threshold=0.05)
        self.assertAlmostEqual(score, 1.0)

    def test_none_correct(self):
        t = [[0.0, 0.0], [0.0, 0.0]]
        p = [[100.0, 100.0], [100.0, 100.0]]
        score = compute_pck([t], [p], threshold=0.05)
        self.assertEqual(score, 0.0)

    def test_shape_mismatch(self):
        t = [[0.0, 0.0], [1.0, 1.0]]
        p = [[0.0, 0.0]]
        score = compute_pck([t], [p])
        self.assertEqual(score, 0.0)

    def test_empty(self):
        score = compute_pck([[]], [[]])
        self.assertEqual(score, 0.0)

    def test_custom_threshold(self):
        t = [[0.0, 0.0], [0.5, 0.5]]
        p = [[0.05, 0.05], [0.5, 0.5]]
        score_loose = compute_pck([t], [p], threshold=0.1)
        score_tight = compute_pck([t], [p], threshold=0.01)
        self.assertGreater(score_loose, score_tight)


class TestComputeNdcgAtK(unittest.TestCase):
    def test_perfect_ranking(self):
        score = compute_ndcg_at_k([3, 2, 1], k=3)
        self.assertAlmostEqual(score, 1.0)

    def test_worst_ranking(self):
        score = compute_ndcg_at_k([1, 2, 3], k=3)
        self.assertLess(score, 1.0)

    def test_empty(self):
        score = compute_ndcg_at_k([], k=10)
        self.assertEqual(score, 0.0)

    def test_all_zero(self):
        score = compute_ndcg_at_k([0, 0, 0], k=3)
        self.assertEqual(score, 0.0)

    def test_single_item(self):
        score = compute_ndcg_at_k([5], k=10)
        self.assertAlmostEqual(score, 1.0)


class TestComputeRetrievalMetrics(unittest.TestCase):
    def test_perfect_retrieval(self):
        df_true = pd.DataFrame({"query_id": [1, 1], "doc_id": [10, 20]})
        df_pred = pd.DataFrame({"query_id": [1, 1], "doc_id": [10, 20], "score": [0.9, 0.8]})
        result = compute_retrieval_metrics(df_true, df_pred, k=10)
        self.assertAlmostEqual(result["mrr"], 1.0)
        self.assertAlmostEqual(result["recall_10"], 1.0)

    def test_no_relevant(self):
        df_true = pd.DataFrame({"query_id": [1], "doc_id": [10]})
        df_pred = pd.DataFrame({"query_id": [1], "doc_id": [99], "score": [0.9]})
        result = compute_retrieval_metrics(df_true, df_pred, k=10)
        self.assertEqual(result["mrr"], 0.0)
        self.assertEqual(result["recall_10"], 0.0)

    def test_empty_true(self):
        df_true = pd.DataFrame({"query_id": [], "doc_id": []})
        df_pred = pd.DataFrame({"query_id": [1], "doc_id": [10], "score": [0.9]})
        result = compute_retrieval_metrics(df_true, df_pred, k=10)
        self.assertEqual(result["ndcg_10"], 0.0)
        self.assertEqual(result["mrr"], 0.0)
        self.assertEqual(result["recall_10"], 0.0)

    def test_empty_pred(self):
        df_true = pd.DataFrame({"query_id": [1], "doc_id": [10]})
        df_pred = pd.DataFrame({"query_id": [], "doc_id": [], "score": []})
        result = compute_retrieval_metrics(df_true, df_pred, k=10)
        self.assertEqual(result["recall_10"], 0.0)

    def test_multiple_queries(self):
        df_true = pd.DataFrame({"query_id": [1, 1, 2, 2], "doc_id": [10, 20, 30, 40]})
        df_pred = pd.DataFrame({
            "query_id": [1, 1, 2, 2],
            "doc_id": [10, 20, 30, 40],
            "score": [0.9, 0.8, 0.7, 0.6]
        })
        result = compute_retrieval_metrics(df_true, df_pred, k=10)
        self.assertAlmostEqual(result["mrr"], 1.0)
        self.assertAlmostEqual(result["recall_10"], 1.0)


class TestValidateParquetSchema(unittest.TestCase):
    def test_valid_submission(self):
        df = pd.DataFrame({"id": [1, 2], "prediction": [0.5, 0.6]})
        ok, msg = validate_parquet_schema(df, is_submission=True)
        self.assertTrue(ok)
        self.assertIsNone(msg)

    def test_valid_labels(self):
        df = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        ok, msg = validate_parquet_schema(df, is_submission=False)
        self.assertTrue(ok)
        self.assertIsNone(msg)

    def test_missing_id(self):
        df = pd.DataFrame({"prediction": [0.5]})
        ok, msg = validate_parquet_schema(df, is_submission=True)
        self.assertFalse(ok)
        self.assertIn("Submission", msg)
        self.assertIn("missing required column", msg)

    def test_missing_id_labels(self):
        df = pd.DataFrame({"label": [0]})
        ok, msg = validate_parquet_schema(df, is_submission=False)
        self.assertFalse(ok)
        self.assertIn("Labels/Ground Truth", msg)

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        ok, msg = validate_parquet_schema(df)
        self.assertFalse(ok)


class TestEvaluatePredictionsEdgeCases(unittest.TestCase):
    def test_no_metrics_config_defaults_to_accuracy(self):
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        result = evaluate_predictions(df_sub, df_labels, None)
        self.assertIn("accuracy", result)

    def test_empty_metrics_config(self):
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        result = evaluate_predictions(df_sub, df_labels, {})
        self.assertIn("accuracy", result)

    def test_empty_labels_df(self):
        df_sub = pd.DataFrame({"id": [1], "prediction": [0.5]})
        df_labels = pd.DataFrame({"id": [], "label": []})
        result = evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0}})
        self.assertEqual(result, {})

    def test_submission_id_mismatch(self):
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})
        df_labels = pd.DataFrame({"id": [3, 4], "label": [0, 1]})
        with self.assertRaises(ValueError):
            evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0}})

    def test_single_class_accuracy(self):
        df_sub = pd.DataFrame({"id": [1, 2, 3], "prediction": [0, 0, 0]})
        df_labels = pd.DataFrame({"id": [1, 2, 3], "label": [0, 0, 0]})
        result = evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0}})
        self.assertEqual(result["accuracy"], 1.0)

    def test_f1_single_class(self):
        df_sub = pd.DataFrame({"id": [1, 2, 3], "prediction": [0, 0, 0]})
        df_labels = pd.DataFrame({"id": [1, 2, 3], "label": [0, 0, 0]})
        result = evaluate_predictions(df_sub, df_labels, {"f1": {"weight": 1.0, "options": {"average": "macro"}}})
        self.assertIsInstance(result["f1"], float)

    def test_custom_column(self):
        df_sub = pd.DataFrame({"id": [1], "my_pred": [0.5]})
        df_labels = pd.DataFrame({"id": [1], "my_label": [0.5]})
        result = evaluate_predictions(df_sub, df_labels, {"rmse": {"weight": 1.0, "options": {"column": "my_label"}}})
        self.assertIn("rmse", result)

    def test_custom_column_missing(self):
        df_sub = pd.DataFrame({"id": [1], "prediction": [0.5]})
        df_labels = pd.DataFrame({"id": [1], "label": [0.5]})
        result = evaluate_predictions(df_sub, df_labels, {"rmse": {"weight": 1.0, "options": {"column": "nonexistent"}}})
        self.assertEqual(result["rmse"], 0.0)

    def test_balanced_accuracy(self):
        df_sub = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0, 0, 0, 1]})
        df_labels = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 0, 1, 1]})
        result = evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0, "options": {"balanced": "true"}}})
        self.assertIn("accuracy", result)

    def test_exact_match(self):
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": ["cat", "dog"]})
        df_labels = pd.DataFrame({"id": [1, 2], "label": ["cat", "dog"]})
        result = evaluate_predictions(df_sub, df_labels, {"exact_match": {"weight": 1.0}})
        self.assertEqual(result["exact_match"], 1.0)

    def test_exact_match_mismatch(self):
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": ["cat", "bird"]})
        df_labels = pd.DataFrame({"id": [1, 2], "label": ["cat", "dog"]})
        result = evaluate_predictions(df_sub, df_labels, {"exact_match": {"weight": 1.0}})
        self.assertEqual(result["exact_match"], 0.5)

    def test_auc_roc_fallback_on_error(self):
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [0.5, 0.6]})
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        result = evaluate_predictions(df_sub, df_labels, {"auc_roc": {"weight": 1.0}})
        self.assertIsInstance(result["auc_roc"], float)

    def test_logloss_fallback(self):
        df_sub = pd.DataFrame({"id": [1], "prediction": [0.5]})
        df_labels = pd.DataFrame({"id": [1], "label": [0]})
        result = evaluate_predictions(df_sub, df_labels, {"logloss": {"weight": 1.0}})
        self.assertIsInstance(result["logloss"], float)

    def test_mock_metrics(self):
        df_sub = pd.DataFrame({"id": [1], "prediction": [0.5]})
        df_labels = pd.DataFrame({"id": [1], "label": [0]})
        for metric in ["fid", "is", "clip_score", "lpips", "niqe", "nisqa", "pesq"]:
            result = evaluate_predictions(df_sub, df_labels, {metric: {"weight": 1.0}})
            self.assertIn(metric, result)

    def test_retrieval_ndcg_k(self):
        df_true = pd.DataFrame({"id": [1, 2], "query_id": [1, 1], "doc_id": [10, 20], "label": [1, 1]})
        df_pred = pd.DataFrame({"id": [1, 2], "query_id": [1, 1], "doc_id": [10, 20], "score": [0.9, 0.8], "prediction": [0.9, 0.8]})
        result = evaluate_predictions(df_pred, df_true, {"ndcg_k": {"weight": 1.0, "options": {"k": 5}}})
        self.assertIn("ndcg_k", result)

    def test_retrieval_recall_k(self):
        df_true = pd.DataFrame({"id": [1, 2], "query_id": [1, 1], "doc_id": [10, 20], "label": [1, 1]})
        df_pred = pd.DataFrame({"id": [1, 2], "query_id": [1, 1], "doc_id": [10, 20], "score": [0.9, 0.8], "prediction": [0.9, 0.8]})
        result = evaluate_predictions(df_pred, df_true, {"recall_k": {"weight": 1.0, "options": {"k": 5}}})
        self.assertIn("recall_k", result)

    def test_no_prediction_columns(self):
        df_sub = pd.DataFrame({"id": [1, 2]})
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        with self.assertRaises(ValueError):
            evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0}})

    def test_no_label_columns(self):
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})
        df_labels = pd.DataFrame({"id": [1, 2]})
        with self.assertRaises(ValueError):
            evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0}})


class TestValidateParquetSchemaColumns(unittest.TestCase):
    def test_valid_submission_columns(self):
        ok, msg = validate_parquet_schema_columns(["id", "prediction"], is_submission=True)
        self.assertTrue(ok)
        self.assertIsNone(msg)

    def test_valid_labels_columns(self):
        ok, msg = validate_parquet_schema_columns(["id", "label"], is_submission=False)
        self.assertTrue(ok)
        self.assertIsNone(msg)

    def test_missing_id_submission(self):
        ok, msg = validate_parquet_schema_columns(["prediction"], is_submission=True)
        self.assertFalse(ok)
        self.assertIn("Submission", msg)
        self.assertIn("missing required column", msg)

    def test_missing_id_labels(self):
        ok, msg = validate_parquet_schema_columns(["label"], is_submission=False)
        self.assertFalse(ok)
        self.assertIn("Labels/Ground Truth", msg)
        self.assertIn("missing required column", msg)

    def test_empty_columns(self):
        ok, msg = validate_parquet_schema_columns([], is_submission=True)
        self.assertFalse(ok)
        self.assertIn("Submission", msg)

    def test_multiple_columns_with_id(self):
        ok, msg = validate_parquet_schema_columns(["id", "col1", "col2", "col3"], is_submission=True)
        self.assertTrue(ok)
        self.assertIsNone(msg)

    def test_only_id_column(self):
        ok, msg = validate_parquet_schema_columns(["id"], is_submission=True)
        self.assertTrue(ok)
        self.assertIsNone(msg)
