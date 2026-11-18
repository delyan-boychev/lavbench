"""Regression tests for the 2026-11-18 security review: jury scoping, admin rules, task release."""

import importlib.util
import os
import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

import routes.auth as auth_routes
from models import Challenge, Stage, Submission, Task, User, db
from utils.auth_utils import generate_token, jury_access_required
from utils.dates import utcnow

ADMIN_PASSWORD = "admin-pass-123"


def _challenge(db_session, title, start_hours, end_hours=10, double_blind=True):
    challenge = Challenge(
        title=title,
        start_time=utcnow() + timedelta(hours=start_hours),
        end_time=utcnow() + timedelta(hours=end_hours),
        double_blind=double_blind,
        timezone="UTC",
    )
    db_session.add(challenge)
    db_session.flush()
    return challenge


def _competitor(create_user, username, challenge, name="Ivan", surname="Petrov"):
    user = create_user(
        username=username,
        role="competitor",
        alias_id=f"Alias-{uuid.uuid4().hex[:8]}",
        challenge_id=challenge.id if challenge else None,
    )
    user.set_demographics(name, surname, "10", "School", "City")
    return user


@pytest.fixture
def world(db_session, create_user, redis_flush):
    """Competition A (jury assigned, not started) and B (jury not assigned, running)."""
    a = _challenge(db_session, "A", start_hours=5)
    b = _challenge(db_session, "B", start_hours=-1)
    admin = create_user(username="the_admin", password=ADMIN_PASSWORD, role="admin")
    jury = create_user(username="jury_a", role="jury", jury_challenges=[a])
    other_jury = create_user(username="jury_b", role="jury", jury_challenges=[b])
    comp_a = _competitor(create_user, "comp_a", a)
    comp_b = _competitor(create_user, "comp_b", b)
    orphan = _competitor(create_user, "orphan", None)
    stage_b = Stage(
        challenge_id=b.id,
        stage_number=1,
        title="S",
        start_time=utcnow() - timedelta(minutes=30),
        end_time=utcnow() + timedelta(hours=5),
    )
    db_session.add(stage_b)
    db_session.flush()
    task_b = Task(challenge_id=b.id, stage_id=stage_b.id, title="T", files="[]")
    db_session.add(task_b)
    db_session.flush()
    sub_b = Submission(user_id=comp_b.id, challenge_id=b.id, task_id=task_b.id, status="completed")
    db_session.add(sub_b)
    db_session.commit()

    class World:
        pass

    w = World()
    w.a, w.b, w.admin, w.jury, w.other_jury = a, b, admin, jury, other_jury
    w.comp_a, w.comp_b, w.orphan = comp_a, comp_b, orphan
    w.stage_b, w.task_b, w.sub_b = stage_b, task_b, sub_b
    w.jury_token = generate_token(jury.id, "jury")
    w.admin_token = generate_token(admin.id, "admin")
    return w


def _hash_of(user_id):
    db.session.expire_all()
    return db.session.get(User, user_id).password_hash


# ── C1: password resets ──


@pytest.mark.parametrize(
    "target",
    ["admin", "other_jury", "orphan", "comp_b"],
)
def test_jury_cannot_reset_outside_its_competitors(client, world, csrf_headers, target):
    victim = getattr(world, target)
    before = _hash_of(victim.id)
    for query in ("", f"?challenge_id={world.a.id}"):
        res = client.post(
            f"/api/admin/users/{victim.id}/reset-password{query}",
            headers=csrf_headers(world.jury_token),
        )
        assert res.status_code == 403
        assert "password" not in (res.get_json() or {})
    assert _hash_of(victim.id) == before


