"""Run an admin- or jury-provided evaluator as a resource-limited Python subprocess."""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import tempfile
from typing import Any

import pandas as pd

from config import Config
from services.evaluation.exceptions import EvaluationError
from utils.limited_process import run_limited

logger = logging.getLogger(__name__)

_EXIT_INVALID_SCRIPT = 3
_EXIT_INVALID_OUTPUT = 4
_MAX_FILE_BYTES = 256 * 1024 * 1024

# Trusted harness, run under utils.limited_process: loads the evaluator and scores every split
_HARNESS = '''\
"""Trusted harness: load the evaluator, score each split and write the metrics."""
import json
import sys


def main() -> int:
    eval_path, opts_path, result_path, *pairs = sys.argv[1:]
    with open(eval_path, encoding="utf-8") as f:
        source = f.read()
    try:
        code = compile(source, "evaluator.py", "exec")
    except SyntaxError as exc:
        sys.stderr.write(f"Evaluator does not compile: {exc}\\n")
        return 3
    namespace = {"__name__": "evaluator"}
    exec(code, namespace)
    evaluate = namespace.get("evaluate")
    if not callable(evaluate):
        sys.stderr.write("Evaluator does not define a callable evaluate\\n")
        return 3

    import pandas as pd

    with open(opts_path, encoding="utf-8") as f:
        options = json.load(f)
    results = []
    for sub_path, labels_path in zip(pairs[0::2], pairs[1::2], strict=True):
        result = evaluate(pd.read_parquet(sub_path), pd.read_parquet(labels_path), options)
        if not isinstance(result, dict):
            sys.stderr.write(f"evaluate returned {type(result).__name__}, not a dict\\n")
            return 4
        clean = {}
        for key, value in result.items():
            try:
                clean[str(key)] = float(value)
            except (TypeError, ValueError):
                sys.stderr.write(f"Metric {key!r} is not numeric\\n")
                return 4
        results.append(clean)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(results, f)
    return 0


sys.exit(main())
'''


def _clean_metrics(result: Any) -> dict[str, float]:
    """Require a mapping of metric names to finite floats."""
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


def _parse_results(result_path: str, count: int) -> list[dict[str, float]]:
    if os.path.getsize(result_path) > Config.MAX_EVALUATOR_RESULT_BYTES:
        raise EvaluationError(
            "EVALUATOR_INVALID_OUTPUT",
            "Custom evaluator output exceeds the configured size limit.",
        )
    with open(result_path, encoding="utf-8") as f:
        results = json.load(f)
    if not isinstance(results, list) or len(results) != count:
        raise EvaluationError(
            "EVALUATOR_INVALID_OUTPUT",
            "Custom evaluator output must be a metric mapping.",
        )
    return [_clean_metrics(result) for result in results]


def run_custom_evaluator_splits(
    code: str,
    splits: list[tuple[pd.DataFrame, pd.DataFrame]],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float]]:
    """Score every split in one evaluator process and return one metric mapping per split.

    The evaluator runs in the worker's interpreter with a clean environment, a private
    temporary folder and resource limits; it has no network or filesystem isolation, an
    accepted risk because evaluators come only from admins and jury and every upload is audited.
    """
    time_limit = Config.CUSTOM_EVALUATOR_TIME_LIMIT_SECONDS
    workdir = tempfile.mkdtemp(prefix="custom_eval_")
    try:
        eval_path = os.path.join(workdir, "evaluator.py")
        opts_path = os.path.join(workdir, "options.json")
        result_path = os.path.join(workdir, "result.json")
        pairs: list[str] = []
        try:
            with open(eval_path, "w", encoding="utf-8") as f:
                f.write(code)
            with open(opts_path, "w", encoding="utf-8") as f:
                json.dump(options or {}, f)
            for index, (df_sub, df_labels) in enumerate(splits):
                sub_path = os.path.join(workdir, f"predictions_{index}.parquet")
                labels_path = os.path.join(workdir, f"labels_{index}.parquet")
                df_sub.to_parquet(sub_path, index=False)
                df_labels.to_parquet(labels_path, index=False)
                pairs.extend((sub_path, labels_path))
            run = run_limited(
                _HARNESS,
                [eval_path, opts_path, result_path, *pairs],
                workdir,
                memory_mb=Config.CUSTOM_EVALUATOR_MEMORY_MB,
                time_limit=time_limit,
                max_file_bytes=_MAX_FILE_BYTES,
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Custom evaluator could not start: %s", exc)
            raise EvaluationError(
                "EVALUATOR_EXECUTION_FAILED",
                "Custom evaluator did not complete successfully.",
            ) from exc

        if run.timed_out:
            raise EvaluationError(
                "EVALUATOR_TIMEOUT",
                f"Custom evaluator exceeded the {time_limit} second time limit.",
            )
        if run.returncode != 0 or not os.path.exists(result_path):
            logger.warning("Custom evaluator failed (rc=%s): %s", run.returncode, run.output_tail)
            if run.returncode == _EXIT_INVALID_SCRIPT:
                raise EvaluationError(
                    "EVALUATOR_INVALID_SCRIPT",
                    "Custom evaluator does not compile or define a callable evaluate function.",
                )
            if run.returncode == _EXIT_INVALID_OUTPUT:
                raise EvaluationError(
                    "EVALUATOR_INVALID_OUTPUT",
                    "Custom evaluator output must map metric names to numbers.",
                )
            raise EvaluationError(
                "EVALUATOR_EXECUTION_FAILED",
                "Custom evaluator did not complete successfully.",
            )
        try:
            return _parse_results(result_path, len(splits))
        except (OSError, ValueError) as exc:
            raise EvaluationError(
                "EVALUATOR_INVALID_OUTPUT",
                "Custom evaluator output is not valid JSON.",
            ) from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
