import io
import json
from unittest.mock import patch

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_notebook(content="print('hello')"):
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [{"cell_type": "code", "source": [content]}],
        "metadata": {},
    }
    return io.BytesIO(json.dumps(nb).encode())


def _make_csv(text="a,b,c\n1,2,3\n"):
    return io.BytesIO(text.encode())


def _make_parquet_with_id():
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"id": [1, 2, 3], "label": ["x", "y", "z"]})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════
#  CREATE — /api/challenges/<id>/tasks  (POST)
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateTask:
    """POST /api/challenges/<challenge_id>/tasks"""

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_basic(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        data = {
            "title": "Basic Task",
            "description": "A basic test task",
            "baseline_notebook": (nb, "baseline.ipynb"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["title"] == "Basic Task"
        assert body["description"] == "A basic test task"
        assert body["challenge_id"] == sample_challenge.id
        assert "baseline.ipynb" in [f["filename"] for f in body["files"]]
        assert body["stage_id"] is None

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_with_all_fields(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        sol_nb = _make_notebook("print('solution')")

        metrics = json.dumps({"accuracy": {"weight": 1.0}})
        hf_ds = json.dumps(["dataset1"])
        hf_models = json.dumps(["model1"])

        data = {
            "title": "Full Task",
            "description": "All fields filled in",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "solution_notebook": (sol_nb, "solution.ipynb"),
            "ram_limit_mb": "1024",
            "time_limit_sec": "600",
            "gpu_required": "true",
            "base_docker_image": "python:3.11-slim",
            "apt_packages": "curl git",
            "pip_requirements": "requests>=2.0\npandas",
            "ban_magic_commands": "true",
            "banned_imports": "os,sys",
            "whitelisted_imports": "pandas,numpy",
            "metrics_config": metrics,
            "hf_datasets": hf_ds,
            "hf_models": hf_models,
            "public_eval_percentage": "50",
            "max_submissions_per_period": "5",
            "submission_period_hours": "24",
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["title"] == "Full Task"
        assert body["ram_limit_mb"] == 1024
        assert body["time_limit_sec"] == 600
        assert body["gpu_required"] is True
        assert body["base_docker_image"] == "python:3.11-slim"
        assert body["public_eval_percentage"] == 50
        assert body["solution_notebook_path"] is not None
        assert "solution.ipynb" in body["solution_notebook_path"]

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_with_gpu_flag_false(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        data = {
            "title": "GPU Task",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "gpu_required": "false",
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        assert resp.get_json()["gpu_required"] is False

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_with_dataset_file(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        csv = _make_csv()
        data = {
            "title": "Dataset Task",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "file0": (csv, "train.csv"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        body = resp.get_json()
        files = body["files"]
        filenames = [f["filename"] for f in files]
        assert "train.csv" in filenames

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_with_labels_parquet(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        prq = _make_parquet_with_id()
        data = {
            "title": "Labels Parquet Task",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "file0": (prq, "labels.parquet"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        files = resp.get_json()["files"]
        assert "labels.parquet" in [f["filename"] for f in files]

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_with_evaluator_script(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        script = io.BytesIO(
            b'METRIC_NAME = "my_eval"\n'
            b'SUBMISSION_COLUMNS = [{"name": "id", "type": "string"}]\n'
            b'LABELS_COLUMNS = [{"name": "id", "type": "string"}]\n'
            b"def evaluate(): pass\n"
        )
        data = {
            "title": "Eval Script Task",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "evaluator_script": (script, "eval.py"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["evaluator_script_path"] is not None
        assert body["evaluator_metric_name"] == "my_eval"

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_with_stage(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        sample_stage,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        data = {
            "title": "Staged Task",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "stage_id": str(sample_stage.id),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        assert resp.get_json()["stage_id"] == str(sample_stage.id)

    # ── Error cases ──

    def test_create_missing_title(self, client, db_session, sample_challenge, tokens, auth_headers):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        data = {"baseline_notebook": (nb, "baseline.ipynb")}
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "ERR_VALIDATION"

    def test_create_missing_baseline(
        self, client, db_session, sample_challenge, tokens, auth_headers
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        data = {"title": "No NB"}
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "baseline" in resp.get_json()["error"].lower()

    def test_create_wrong_baseline_extension(
        self, client, db_session, sample_challenge, tokens, auth_headers
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        data = {
            "title": "Bad Ext",
            "baseline_notebook": (io.BytesIO(b"{}"), "notebook.txt"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "extension" in resp.get_json()["error"].lower()

    def test_create_competitor_forbidden(
        self, client, db_session, sample_challenge, tokens, auth_headers
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.competitor)
        nb = _make_notebook()
        data = {
            "title": "Hacker Task",
            "baseline_notebook": (nb, "baseline.ipynb"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 403

    def test_create_challenge_not_found(self, client, db_session, tokens, auth_headers):
        url = "/api/challenges/99999/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        data = {
            "title": "Ghost Task",
            "baseline_notebook": (nb, "baseline.ipynb"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 404

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_invalid_metrics(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        data = {
            "title": "Bad Metrics",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "metrics_config": "not-json",
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "ERR_INVALID_METRIC_CONFIG"

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_invalid_docker_image(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        data = {
            "title": "Bad Docker",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "base_docker_image": "UPPERCASE_IMAGE!!",
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "ERR_INVALID_DOCKER_IMAGE"

    def test_create_unauthenticated_returns_403(self, client, db_session, sample_challenge):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        nb = _make_notebook()
        data = {
            "title": "No Auth",
            "baseline_notebook": (nb, "baseline.ipynb"),
        }
        resp = client.post(url, data=data, content_type="multipart/form-data")
        assert resp.status_code == 403

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_invalid_evaluator_syntax(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        script = io.BytesIO(b"def foo(:")
        data = {
            "title": "Bad Eval Syntax",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "evaluator_script": (script, "eval.py"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_EVALUATOR_SCRIPT_INVALID"
        assert "Syntax error" in resp.get_json()["error"]

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_invalid_evaluator_missing_metric_name(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        script = io.BytesIO(
            b'SUBMISSION_COLUMNS = [{"name": "id", "type": "string"}]\n'
            b'LABELS_COLUMNS = [{"name": "id", "type": "string"}]\n'
            b"def evaluate(): pass\n"
        )
        data = {
            "title": "Bad Eval No Metric",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "evaluator_script": (script, "eval.py"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_EVALUATOR_SCRIPT_INVALID"
        assert "Missing required variable: METRIC_NAME" in resp.get_json()["error"]

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_invalid_evaluator_bad_columns(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        script = io.BytesIO(
            b'METRIC_NAME = "x"\nSUBMISSION_COLUMNS = "not_a_list"\n'
            b'LABELS_COLUMNS = [{"name": "id", "type": "string"}]\n'
            b"def evaluate(): pass\n"
        )
        data = {
            "title": "Bad Eval Columns",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "evaluator_script": (script, "eval.py"),
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_EVALUATOR_SCRIPT_INVALID"
        assert "must be a list" in resp.get_json()["error"]

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_create_with_columns_metadata(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        url = f"/api/challenges/{sample_challenge.id}/tasks"
        headers = auth_headers(tokens.admin)
        nb = _make_notebook()
        metrics = json.dumps(
            {
                "accuracy": {"weight": 1.0},
                "_columns": [{"name": "id", "type": "string", "desc": "primary identifier"}],
            }
        )
        data = {
            "title": "Task with columns",
            "baseline_notebook": (nb, "baseline.ipynb"),
            "metrics_config": metrics,
        }
        resp = client.post(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["title"] == "Task with columns"
        assert body["metrics_config"] == {
            "accuracy": {"weight": 1.0},
            "_columns": [{"name": "id", "type": "string", "desc": "primary identifier"}],
        }


# ═══════════════════════════════════════════════════════════════════════════
#  UPDATE — /api/tasks/<id>  (PUT)
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateTask:
    """PUT /api/tasks/<task_id>"""

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_basic_fields(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        from models import Task

        task = Task(
            title="Original",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()

        url = f"/api/tasks/{task.id}"
        headers = auth_headers(tokens.admin)
        data = {
            "title": "Updated Title",
            "description": "Updated description",
            "ram_limit_mb": "2048",
            "time_limit_sec": "900",
        }
        resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["title"] == "Updated Title"
        assert body["description"] == "Updated description"
        assert body["ram_limit_mb"] == 2048
        assert body["time_limit_sec"] == 900

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_clear_limits(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        from models import Task

        task = Task(
            title="Original",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()

        url = f"/api/tasks/{task.id}"
        headers = auth_headers(tokens.admin)
        data = {
            "ram_limit_mb": "",
            "time_limit_sec": "",
        }
        resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ram_limit_mb"] is None
        assert body["time_limit_sec"] is None

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_replace_file(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        import os
        import tempfile

        from models import Task

        task = Task(
            title="File Replace",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
            files=json.dumps([{"filename": "old.csv", "saved_name": "old.csv", "size_bytes": 4}]),
        )
        db_session.add(task)
        db_session.flush()

        upload_dir = os.path.join(tempfile.gettempdir(), f"task_{task.id}")
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, "old.csv"), "w") as f:
            f.write("a,b\n1,2\n")

        # Override UPLOAD_FOLDER for this test
        with patch.dict(
            client.application.config,
            {"UPLOAD_FOLDER": tempfile.gettempdir()},
            clear=False,
        ):
            url = f"/api/tasks/{task.id}"
            headers = auth_headers(tokens.admin)

            new_csv = _make_csv("x,y\n3,4\n")
            data = {
                "title": "File Replace",
                "deleted_files": json.dumps(["old.csv"]),
                "file0": (new_csv, "new.csv"),
            }
            resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 200
        files = resp.get_json()["files"]
        filenames = [f["filename"] for f in files]
        assert "old.csv" not in filenames
        assert "new.csv" in filenames

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_gpu_flag(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        from models import Task

        task = Task(
            title="GPU Toggle",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()

        url = f"/api/tasks/{task.id}"
        headers = auth_headers(tokens.admin)
        data = {"gpu_required": "true"}
        resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 200
        assert resp.get_json()["gpu_required"] is True

    def test_update_competitor_forbidden(
        self, client, db_session, sample_challenge, tokens, auth_headers
    ):
        from models import Task

        task = Task(
            title="Locked",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()

        url = f"/api/tasks/{task.id}"
        headers = auth_headers(tokens.competitor)
        resp = client.put(
            url,
            data={"title": "Hacked"},
            headers=headers,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 403

    def test_update_task_not_found(self, client, db_session, tokens, auth_headers):
        url = "/api/tasks/99999"
        headers = auth_headers(tokens.admin)
        resp = client.put(
            url,
            data={"title": "Ghost"},
            headers=headers,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 404

    def test_update_unauthenticated_returns_403(self, client, db_session, sample_challenge):
        from models import Task

        task = Task(
            title="No Auth",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()

        url = f"/api/tasks/{task.id}"
        resp = client.put(url, data={"title": "X"}, content_type="multipart/form-data")
        assert resp.status_code == 403

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_baseline_notebook_replacement(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        import os
        import tempfile

        from models import Task

        task = Task(
            title="Replace NB",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()

        upload_dir = os.path.join(tempfile.gettempdir(), f"task_{task.id}")
        os.makedirs(upload_dir, exist_ok=True)

        with patch.dict(
            client.application.config,
            {"UPLOAD_FOLDER": tempfile.gettempdir()},
            clear=False,
        ):
            url = f"/api/tasks/{task.id}"
            headers = auth_headers(tokens.admin)
            nb = _make_notebook("print('updated')")
            data = {
                "title": "Replace NB",
                "baseline_notebook": (nb, "baseline.ipynb"),
            }
            resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 200
        assert resp.get_json()["baseline_notebook_path"] is not None

    # ── Evaluator update tests ──

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_replace_evaluator_script(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        import os
        import tempfile

        from models import Task

        task = Task(
            title="Eval Update",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
        )
        db_session.add(task)
        db_session.flush()

        upload_dir = os.path.join(tempfile.gettempdir(), f"task_{task.id}")
        os.makedirs(upload_dir, exist_ok=True)
        # Write an existing evaluator script on disk
        with open(os.path.join(upload_dir, "evaluator.py"), "w") as f:
            f.write(
                'METRIC_NAME = "old"\n'
                'SUBMISSION_COLUMNS = [{"name": "id", "type": "string"}]\n'
                'LABELS_COLUMNS = [{"name": "id", "type": "string"}]\n'
                "def evaluate(): pass\n"
            )
        task.evaluator_script_path = os.path.join(upload_dir, "evaluator.py")
        task.evaluator_metric_name = "old"

        with patch.dict(
            client.application.config,
            {"UPLOAD_FOLDER": tempfile.gettempdir()},
            clear=False,
        ):
            url = f"/api/tasks/{task.id}"
            headers = auth_headers(tokens.admin)
            new_script = io.BytesIO(
                b'METRIC_NAME = "new_metric"\n'
                b'SUBMISSION_COLUMNS = [{"name": "id", "type": "string"}]\n'
                b'LABELS_COLUMNS = [{"name": "id", "type": "string"}]\n'
                b"def evaluate(): pass\n"
            )
            data = {
                "title": "Eval Update",
                "evaluator_script": (new_script, "eval.py"),
            }
            resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["evaluator_metric_name"] == "new_metric"

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_delete_evaluator(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        import os
        import tempfile

        from models import Task

        task = Task(
            title="Delete Eval",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
        )
        db_session.add(task)
        db_session.flush()

        upload_dir = os.path.join(tempfile.gettempdir(), f"task_{task.id}")
        os.makedirs(upload_dir, exist_ok=True)
        eval_path = os.path.join(upload_dir, "evaluator.py")
        with open(eval_path, "w") as f:
            f.write(
                'METRIC_NAME = "del"\n'
                'SUBMISSION_COLUMNS = [{"name": "id", "type": "string"}]\n'
                'LABELS_COLUMNS = [{"name": "id", "type": "string"}]\n'
                "def evaluate(): pass\n"
            )
        task.evaluator_script_path = eval_path
        task.evaluator_metric_name = "del"

        with patch.dict(
            client.application.config,
            {"UPLOAD_FOLDER": tempfile.gettempdir()},
            clear=False,
        ):
            url = f"/api/tasks/{task.id}"
            headers = auth_headers(tokens.admin)
            data = {
                "title": "Delete Eval",
                "delete_evaluator": "true",
            }
            resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["evaluator_script_path"] is None
        assert body["evaluator_metric_name"] is None
        assert not os.path.exists(eval_path)

    @patch("routes.tasks._maybe_queue_baseline")
    @patch("cache_utils.invalidate_challenge_cache")
    @patch("services.audit_service.log_action")
    def test_update_invalid_evaluator_script_returns_error(
        self,
        mock_log,
        mock_cache,
        mock_queue,
        client,
        db_session,
        sample_challenge,
        tokens,
        auth_headers,
    ):
        from models import Task

        task = Task(
            title="Bad Eval Update",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
        )
        db_session.add(task)
        db_session.flush()

        url = f"/api/tasks/{task.id}"
        headers = auth_headers(tokens.admin)
        bad_script = io.BytesIO(b"this is not valid python !!!")
        data = {
            "title": "Bad Eval Update",
            "evaluator_script": (bad_script, "eval.py"),
        }
        resp = client.put(url, data=data, headers=headers, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "ERR_EVALUATOR_SCRIPT_INVALID"
        # Task should still exist and not be deleted
        from models import Task as TaskModel

        assert db_session.get(TaskModel, task.id) is not None


# ═══════════════════════════════════════════════════════════════════════════
#  DELETE — /api/tasks/<id>  (bonus coverage)
# ═══════════════════════════════════════════════════════════════════════════


class TestDeleteTaskCRUD:
    """DELETE /api/tasks/<task_id>"""

    def test_delete_while_unauthenticated(self, client, db_session, sample_challenge):
        from models import Task

        task = Task(
            title="Delete Me",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()
        resp = client.delete(f"/api/tasks/{task.id}")
        assert resp.status_code == 403

    def test_delete_task_success(self, client, db_session, sample_challenge, tokens, auth_headers):
        import os
        import shutil
        import tempfile

        from models import Submission, Task, User

        # Create task
        task = Task(
            title="Delete Me Success",
            challenge_id=sample_challenge.id,
            base_docker_image="python:3.10-slim",
            time_limit_sec=300,
            ram_limit_mb=512,
            max_submissions_per_period=10,
        )
        db_session.add(task)
        db_session.flush()

        competitor = db_session.query(User).filter_by(role="competitor").first()
        # Create submission for the task
        sub = Submission(
            user_id=competitor.id,
            challenge_id=sample_challenge.id,
            task_id=task.id,
            status="completed",
        )
        db_session.add(sub)
        db_session.flush()

        # Mock UPLOAD_FOLDER
        temp_upload_dir = tempfile.mkdtemp()
        task_dir = os.path.join(temp_upload_dir, f"task_{task.id}")
        os.makedirs(task_dir, exist_ok=True)
        # Create a mock file inside task_dir
        with open(os.path.join(task_dir, "mock_file.txt"), "w") as f:
            f.write("hello")

        task_id = task.id
        sub_id = sub.id

        with patch.dict(client.application.config, {"UPLOAD_FOLDER": temp_upload_dir}):
            url = f"/api/tasks/{task_id}"
            headers = auth_headers(tokens.admin)
            resp = client.delete(url, headers=headers)
            assert resp.status_code == 200

        # Assert task is deleted
        assert db_session.get(Task, task_id) is None
        # Assert submissions are deleted
        assert db_session.get(Submission, sub_id) is None
        # Assert upload directory is deleted
        assert not os.path.exists(task_dir)

        shutil.rmtree(temp_upload_dir, ignore_errors=True)


class TestReportBuildError:
    """Test the POST /worker/tasks/<id>/report-build-error endpoint."""

    def test_report_error(self, client, db_session, sample_challenge, tokens, auth_headers):
        from models.task import Task

        task = Task(challenge_id=sample_challenge.id, title="Test Build Task")
        db_session.add(task)
        db_session.commit()
        task_id = task.id

        # No token → 401
        resp = client.post(
            f"/api/worker/tasks/{task_id}/report-build-error",
            json={"error": "Docker pull failed"},
        )
        assert resp.status_code == 401

        # Invalid token → 401
        resp = client.post(
            f"/api/worker/tasks/{task_id}/report-build-error",
            json={"error": "Docker pull failed"},
            headers={"X-Worker-Token": "bad-token"},
        )
        assert resp.status_code == 401

        # Valid token → set build_error
        with patch("routes.tasks.check_worker_auth", return_value=True):
            resp = client.post(
                f"/api/worker/tasks/{task_id}/report-build-error",
                json={"error": "Docker pull failed: 404 Not Found"},
                headers={"X-Worker-Token": "valid-token"},
            )
            assert resp.status_code == 200
            db_session.refresh(task)
            assert task.build_error == "Docker pull failed: 404 Not Found"

            # Clear error with empty string
            resp = client.post(
                f"/api/worker/tasks/{task_id}/report-build-error",
                json={"error": ""},
                headers={"X-Worker-Token": "valid-token"},
            )
            assert resp.status_code == 200
            db_session.refresh(task)
            assert task.build_error is None

    def test_report_error_not_found(self, client, tokens):
        with patch("routes.tasks.check_worker_auth", return_value=True):
            resp = client.post(
                "/api/worker/tasks/00000000-0000-0000-0000-000000000000/report-build-error",
                json={"error": "fail"},
                headers={"X-Worker-Token": "valid-token"},
            )
            assert resp.status_code == 404