def test_jury_reset_of_admin_never_yields_an_admin_session(client, world, csrf_headers):
    client.post(
        f"/api/admin/users/{world.admin.id}/reset-password?challenge_id={world.a.id}",
        headers=csrf_headers(world.jury_token),
    )
    login = client.post(
        "/api/auth/login", json={"username": "the_admin", "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200
    assert login.get_json()["user"]["role"] == "admin"


def test_jury_resets_its_own_competitor_before_the_start(client, world, csrf_headers):
    res = client.post(
        f"/api/admin/users/{world.comp_a.id}/reset-password",
        headers=csrf_headers(world.jury_token),
    )
    assert res.status_code == 200
    assert check_password_hash(_hash_of(world.comp_a.id), res.get_json()["password"])


def test_jury_cannot_reset_after_the_start(client, world, csrf_headers, db_session):
    world.a.start_time = utcnow() - timedelta(minutes=1)
    db_session.commit()
    res = client.post(
        f"/api/admin/users/{world.comp_a.id}/reset-password",
        headers=csrf_headers(world.jury_token),
    )
    assert res.status_code == 403
    assert res.get_json()["code"] == "ERR_CANNOT_RESET_STARTED"


def test_admin_resets_any_other_account_but_not_its_own(client, world, csrf_headers):
    for target in (world.jury, world.comp_b, world.orphan):
        res = client.post(
            f"/api/admin/users/{target.id}/reset-password", headers=csrf_headers(world.admin_token)
        )
        assert res.status_code == 200
    before = _hash_of(world.admin.id)
    res = client.post(
        f"/api/admin/users/{world.admin.id}/reset-password", headers=csrf_headers(world.admin_token)
    )
    assert res.status_code == 403
    assert res.get_json()["code"] == "ERR_CANNOT_RESET_OWN_PASSWORD"
    assert _hash_of(world.admin.id) == before


def test_competitors_cannot_reset_passwords(client, world, csrf_headers):
    token = generate_token(world.comp_a.id, "competitor")
    res = client.post(
        f"/api/admin/users/{world.comp_a.id}/reset-password", headers=csrf_headers(token)
    )
    assert res.status_code == 403


def test_bulk_reset_stays_admin_only(client, world, csrf_headers):
    res = client.post(
        f"/api/admin/challenges/{world.a.id}/reset-all-passwords",
        headers=csrf_headers(world.jury_token),
    )
    assert res.status_code == 403
    assert res.get_json()["code"] == "ERR_ROLE_REQUIRED"


def test_user_list_says_which_resets_the_viewer_may_run(client, world, csrf_headers, db_session):
    def flags(token):
        res = client.get("/api/admin/users?per_page=100", headers=csrf_headers(token))
        return {row["id"]: row["can_reset_password"] for row in res.get_json()["items"]}

    admin_view = flags(world.admin_token)
    assert admin_view[str(world.admin.id)] is False
    assert admin_view[str(world.jury.id)] is True
    assert admin_view[str(world.comp_b.id)] is True
    assert flags(world.jury_token) == {str(world.comp_a.id): True}
    world.a.start_time = utcnow() - timedelta(minutes=1)
    db_session.commit()
    assert flags(world.jury_token) == {str(world.comp_a.id): False}


def test_jury_cannot_adopt_a_competitor_without_competition(client, world, csrf_headers):
    res = client.put(
        f"/api/admin/users/{world.orphan.id}",
        json={"challenge_id": str(world.a.id), "email": "taken@over.example"},
        headers=csrf_headers(world.jury_token),
    )
    assert res.status_code == 403
    db.session.expire_all()
    assert db.session.get(User, world.orphan.id).challenge_id is None


def test_jury_register_reads_the_competition_from_the_body_only(
    client, world, csrf_headers, db_session
):
    # Not started, so only the assignment can refuse it
    world.b.start_time = utcnow() + timedelta(hours=1)
    db_session.commit()
    body = {
        "username": "smuggled",
        "role": "competitor",
        "challenge_id": str(world.b.id),
        "name": "N",
        "surname": "S",
        "middle_name": "M",
        "birth_date": "2008-01-01",
        "grade": "10",
        "school": "Sch",
        "city": "City",
    }
    res = client.post(
        f"/api/admin/register-user?challenge_id={world.a.id}",
        json=body,
        headers=csrf_headers(world.jury_token),
    )
    assert res.status_code == 403
    assert User.query.filter_by(username="smuggled").first() is None


def test_object_from_another_competition_is_refused(client, world, csrf_headers):
    res = client.get(
        f"/api/challenges/{world.a.id}/users/{world.comp_b.id}/best-submissions",
        headers=csrf_headers(world.jury_token),
    )
    assert res.status_code == 403


def _jury_routes(app):
    """Every route guarded by jury_access_required, found through the decorator chain."""
    marker = jury_access_required(lambda: None).__code__
    found = []
    for rule in app.url_map.iter_rules():
        view = app.view_functions[rule.endpoint]
        while view is not None:
            if getattr(view, "__code__", None) is marker:
                found.append(rule)
                break
            view = getattr(view, "__wrapped__", None)
    return found


def test_unassigned_jury_is_refused_on_every_jury_scoped_route(
    app, client, world, csrf_headers, monkeypatch
):
    import routes.environment

    # The workspace routes answer 404 before any check while nanoColab is off
    monkeypatch.setattr(routes.environment.envs, "nanocolab_enabled", lambda: True)
    values = {
        "challenge_id": world.b.id,
        "task_id": world.task_b.id,
        "stage_id": world.stage_b.id,
        "submission_id": world.sub_b.id,
        "user_id": world.comp_b.id,
        "filename": "data.csv",
        "kind": "notebook",
        "environment_id": uuid.uuid4(),
    }
    rules = _jury_routes(app)
    assert len(rules) >= 40
    checked = 0
    for rule in rules:
        url = re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(values[m.group(1)]), rule.rule)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            # Smuggle the assigned competition where an object decides; else name the other one
            body = {"challenge_id": str(world.a.id if rule.arguments else world.b.id)}
            res = client.open(
                f"{url}?challenge_id={world.a.id}",
                method=method,
                json=body,
                headers=csrf_headers(world.jury_token),
            )
            assert res.status_code == 403, f"{method} {rule.rule} -> {res.status_code}"
            checked += 1
    assert checked == sum(len(r.methods - {"HEAD", "OPTIONS"}) for r in rules)


def test_assigned_jury_still_reads_its_competition(client, world, csrf_headers):
    token = generate_token(world.other_jury.id, "jury")
    assert (
        client.get(f"/api/challenges/{world.b.id}", headers=csrf_headers(token)).status_code == 200
    )
    assert (
        client.get(f"/api/submissions/{world.sub_b.id}", headers=csrf_headers(token)).status_code
        == 200
    )


# ── Exactly one admin ──


def test_the_database_refuses_a_second_admin(world, db_session):
    db_session.add(User(username="admin2", password_hash="x", role="admin", alias_id="adm-2"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_the_admin_role_is_never_removed_or_given(client, world, csrf_headers):
    res = client.put(
        f"/api/admin/users/{world.admin.id}",
        json={"role": "jury", "jury_challenges": [str(world.a.id)]},
        headers=csrf_headers(world.admin_token),
    )
    assert res.status_code == 403
    assert res.get_json()["code"] == "ERR_CANNOT_CHANGE_ROLE_ADMIN"
    res = client.put(
        f"/api/admin/users/{world.jury.id}",
        json={"role": "admin"},
        headers=csrf_headers(world.admin_token),
    )
    assert res.status_code == 403
    db.session.expire_all()
    assert db.session.get(User, world.admin.id).role == "admin"
    assert db.session.get(User, world.jury.id).role == "jury"


def test_the_admin_account_cannot_be_deleted(client, world, csrf_headers):
    res = client.delete(
        f"/api/admin/users/{world.admin.id}", headers=csrf_headers(world.admin_token)
    )
    assert res.status_code == 400
    assert db.session.get(User, world.admin.id) is not None


# ── H1: task statements before their release ──


def _competitor_task_views(client, token, challenge_id):
    headers = {"Authorization": f"Bearer {token}"}
    page = client.get(f"/api/challenges/{challenge_id}", headers=headers).get_json()
    subs = client.get(f"/api/challenges/{challenge_id}/submissions", headers=headers).get_json()
    board = client.get(f"/api/challenges/{challenge_id}/leaderboard", headers=headers).get_json()
    return (
        {t["description"] for t in page["tasks"]},
        {t["description"] for t in subs["challenge"]["tasks"]},
        {t["description"] for t in board["tasks"]},
    )


def test_no_task_statement_before_the_start(client, db_session, create_user, redis_flush):
    challenge = _challenge(db_session, "Later", start_hours=5)
    db_session.add(Task(challenge_id=challenge.id, title="T", description="SECRET", files="[]"))
    comp = _competitor(create_user, "early_bird", challenge)
    db_session.commit()
    views = _competitor_task_views(client, generate_token(comp.id, "competitor"), challenge.id)
    assert views == (set(), set(), set())


def test_no_task_statement_of_a_later_stage(client, db_session, create_user, redis_flush):
    challenge = _challenge(db_session, "Running", start_hours=-5)
    now = utcnow()
    s1 = Stage(
        challenge_id=challenge.id,
        stage_number=1,
        title="S1",
        start_time=now - timedelta(hours=4),
        end_time=now + timedelta(hours=1),
    )
    s2 = Stage(
        challenge_id=challenge.id,
        stage_number=2,
        title="S2",
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=5),
    )
    db_session.add_all([s1, s2])
    db_session.flush()
    db_session.add_all(
        [
            Task(challenge_id=challenge.id, stage_id=s1.id, title="T1", description="NOW"),
            Task(challenge_id=challenge.id, stage_id=s2.id, title="T2", description="LATER"),
        ]
    )
    comp = _competitor(create_user, "mid_comp", challenge)
    db_session.commit()
    views = _competitor_task_views(client, generate_token(comp.id, "competitor"), challenge.id)
    assert views == ({"NOW"}, {"NOW"}, {"NOW"})


# ── H2: login throttling and hashing off the hub ──


def test_successful_logins_are_never_limited(client, db_session, create_user, redis_flush):
    """A whole school logs in from one address at once: successes are not counted."""
    create_user(username="student1", password="Correct-horse-1")
    db_session.commit()
    for _ in range(30):
        res = client.post(
            "/api/auth/login",
            json={"username": "student1", "password": "Correct-horse-1"},
            headers={"X-Real-IP": "198.51.100.6"},
        )
        assert res.status_code == 200


def test_failed_logins_lock_the_address(client, db_session, create_user, redis_flush):
    from utils.cache_utils import get_coordination_client

    redis = get_coordination_client()
    if redis is None:
        pytest.skip("needs Redis")
    create_user(username="student2", password="Correct-horse-2")
    db_session.commit()
    ip = "198.51.100.7"
    for i in range(auth_routes.LOGIN_IP_MAX_FAILURES):
        auth_routes._record_login_failure(f"guess{i}", ip)
    res = client.post(
        "/api/auth/login",
        json={"username": "student2", "password": "Correct-horse-2"},
        headers={"X-Real-IP": ip},
    )
    assert res.status_code == 429
    assert res.headers["Retry-After"] == str(auth_routes.LOGIN_IP_FAILURE_WINDOW_SECONDS)
    ok = client.post(
        "/api/auth/login",
        json={"username": "student2", "password": "Correct-horse-2"},
        headers={"X-Real-IP": "198.51.100.8"},
    )
    assert ok.status_code == 200


def test_failed_logins_lock_the_username(client, db_session, create_user, redis_flush):
    create_user(username="student4", password="Correct-horse-4")
    db_session.commit()
    for _ in range(auth_routes.LOGIN_USER_MAX_FAILURES):
        bad = client.post("/api/auth/login", json={"username": "student4", "password": "wrong"})
        assert bad.status_code == 401
    res = client.post(
        "/api/auth/login", json={"username": "student4", "password": "Correct-horse-4"}
    )
    assert res.status_code == 429
    assert res.get_json()["code"] == "ERR_RATE_LIMIT_EXCEEDED"


def test_password_checks_run_off_the_gevent_hub(client, db_session, create_user, monkeypatch):
    calls = []
    original = auth_routes.run_blocking

    def recording(func, *args):
        calls.append(func)
        return original(func, *args)

    monkeypatch.setattr(auth_routes, "run_blocking", recording)
    create_user(username="student3", password="Correct-horse-3")
    db_session.commit()
    client.post("/api/auth/login", json={"username": "student3", "password": "Correct-horse-3"})
    client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert [f.__name__ for f in calls] == ["check_password_hash", "check_password_hash"]


# ── H3: finalising and revealing only through their own routes ──


def test_stage_update_cannot_finalise_or_reveal(client, db_session, create_user, csrf_headers):
    challenge = _challenge(db_session, "Staged", start_hours=-5)
    stage = Stage(
        challenge_id=challenge.id,
        stage_number=1,
        title="S1",
        start_time=utcnow() - timedelta(hours=4),
        end_time=utcnow() + timedelta(hours=1),
    )
    db_session.add(stage)
    db_session.flush()
    task = Task(challenge_id=challenge.id, stage_id=stage.id, title="T1", files="[]")
    db_session.add(task)
    db_session.flush()
    comp = _competitor(create_user, "comp_h3", challenge)
    jury = create_user(username="jury_h3", role="jury", jury_challenges=[challenge])
    sub = Submission(
        user_id=comp.id,
        challenge_id=challenge.id,
        task_id=task.id,
        status="completed",
        public_score=0.5,
        private_score=0.77,
    )
    db_session.add(sub)
    db_session.commit()
    for body in ({"is_finalized": True}, {"reveal_results": True}):
        res = client.put(
            f"/api/challenges/{challenge.id}/stages/{stage.id}",
            json=body,
            headers=csrf_headers(generate_token(jury.id, "jury")),
        )
        assert res.status_code == 422
    db.session.expire_all()
    stage = db.session.get(Stage, stage.id)
    assert (stage.is_finalized, stage.reveal_results) == (False, False)
    res = client.get(
        f"/api/submissions/{sub.id}",
        headers={"Authorization": f"Bearer {generate_token(comp.id, 'competitor')}"},
    )
    assert res.get_json()["private_score"] is None


# ── M3: finalise errors name aliases only ──


def _ended_with_missing_points(db_session, create_user, with_stage):
    challenge = _challenge(db_session, "Ended", start_hours=-5, end_hours=-1)
    stage = None
    if with_stage:
        stage = Stage(
            challenge_id=challenge.id,
            stage_number=1,
            title="S",
            start_time=utcnow() - timedelta(hours=4),
            end_time=utcnow() - timedelta(hours=2),
        )
        db_session.add(stage)
        db_session.flush()
    task = Task(
        challenge_id=challenge.id, stage_id=stage.id if stage else None, title="T", files="[]"
    )
    db_session.add(task)
    db_session.flush()
    comp = _competitor(create_user, "comp_ivan", challenge)
    jury = create_user(username="jury_m3", role="jury", jury_challenges=[challenge])
    db_session.add(
        Submission(user_id=comp.id, challenge_id=challenge.id, task_id=task.id, status="completed")
    )
    db_session.commit()
    return challenge, stage, comp, generate_token(jury.id, "jury")


@pytest.mark.parametrize("with_stage", [True, False])
def test_finalise_errors_name_the_alias_only(
    client, db_session, create_user, csrf_headers, with_stage
):
    challenge, stage, comp, token = _ended_with_missing_points(db_session, create_user, with_stage)
    url = (
        f"/api/challenges/{challenge.id}/stages/{stage.id}/finalize"
        if stage
        else f"/api/challenges/{challenge.id}/finalize"
    )
    res = client.post(url, json={"reveal_results": False}, headers=csrf_headers(token))
    assert res.status_code == 400
    message = res.get_json()["error"]
    assert comp.alias_id in message
    for secret in ("Ivan", "Petrov", comp.username, str(comp.id)):
        assert secret not in message


# ── M8: setup-admin keeps data and one admin ──


def _setup_admin_module():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "setup-admin.py")
    spec = importlib.util.spec_from_file_location("setup_admin_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_admin_replaces_the_existing_admin_in_place(db_session, sample_challenge):
    module = _setup_admin_module()
    first_name, first_key, replaced = module.provision_admin()
    assert replaced is False
    admin_id = User.query.filter_by(role="admin").one().id
    second_name, second_key, replaced = module.provision_admin()
    assert replaced is True
    admin = User.query.filter_by(role="admin").one()
    assert admin.id == admin_id
    assert admin.username == second_name != first_name
    assert check_password_hash(admin.password_hash, second_key)
    assert not check_password_hash(admin.password_hash, first_key)
    assert db.session.get(Challenge, sample_challenge.id) is not None


def test_setup_admin_never_resets_without_confirmation(monkeypatch):
    module = _setup_admin_module()
    touched = []
    monkeypatch.setattr(module, "create_engine", lambda *a, **k: touched.append("engine"))
    monkeypatch.setattr(module, "reset_database", lambda *a: touched.append("reset"))
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: False)
    assert module.main(["--reset-database"]) == 1
    assert touched == []


def test_setup_admin_reset_needs_the_typed_phrase(monkeypatch):
    module = _setup_admin_module()
    touched = []
    monkeypatch.setattr(module, "create_engine", lambda *a, **k: touched.append("engine"))
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert module.main(["--reset-database"]) == 1
    assert touched == []
