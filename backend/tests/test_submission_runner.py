import math
import unittest
from task_modules.submission_runner import calculate_weighted_score

class TestSubmissionRunnerMetrics(unittest.TestCase):

    def test_calculate_weighted_score_no_cfg_higher_better(self):
        # No config, metric defaults to higher is better (e.g. accuracy)
        payload = {"accuracy": 0.85}
        score = calculate_weighted_score(payload, None)
        self.assertEqual(score, 0.85)

    def test_calculate_weighted_score_no_cfg_lower_better(self):
        # No config, metric is lower is better (e.g. mse)
        payload = {"mse": 0.25}
        score = calculate_weighted_score(payload, None)
        self.assertEqual(score, 1.0 / (1.0 + 0.25))

    def test_calculate_weighted_score_no_cfg_brier(self):
        # Brier score specific normalization
        payload = {"brier_score": 0.1}
        score = calculate_weighted_score(payload, None)
        self.assertEqual(score, 0.9)

    def test_calculate_weighted_score_with_cfg_higher_better(self):
        payload = {"accuracy": 0.9, "f1": 0.8}
        cfg = {
            "accuracy": {"weight": 2.0},
            "f1": {"weight": 1.0}
        }
        score = calculate_weighted_score(payload, cfg)
        # Expected: (0.9*2 + 0.8*1) / 3 = 2.6 / 3 = 0.8666...
        self.assertAlmostEqual(score, 0.8666666666666667)

    def test_calculate_weighted_score_with_cfg_lower_better(self):
        payload = {"mse": 0.5, "accuracy": 0.8}
        cfg = {
            "mse": {"weight": 1.0},
            "accuracy": {"weight": 1.0}
        }
        score = calculate_weighted_score(payload, cfg)
        # mse norm: 1 / (1 + 0.5) = 0.6666...
        # Expected: (0.6666...*1 + 0.8*1) / 2 = 1.4666... / 2 = 0.7333...
        self.assertAlmostEqual(score, 0.7333333333333333)

    def test_calculate_weighted_score_nan_inf(self):
        payload = {"accuracy": math.nan, "f1": math.inf}
        cfg = {
            "accuracy": {"weight": 1.0},
            "f1": {"weight": 1.0}
        }
        score = calculate_weighted_score(payload, cfg)
        # NaN and Inf are sanitized to 0.0
        self.assertEqual(score, 0.0)

    def test_calculate_weighted_score_negative_one(self):
        payload = {"mse": -1.0}
        cfg = {"mse": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        # -1.0 is handled to avoid ZeroDivisionError: 1 / (1 + (-1)) -> 0.0
        self.assertEqual(score, 0.0)

if __name__ == '__main__':
    unittest.main()
