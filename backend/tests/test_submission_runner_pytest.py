import math
import pytest
from task_modules.submission_runner import calculate_weighted_score


class TestSubmissionRunnerMetrics:
    def test_calculate_weighted_score_no_cfg_higher_better(self):
        payload = {"accuracy": 0.85}
        score = calculate_weighted_score(payload, None)
        assert score == 0.85

    def test_calculate_weighted_score_no_cfg_lower_better(self):
        payload = {"mse": 0.25}
        score = calculate_weighted_score(payload, None)
        assert score == 1.0 / (1.0 + 0.25)

    def test_calculate_weighted_score_no_cfg_brier(self):
        payload = {"brier_score": 0.1}
        score = calculate_weighted_score(payload, None)
        assert score == 0.9

    def test_calculate_weighted_score_with_cfg_higher_better(self):
        payload = {"accuracy": 0.9, "f1": 0.8}
        cfg = {"accuracy": {"weight": 2.0}, "f1": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert round(score, 10) == round(0.8666666666666667, 10)

    def test_calculate_weighted_score_with_cfg_lower_better(self):
        payload = {"mse": 0.5, "accuracy": 0.8}
        cfg = {"mse": {"weight": 1.0}, "accuracy": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert round(score, 10) == round(0.7333333333333333, 10)

    def test_calculate_weighted_score_nan_inf(self):
        payload = {"accuracy": math.nan, "f1": math.inf}
        cfg = {"accuracy": {"weight": 1.0}, "f1": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert score == 0.0

    def test_calculate_weighted_score_negative_one(self):
        payload = {"mse": -1.0}
        cfg = {"mse": {"weight": 1.0}}
        score = calculate_weighted_score(payload, cfg)
        assert score == 0.0
