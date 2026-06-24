"""pytest tests for challenge lifecycle endpoints: finalize, archive, test-competition.

Uses fixture-based patterns from conftest.py.
"""

import json
import pytest

from models import Challenge

# ═══════════════════════════════════════════════════════════════════════════
# Finalize endpoint:  POST /challenges/<id>/finalize
# Requires role: jury
# ═══════════════════════════════════════════════════════════════════════════


class TestFinalizeChallenge:
    """Tests for POST /challenges/<id>/finalize."""

    @pytest.fixture(autouse=True)
    def make_challenge_ended(self, db_session, sample_challenge):
        from datetime import datetime, timedelta

        sample_challenge.end_time = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()

    def test_finalize_as_jury_success(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = {str(sample_task.id): 90}
        db_session.commit()

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["challenge"]["scores_finalized"] is True

        db_session.refresh(sample_challenge)
        assert sample_challenge.scores_finalized is True

    def test_finalize_admin_forbidden(self, client, db_session, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 403

    def test_finalize_competitor_forbidden(self, client, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.competitor}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 403

    def test_finalize_challenge_not_found(self, client, create_user):
        jury = create_user(username="finalize-jury-nf", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        res = client.post(
            "/api/challenges/99999/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 404

    def test_finalize_missing_manual_points(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury-mp", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = None
        db_session.commit()

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "missing manual points" in res.get_json()["error"].lower()

    def test_finalize_repeat_finalize(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury-rf", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = {str(sample_task.id): 85}
        db_session.commit()

        res1 = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res1.status_code == 200

        res2 = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res2.status_code == 400
        assert "already finalized" in res2.get_json()["error"].lower()

    def test_finalize_reveal_options(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        jury = create_user(username="finalize-jury-ro", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        sample_competitor.manual_points = {str(sample_task.id): 75}
        db_session.commit()

        # Finalize first (no reveal options)
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.scores_finalized is True

        # Toggle reveal — turn off
        res2 = client.put(
            f"/api/challenges/{sample_challenge.id}/reveal-results",
            data=json.dumps({"reveal_results": False}),
            content_type="application/json",
            headers=headers,
        )
        assert res2.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.reveal_results is False

        # Toggle reveal — turn back on
        res3 = client.put(
            f"/api/challenges/{sample_challenge.id}/reveal-results",
            data=json.dumps({"reveal_results": True}),
            content_type="application/json",
            headers=headers,
        )
        assert res3.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.reveal_results is True

        # Toggle reveal as admin — turn off
        admin = create_user(username="finalize-admin-ro", role="admin")
        admin_token = generate_token(admin.id, "admin")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        res_admin = client.put(
            f"/api/challenges/{sample_challenge.id}/reveal-results",
            data=json.dumps({"reveal_results": False}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert res_admin.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.reveal_results is False

    def test_finalize_before_ended_returns_400(
        self, client, db_session, sample_challenge, sample_competitor, sample_task, create_user
    ):
        from datetime import datetime, timedelta

        # Override end_time to be in the future
        sample_challenge.end_time = datetime.utcnow() + timedelta(hours=2)
        sample_competitor.manual_points = {str(sample_task.id): 90}
        db_session.commit()

        jury = create_user(username="finalize-jury-be", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "before its end time" in res.get_json()["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Test-Stage endpoint:  POST /challenges/<id>/test-stage
# Requires role: admin or jury
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateTestStage:
    """Tests for POST /challenges/<id>/test-stage."""

    def _make_payload(self, start_offset_hours=1, end_offset_hours=2):
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        return {
            "title": "Test Stage",
            "start_time": (now + timedelta(hours=start_offset_hours)).isoformat() + "Z",
            "end_time": (now + timedelta(hours=end_offset_hours)).isoformat() + "Z",
        }

    def test_admin_creates_test_stage(self, client, db_session, sample_future_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        payload = self._make_payload()
        res = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["is_test"] is True
        assert data["stage_number"] == 0

        from models import Stage, Task
        import os
        import json as json_mod

        stage = db_session.get(Stage, data["id"])
        assert stage is not None
        assert stage.is_test is True

        tasks = Task.query.filter_by(stage_id=stage.id).all()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.title == "Warm-up Test Task"
        assert task.custom_eval_code is None
        assert task.gpu_required is True
        assert task.base_docker_image == "pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime"
        assert (
            task.pip_requirements
            == "pandas==2.2.2\npyarrow==17.0.0\ndatasets==3.0.0\ntorchvision==0.21.0"
        )
        assert task.ram_limit_mb == 8192
        assert task.time_limit_sec == 600
        assert task.ban_magic_commands is True
        assert (
            task.whitelisted_imports
            == "pandas,datasets,pyarrow,torch,torchvision,numpy,json,sys,os"
        )
        assert task.hf_datasets == ["ylecun/mnist"]
        assert task.metrics_config == {
            "accuracy": {"weight": 0.25},
            "f1": {"weight": 0.25, "options": {"average": "macro"}},
            "precision": {"weight": 0.25, "options": {"average": "macro"}},
            "recall": {"weight": 0.25, "options": {"average": "macro"}},
        }

        # Check files copying
        assert task.baseline_notebook_path is not None
        assert os.path.exists(task.baseline_notebook_path)
        assert task.files is not None
        files_list = json_mod.loads(task.files)
        assert len(files_list) == 1
        assert files_list[0]["filename"] == "labels.parquet"

        # Check physical labels.parquet
        task_upload_dir = os.path.dirname(task.baseline_notebook_path)
        labels_path = os.path.join(task_upload_dir, "labels.parquet")
        assert os.path.exists(labels_path)
        import pandas as pd

        df_labels = pd.read_parquet(labels_path)
        assert len(df_labels) == 2400

    def test_jury_creates_test_stage(
        self, client, db_session, sample_future_challenge, create_user
    ):
        jury = create_user(username="teststage-jury", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}
        payload = self._make_payload()
        res = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 201

    def test_competitor_forbidden(self, client, sample_future_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.competitor}"}
        payload = self._make_payload()
        res = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 403

    def test_challenge_not_found(self, client, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        payload = self._make_payload()
        res = client.post(
            "/api/challenges/99999/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 404

    def test_unauthorized_no_token(self, client, sample_future_challenge):
        payload = self._make_payload()
        res = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert res.status_code == 401

    def test_duplicate_test_stage_rejected(
        self, client, db_session, sample_future_challenge, tokens
    ):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        payload = self._make_payload()
        res1 = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res1.status_code == 201

        res2 = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res2.status_code == 400
        assert "already exists" in res2.get_json()["error"].lower()

    def test_competition_already_started_rejected(self, client, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        payload = self._make_payload()
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "after the competition has started" in res.get_json()["error"].lower()

    def test_test_stage_must_end_before_competition_start(
        self, client, db_session, sample_future_challenge, tokens
    ):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        from datetime import timedelta

        end_after_comp_start = (
            sample_future_challenge.start_time + timedelta(hours=1)
        ).isoformat() + "Z"
        payload = {
            "title": "Test Stage",
            "start_time": (sample_future_challenge.start_time - timedelta(hours=2)).isoformat()
            + "Z",
            "end_time": end_after_comp_start,
        }
        res = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "must end before" in res.get_json()["error"].lower()

    def test_test_stage_time_range_validation(
        self, client, db_session, sample_future_challenge, tokens
    ):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        from datetime import timedelta

        comp_start = sample_future_challenge.start_time
        bad_payload = {
            "title": "Test Stage",
            "start_time": (comp_start - timedelta(hours=3)).isoformat() + "Z",
            "end_time": (comp_start - timedelta(hours=4)).isoformat() + "Z",
        }
        res = client.post(
            f"/api/challenges/{sample_future_challenge.id}/test-stage",
            data=json.dumps(bad_payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 400
        assert "end time must be after start time" in res.get_json()["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Archive endpoint:  POST /challenges/<id>/archive
# (Basic toggle tested in TestArchiveChallenge — pytest-style coverage here)
# ═══════════════════════════════════════════════════════════════════════════


class TestArchiveChallengePytest:
    """Additional archive edge-cases not covered by TestArchiveChallenge."""

    def test_archive_jury_can_toggle(self, client, db_session, sample_challenge, create_user):
        jury = create_user(username="archive-jury", role="jury")
        from auth_utils import generate_token

        token = generate_token(jury.id, "jury")
        headers = {"Authorization": f"Bearer {token}"}

        assert sample_challenge.is_archived is False
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        assert res.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is True

        res = client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        assert res.status_code == 200
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is False

    def test_archive_sets_computed_status(self, client, db_session, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        assert res.status_code == 200
        assert res.get_json()["challenge"]["status"] == "archived"

    def test_archive_challenge_persisted(self, client, db_session, sample_challenge, tokens):
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is True

        client.post(
            f"/api/challenges/{sample_challenge.id}/archive",
            headers=headers,
        )
        db_session.refresh(sample_challenge)
        assert sample_challenge.is_archived is False


# ═══════════════════════════════════════════════════════════════════════════
# Test-Stage creation via competition create/update
# ═══════════════════════════════════════════════════════════════════════════


class TestTestStageViaCompetitionCreate:
    """Test stage created via POST /challenges with test_stage_* fields."""

    def test_create_challenge_with_test_stage(self, client, db_session, tokens):
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        start = now + timedelta(days=1)
        test_start = now + timedelta(hours=1)
        test_end = now + timedelta(hours=2)
        payload = {
            "title": "Comp With Test Stage",
            "start_time": start.isoformat() + "Z",
            "end_time": (start + timedelta(days=7)).isoformat() + "Z",
            "test_stage_start_time": test_start.isoformat() + "Z",
            "test_stage_end_time": test_end.isoformat() + "Z",
            "timezone": "UTC",
        }
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.post(
            "/api/challenges",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["title"] == "Comp With Test Stage"

        from models import Stage, Task

        stages = Stage.query.filter_by(challenge_id=data["id"]).all()
        test_stages = [s for s in stages if s.is_test]
        assert len(test_stages) == 1
        assert test_stages[0].stage_number == 0

        tasks = Task.query.filter_by(stage_id=test_stages[0].id).all()
        assert len(tasks) == 1
        assert tasks[0].title == "Warm-up Test Task"

    def test_update_challenge_adds_test_stage(
        self, client, db_session, sample_future_challenge, tokens
    ):
        from datetime import timedelta

        test_start = sample_future_challenge.start_time - timedelta(hours=4)
        test_end = sample_future_challenge.start_time - timedelta(hours=2)
        payload = {
            "test_stage_start_time": test_start.isoformat() + "Z",
            "test_stage_end_time": test_end.isoformat() + "Z",
        }
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.put(
            f"/api/challenges/{sample_future_challenge.id}",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 200

        from models import Stage

        stages = Stage.query.filter_by(challenge_id=sample_future_challenge.id, is_test=True).all()
        assert len(stages) == 1

    def test_update_challenge_removes_test_stage(
        self, client, db_session, sample_future_challenge, tokens
    ):
        from datetime import timedelta
        from models import Stage

        test_stage = Stage(
            challenge_id=sample_future_challenge.id,
            stage_number=0,
            title="Test Stage",
            start_time=sample_future_challenge.start_time - timedelta(hours=4),
            end_time=sample_future_challenge.start_time - timedelta(hours=2),
            is_test=True,
        )
        db_session.add(test_stage)
        db_session.commit()

        payload = {"test_stage_start_time": "", "test_stage_end_time": ""}
        headers = {"Authorization": f"Bearer {tokens.admin}"}
        res = client.put(
            f"/api/challenges/{sample_future_challenge.id}",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )
        assert res.status_code == 200

        remaining = Stage.query.filter_by(
            challenge_id=sample_future_challenge.id, is_test=True
        ).all()
        assert len(remaining) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Test-Stage scoring exclusion: test stage subs excluded from leaderboard
# ═══════════════════════════════════════════════════════════════════════════


class TestTestStageScoring:
    """Test stage submissions are excluded from leaderboard."""

    def test_test_stage_submission_excluded_from_leaderboard(
        self, client, db_session, sample_future_challenge, sample_competitor, tokens
    ):
        from datetime import datetime, timedelta
        from models import Stage, Task, Submission

        now = datetime.utcnow()
        comp_start = sample_future_challenge.start_time

        test_stage = Stage(
            challenge_id=sample_future_challenge.id,
            stage_number=0,
            title="Test Stage",
            start_time=now,
            end_time=comp_start - timedelta(hours=1),
            is_test=True,
        )
        db_session.add(test_stage)
        db_session.commit()

        test_task = Task(
            challenge_id=sample_future_challenge.id,
            stage_id=test_stage.id,
            title="Warm-up Test Task",
            files="[]",
        )
        db_session.add(test_task)
        db_session.commit()

        sub = Submission(
            user_id=sample_competitor.id,
            challenge_id=sample_future_challenge.id,
            task_id=test_task.id,
            status="completed",
            public_score=0.95,
            private_score=0.95,
        )
        db_session.add(sub)
        db_session.commit()

        from services.leaderboard_service import build_and_cache_leaderboard

        lb = build_and_cache_leaderboard(sample_future_challenge.id)
        if lb:
            found = any(str(entry["user"]["id"]) == str(sample_competitor.id) for entry in lb)
            assert not found, "Test stage submission should not appear in leaderboard"

    def test_regular_stage_submission_still_counts(
        self, client, db_session, sample_challenge, sample_task, sample_competitor, tokens
    ):
        from models import Submission, Stage

        regular_stage = Stage(
            challenge_id=sample_challenge.id,
            stage_number=1,
            title="Regular Stage",
            start_time=sample_challenge.start_time,
            end_time=sample_challenge.end_time,
            is_test=False,
        )
        db_session.add(regular_stage)
        db_session.commit()

        sample_task.stage_id = regular_stage.id
        db_session.commit()

        sub = Submission(
            user_id=sample_competitor.id,
            challenge_id=sample_challenge.id,
            task_id=sample_task.id,
            status="completed",
            public_score=0.85,
            private_score=0.85,
        )
        db_session.add(sub)
        db_session.commit()

        from services.leaderboard_service import build_and_cache_leaderboard

        lb = build_and_cache_leaderboard(sample_challenge.id)
        assert lb is not None
        found = any(str(entry["user"]["id"]) == str(sample_competitor.id) for entry in lb)
        assert found, "Regular stage submission should appear in leaderboard"


# ═══════════════════════════════════════════════════════════════════════════
# Task stage assignment validation
# ═══════════════════════════════════════════════════════════════════════════


class TestTaskStageAssignment:
    """Tasks must be assigned to a stage when regular stages exist."""

    def test_task_requires_stage_id_when_stages_exist(
        self, client, db_session, sample_challenge, tokens
    ):
        from models import Stage

        stage = Stage(
            challenge_id=sample_challenge.id,
            stage_number=1,
            title="Regular Stage",
            start_time=sample_challenge.start_time,
            end_time=sample_challenge.end_time,
            is_test=False,
        )
        db_session.add(stage)
        db_session.commit()

        headers = {"Authorization": f"Bearer {tokens.admin}", "Content-Type": "multipart/form-data"}
        import io
        import json as json_mod

        data = {
            "title": "New Task No Stage",
            "stage_id": "",
        }
        data["baseline_notebook"] = (
            io.BytesIO(
                json_mod.dumps(
                    {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}
                ).encode()
            ),
            "baseline.ipynb",
        )
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/tasks",
            headers=headers,
            data=data,
        )
        assert res.status_code == 400
        err = res.get_json()["error"].lower()
        assert "must be assigned to a stage" in err

    def test_task_without_stage_id_allowed_when_no_stages(
        self, client, db_session, sample_challenge, tokens
    ):
        headers = {"Authorization": f"Bearer {tokens.admin}", "Content-Type": "multipart/form-data"}
        import io
        import json as json_mod

        data = {
            "title": "Stage-less Task",
            "stage_id": "",
        }
        data["baseline_notebook"] = (
            io.BytesIO(
                json_mod.dumps(
                    {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}
                ).encode()
            ),
            "baseline.ipynb",
        )
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/tasks",
            headers=headers,
            data=data,
        )
        # The request may fail for other reasons (missing evaluator etc.) but not for stage
        if res.status_code == 400:
            err = res.get_json()["error"].lower()
            assert "must be assigned to a stage" not in err

    def test_task_without_stage_id_allowed_when_only_test_stage(
        self, client, db_session, sample_future_challenge, tokens
    ):
        from datetime import datetime, timedelta
        from models import Stage

        now = datetime.utcnow()
        test_stage = Stage(
            challenge_id=sample_future_challenge.id,
            stage_number=0,
            title="Test Stage",
            start_time=now,
            end_time=sample_future_challenge.start_time - timedelta(hours=1),
            is_test=True,
        )
        db_session.add(test_stage)
        db_session.commit()

        headers = {"Authorization": f"Bearer {tokens.admin}", "Content-Type": "multipart/form-data"}
        import io
        import json as json_mod

        data = {
            "title": "Stage-less Task",
            "stage_id": "",
        }
        data["baseline_notebook"] = (
            io.BytesIO(
                json_mod.dumps(
                    {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 2}
                ).encode()
            ),
            "baseline.ipynb",
        )
        res = client.post(
            f"/api/challenges/{sample_future_challenge.id}/tasks",
            headers=headers,
            data=data,
        )
        if res.status_code == 400:
            err = res.get_json()["error"].lower()
            assert "must be assigned to a stage" not in err
