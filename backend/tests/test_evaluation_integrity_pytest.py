"""Security and correctness regressions for the evaluation pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from services.evaluation import (
    EvaluationError,
    derive_task_split_key,
    evaluate_predictions,
    read_parquet_bounded,
    split_evaluation_frames,
)
from tasks.task_modules.submission_runner import calculate_weighted_score


def _classification_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = pd.DataFrame({"id": [1, 2, 3], "label": [0, 1, 0]})
    submission = pd.DataFrame({"id": [3, 1, 2], "prediction": [0, 0, 1]})
    return submission, labels


def test_predictions_are_aligned_one_to_one_by_id() -> None:
    submission, labels = _classification_frames()

    result = evaluate_predictions(submission, labels, {"accuracy": {"weight": 1.0}})

    assert result["accuracy"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("submission", "expected_code"),
    [
        (
            pd.DataFrame({"id": [1, 1, 3], "prediction": [0, 1, 0]}),
            "EVALUATION_DUPLICATE_ID",
        ),
        (
            pd.DataFrame({"id": [1, None, 3], "prediction": [0, 1, 0]}),
            "EVALUATION_NULL_ID",
        ),
        (
            pd.DataFrame({"id": [1, 2, 4], "prediction": [0, 1, 0]}),
            "EVALUATION_ID_SET_MISMATCH",
        ),
        (
            pd.DataFrame({"id": ["1", "2", "3"], "prediction": [0, 1, 0]}),
            "EVALUATION_ID_TYPE_MISMATCH",
        ),
    ],
)
def test_invalid_prediction_identifiers_fail_evaluation(
    submission: pd.DataFrame, expected_code: str
) -> None:
    labels = pd.DataFrame({"id": [1, 2, 3], "label": [0, 1, 0]})

    with pytest.raises(EvaluationError) as exc_info:
        evaluate_predictions(submission, labels, {"accuracy": {"weight": 1.0}})

    assert exc_info.value.code == expected_code


def test_retrieval_duplicate_pairs_fail_evaluation() -> None:
    labels = pd.DataFrame({"query_id": [1, 1], "doc_id": ["a", "b"]})
    submission = pd.DataFrame({"query_id": [1, 1], "doc_id": ["a", "a"], "score": [0.9, 0.8]})

    with pytest.raises(EvaluationError) as exc_info:
        evaluate_predictions(submission, labels, {"mrr": {"weight": 1.0}})

    assert exc_info.value.code == "EVALUATION_DUPLICATE_ID"


def test_retrieval_query_sets_must_match() -> None:
    labels = pd.DataFrame({"query_id": [1, 2], "doc_id": ["a", "b"]})
    submission = pd.DataFrame({"query_id": [1, 3], "doc_id": ["a", "c"], "score": [0.9, 0.8]})

    with pytest.raises(EvaluationError) as exc_info:
        evaluate_predictions(submission, labels, {"mrr": {"weight": 1.0}})

    assert exc_info.value.code == "EVALUATION_QUERY_SET_MISMATCH"


def test_secret_split_is_stable_and_keeps_query_groups_whole() -> None:
    labels = pd.DataFrame({"query_id": [1, 1, 2, 2, 3, 3, 4, 4], "doc_id": list("abcdefgh")})
    submission = labels.assign(score=list(range(8, 0, -1)))
    split_key = derive_task_split_key("test-secret", "task-1")

    first = split_evaluation_frames(submission, labels, 50, split_key)
    second = split_evaluation_frames(
        submission.sample(frac=1), labels.sample(frac=1), 50, split_key
    )

    first_public_queries = set(first[1]["query_id"])
    assert first_public_queries == set(second[1]["query_id"])
    assert set(first[0]["query_id"]) == first_public_queries
    assert set(first[2]["query_id"]).isdisjoint(first_public_queries)


def test_different_split_secrets_change_membership() -> None:
    submission, labels = _classification_frames()
    first_key = derive_task_split_key("first-secret", "task-1")
    second_key = derive_task_split_key("second-secret", "task-1")

    first = split_evaluation_frames(submission, labels, 34, first_key)
    second = split_evaluation_frames(submission, labels, 34, second_key)

    assert set(first[1]["id"]) != set(second[1]["id"])


def test_datetime_identifiers_can_be_split() -> None:
    identifiers = pd.date_range("2026-01-01", periods=4, tz="UTC")
    labels = pd.DataFrame({"id": identifiers, "label": [0, 1, 0, 1]})
    submission = pd.DataFrame({"id": identifiers, "prediction": [0, 1, 0, 1]})

    split = split_evaluation_frames(
        submission,
        labels,
        50,
        derive_task_split_key("test-secret", "datetime-task"),
    )

    assert len(split[1]) == 2
    assert len(split[3]) == 2


def test_custom_evaluator_missing_metric_fails() -> None:
    submission, labels = _classification_frames()
    code = "def evaluate(df_sub, df_labels, options):\n    return {'other': 1.0}\n"

    with pytest.raises(EvaluationError) as exc_info:
        evaluate_predictions(
            submission,
            labels,
            {"required": {"weight": 1.0}},
            custom_eval_code=code,
        )

    assert exc_info.value.code == "EVALUATOR_METRIC_MISSING"


def test_custom_evaluator_crash_fails() -> None:
    submission, labels = _classification_frames()
    code = "def evaluate(df_sub, df_labels, options):\n    raise RuntimeError('boom')\n"

    with pytest.raises(EvaluationError) as exc_info:
        evaluate_predictions(
            submission,
            labels,
            {"required": {"weight": 1.0}},
            custom_eval_code=code,
        )

    assert exc_info.value.code == "EVALUATOR_EXECUTION_FAILED"


def test_failed_required_metric_is_not_renormalized() -> None:
    config = {
        "accuracy": {"weight": 0.5},
        "required_metric": {"weight": 0.5},
    }

    with pytest.raises(EvaluationError):
        calculate_weighted_score({"accuracy": 1.0, "required_metric": None}, config)


def test_map_50_95_includes_point_95() -> None:
    labels = pd.DataFrame({"id": [1], "label": [[{"label": "x"}]]})
    submission = pd.DataFrame({"id": [1], "prediction": [[{"label": "x"}]]})
    thresholds: list[float] = []

    def _capture_threshold(_true, _pred, iou_threshold=0.5):
        thresholds.append(iou_threshold)
        return 1.0

    with patch("services.evaluation.engine.compute_map_detection", side_effect=_capture_threshold):
        evaluate_predictions(submission, labels, {"map_50_95": {"weight": 1.0}})

    assert thresholds[-1] == pytest.approx(0.95)
    assert len(thresholds) == 10


def test_detection_recall_matches_each_prediction_once() -> None:
    box = {"label": "x", "x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10}
    labels = pd.DataFrame({"id": [1], "label": [[box, box.copy()]]})
    submission = pd.DataFrame({"id": [1], "prediction": [[box.copy()]]})

    result = evaluate_predictions(submission, labels, {"recall": {"weight": 1.0}})

    assert result["recall"] == pytest.approx(0.5)


def test_parquet_metadata_limits_are_checked_before_read(tmp_path) -> None:
    parquet_path = tmp_path / "submission.parquet"
    pd.DataFrame({"id": [1, 2], "prediction": [0, 1]}).to_parquet(parquet_path)

    with pytest.raises(EvaluationError) as exc_info:
        read_parquet_bounded(
            parquet_path,
            max_file_bytes=parquet_path.stat().st_size,
            max_uncompressed_bytes=1024 * 1024,
            max_rows=1,
            max_columns=10,
        )

    assert exc_info.value.code == "EVALUATION_PARQUET_LIMIT_EXCEEDED"
