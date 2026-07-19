"""Direct unit tests for _validate_evaluator_script in routes.tasks."""

from routes.tasks import _validate_evaluator_script


class TestValidateEvaluatorScript:
    """Test all code paths in _validate_evaluator_script."""

    def _make_script(self, **overrides):
        parts = {
            "metric_name": 'METRIC_NAME = "my_metric"',
            "sub_cols": 'SUBMISSION_COLUMNS = [{"name": "id", "type": "string"}]',
            "lbl_cols": 'LABELS_COLUMNS = [{"name": "id", "type": "string"}]',
            "options": 'EVALUATOR_OPTIONS = {"threshold": 0.5}',
            "evaluate": "def evaluate(df_sub, df_labels, options=None): pass",
        }
        parts.update(overrides)
        return "\n".join(v if v is not None else "# not set" for v in parts.values())

    # ── Happy path ──

    def test_valid_full_script(self):
        script = self._make_script()
        result, err = _validate_evaluator_script(script)
        assert err is None
        assert result["metric_name"] == "my_metric"
        assert result["submission_columns"] == [{"name": "id", "type": "string"}]
        assert result["labels_columns"] == [{"name": "id", "type": "string"}]
        assert result["options"] == {"threshold": 0.5}

    def test_valid_no_options(self):
        script = self._make_script(options=None)
        result, err = _validate_evaluator_script(script)
        assert err is None
        assert result["options"] == {}

    def test_valid_empty_options_dict(self):
        script = self._make_script(options="EVALUATOR_OPTIONS = {}")
        result, err = _validate_evaluator_script(script)
        assert err is None
        assert result["options"] == {}

    def test_valid_multiple_columns(self):
        script = self._make_script(
            sub_cols=(
                "SUBMISSION_COLUMNS = ["
                '{"name": "id", "type": "int64"}, {"name": "pred", "type": "float64"}]'
            ),
            lbl_cols=(
                "LABELS_COLUMNS = ["
                '{"name": "id", "type": "int64"}, {"name": "label", "type": "float64"}]'
            ),
        )
        result, err = _validate_evaluator_script(script)
        assert err is None
        assert len(result["submission_columns"]) == 2
        assert len(result["labels_columns"]) == 2

    # ── Syntax error ──

    def test_syntax_error(self):
        result, err = _validate_evaluator_script("def foo(:")
        assert result is None
        assert err is not None
        assert "Syntax error" in err

    # ── METRIC_NAME errors ──

    def test_missing_metric_name(self):
        script = self._make_script(metric_name=None)
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "METRIC_NAME" in err

    def test_metric_name_not_string(self):
        script = self._make_script(metric_name="METRIC_NAME = 42")
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "non-empty string" in err

    def test_metric_name_empty_string(self):
        script = self._make_script(metric_name='METRIC_NAME = ""')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "non-empty string" in err

    def test_metric_name_whitespace(self):
        script = self._make_script(metric_name='METRIC_NAME = "   "')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "non-empty string" in err

    # ── SUBMISSION_COLUMNS errors ──

    def test_missing_submission_columns(self):
        script = self._make_script(sub_cols=None)
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "SUBMISSION_COLUMNS" in err

    def test_submission_columns_not_a_list(self):
        script = self._make_script(sub_cols='SUBMISSION_COLUMNS = "not_a_list"')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "must be a list" in err

    def test_submission_columns_entry_missing_name(self):
        script = self._make_script(sub_cols='SUBMISSION_COLUMNS = [{"type": "string"}]')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "name" in err and "type" in err

    def test_submission_columns_entry_missing_type(self):
        script = self._make_script(sub_cols='SUBMISSION_COLUMNS = [{"name": "id"}]')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "name" in err and "type" in err

    def test_submission_columns_entry_name_not_string(self):
        script = self._make_script(
            sub_cols='SUBMISSION_COLUMNS = [{"name": 123, "type": "string"}]'
        )
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "must be strings" in err

    def test_submission_columns_entry_type_not_string(self):
        script = self._make_script(sub_cols='SUBMISSION_COLUMNS = [{"name": "id", "type": 456}]')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "must be strings" in err

    # ── LABELS_COLUMNS errors ──

    def test_missing_labels_columns(self):
        script = self._make_script(lbl_cols=None)
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "LABELS_COLUMNS" in err

    def test_labels_columns_not_a_list(self):
        script = self._make_script(lbl_cols='LABELS_COLUMNS = "bad"')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "must be a list" in err

    def test_labels_columns_entry_missing_name(self):
        script = self._make_script(lbl_cols='LABELS_COLUMNS = [{"type": "float"}]')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "name" in err

    def test_labels_columns_entry_name_not_string(self):
        script = self._make_script(lbl_cols='LABELS_COLUMNS = [{"name": True, "type": "string"}]')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "must be strings" in err

    # ── EVALUATOR_OPTIONS errors ──

    def test_options_not_a_dict(self):
        script = self._make_script(options="EVALUATOR_OPTIONS = [1, 2, 3]")
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "must be a dict" in err

    def test_options_is_string(self):
        script = self._make_script(options='EVALUATOR_OPTIONS = "bad"')
        result, err = _validate_evaluator_script(script)
        assert result is None
        assert "must be a dict" in err
