"""Tests for Hugging Face ZIPs: checks, the package, the worker cache, mounts and the layout."""

import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import utils.worker_utils as wu
from config import Config
from models import Task
from services import environment_package, hf_zip
from services.environment_package import PackageError
from tasks.task_modules.submission_runner import link_public_files
from tests.helpers.hf import CONFIG, hf_zip_bytes


@pytest.fixture
def store(app, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(uploads))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(uploads))
    os.makedirs(uploads / "hf")
    return uploads


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "hf_cache"
    root.mkdir()
    monkeypatch.setattr(Config, "HF_CACHE_DIR", str(root))
    return root


def _store_zip(data):
    sha256 = hashlib.sha256(data).hexdigest()
    with open(hf_zip.hf_zip_path(sha256), "wb") as handle:
        handle.write(data)
    return sha256


def _write(path, data):
    path = str(path)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


# ── Central directory checks and extraction ──


def test_hidden_entries_are_counted_and_never_extracted(tmp_path):
    path = _write(tmp_path / "hf.zip", hf_zip_bytes())
    summary = hf_zip.inspect_zip(path)
    assert [entry.path for entry in summary.entries] == ["models/acme/tiny/config.json"]
    assert summary.skipped_count == 2
    out = tmp_path / "out"
    out.mkdir()
    assert hf_zip.extract(path, str(out), max_unpacked=10**6) == len(CONFIG)
    extracted = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert extracted == ["models/acme/tiny/config.json"]
    assert (out / "models/acme/tiny/config.json").stat().st_mode & 0o777 == 0o644


def test_extraction_is_capped_at_the_recorded_unpacked_size(tmp_path):
    path = _write(tmp_path / "hf.zip", hf_zip_bytes())
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(hf_zip.HfZipError):
        hf_zip.extract(path, str(out), max_unpacked=len(CONFIG) - 1)


def test_a_corrupt_entry_fails_its_crc(tmp_path):
    data = bytearray(hf_zip_bytes({"models/a/b/c.txt": b"hello world"}, compression=0))
    data[data.find(b"hello world")] = ord("j")
    path = _write(tmp_path / "hf.zip", bytes(data))
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(hf_zip.HfZipError, match="corrupt"):
        hf_zip.extract(path, str(out), max_unpacked=10**6)


def test_too_many_entries_are_refused_before_reading_the_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_zip, "MAX_MEMBERS", 2)
    files = {f"models/a/b/{index}.txt": b"x" for index in range(3)}
    path = _write(tmp_path / "hf.zip", hf_zip_bytes(files))
    with pytest.raises(hf_zip.HfZipError, match="more than 2 entries"):
        hf_zip.inspect_zip(path)


def test_a_path_that_is_both_file_and_folder_is_refused(tmp_path):
    files = {"models/a/b/x": b"1", "models/a/b/x/y": b"2"}
    with pytest.raises(hf_zip.HfZipError, match="both a file and a folder"):
        hf_zip.inspect_zip(_write(tmp_path / "hf.zip", hf_zip_bytes(files)))


# ── Package ──


def _set_zip(task, sha256):
    """Record a stored ZIP on the task the way the upload route does."""
    summary = hf_zip.inspect_zip(hf_zip.hf_zip_path(sha256)) if sha256 else None
    task.hf_zip_sha256 = sha256
    task.hf_folders = summary.folders if summary else None
    task.hf_file_count = summary.file_count if summary else None
    task.hf_unpacked_bytes = summary.unpacked_bytes if summary else None


def _task(db_session, challenge, folder, sha256=None, notebook=None):
    task = Task(
        challenge_id=challenge.id,
        title=folder.upper(),
        folder_name=folder,
        baseline_notebook_path=notebook,
    )
    _set_zip(task, sha256)
    db_session.add(task)
    db_session.commit()
    return task


def test_the_package_ships_hf_folders_at_the_root_once(db_session, sample_challenge, store):
    shared = _store_zip(hf_zip_bytes())
    extra = _store_zip(
        hf_zip_bytes(
            {
                "models/acme/tiny/config.json": CONFIG,
                "datasets/acme/reviews/train.parquet": b"PAR1",
            }
        )
    )
    tasks = [
        _task(db_session, sample_challenge, "one", shared),
        _task(db_session, sample_challenge, "two", extra),
    ]
    entries, duplicates = environment_package.package_entries(tasks)
    assert duplicates
    assert [entry.arcname for entry in entries] == [
        "datasets/acme/reviews/train.parquet",
        "models/acme/tiny/config.json",
    ]
    built = environment_package.build(entries, "v", str(store / "packages"), duplicates)
    with zipfile.ZipFile(built.path) as archive:
        assert archive.read("models/acme/tiny/config.json") == CONFIG
        assert archive.namelist() == [entry.arcname for entry in entries]
    plan = environment_package.package_plan(tasks)
    assert plan.file_count == len(entries)
    assert plan.total_bytes == sum(entry.size for entry in entries)
    assert environment_package.data_gib(plan) == 1


def test_a_differing_folder_is_a_package_conflict(db_session, sample_challenge, store):
    first = _store_zip(hf_zip_bytes())
    second = _store_zip(hf_zip_bytes({"models/acme/tiny/config.json": b"{}"}))
    tasks = [
        _task(db_session, sample_challenge, "one", first),
        _task(db_session, sample_challenge, "two", second),
    ]
    with pytest.raises(PackageError) as raised:
        environment_package.package_plan(tasks)
    assert raised.value.code == "ERR_HF_FOLDER_CONFLICT"
    assert "models/acme/tiny" in raised.value.message
    assert raised.value.fields == {"folder": "models/acme/tiny", "detail": "ONE"}


def test_the_fingerprint_and_version_follow_the_hf_zip(db_session, sample_challenge, store):
    first = _store_zip(hf_zip_bytes())
    second = _store_zip(hf_zip_bytes({"models/acme/tiny/config.json": b"{}"}))
    task = _task(db_session, sample_challenge, "one", first)
    before = environment_package.package_entries([task])[0]
    plan_before = environment_package.fingerprint(environment_package.package_plan([task]))
    _set_zip(task, second)
    db_session.commit()
    after = environment_package.package_entries([task])[0]
    plan_after = environment_package.fingerprint(environment_package.package_plan([task]))
    assert plan_before != plan_after
    assert environment_package.content_version(before) != environment_package.content_version(after)
    assert environment_package.content_version(after) == environment_package.content_version(
        environment_package.package_entries([task])[0]
    )


def test_the_fingerprint_reads_no_zip_and_ignores_its_mtime(db_session, sample_challenge, store):
    sha256 = _store_zip(hf_zip_bytes())
    task = _task(db_session, sample_challenge, "one", sha256)
    first = environment_package.fingerprint(environment_package.package_plan([task]))
    os.utime(hf_zip.hf_zip_path(sha256), (1, 1))
    with patch("services.hf_zip.inspect_zip", side_effect=AssertionError("read")):
        plan = environment_package.package_plan([task])
    assert environment_package.fingerprint(plan) == first
    assert plan.hf_file_count == task.hf_file_count


def test_a_shared_folder_with_other_bytes_fails_the_build_by_sha256(
    db_session, sample_challenge, store
):
    first = _store_zip(hf_zip_bytes({"models/acme/tiny/w.bin": b"aaaa"}))
    second = _store_zip(hf_zip_bytes({"models/acme/tiny/w.bin": b"bbbb"}))
    tasks = [
        _task(db_session, sample_challenge, "one", first),
        _task(db_session, sample_challenge, "two", second),
    ]
    # Size and CRC are what the cheap checks compare; forge an equal CRC to reach the build
    with patch("services.hf_zip.folder_listing", return_value=[("models/acme/tiny/w.bin", 4, 0)]):
        environment_package.package_plan(tasks)
    entries, duplicates = environment_package.package_entries(tasks)
    assert [d.arcname for d in duplicates] == ["models/acme/tiny/w.bin"]
    with pytest.raises(PackageError) as raised:
        environment_package.build(entries, "v", str(store / "packages"), duplicates)
    assert raised.value.code == "ERR_HF_FOLDER_CONFLICT"
    assert raised.value.fields["folder"] == "models/acme/tiny"
    assert not os.listdir(store / "packages")


def test_large_entries_are_written_as_zip64(tmp_path, monkeypatch):
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 100)
    source = _write(tmp_path / "big.bin", b"x" * 500)
    entries = [environment_package.file_entry("one/big.bin", source)]
    built = environment_package.build(entries, "v", str(tmp_path / "out"))
    with zipfile.ZipFile(built.path) as archive:
        assert archive.read("one/big.bin") == b"x" * 500


# ── Worker cache ──


def test_the_cache_is_extracted_once_and_reused(cache, tmp_path):
    data = hf_zip_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    local = _write(tmp_path / "local.zip", data)
    logs = []
    first = wu.ensure_hf_cache(sha256, len(data), len(CONFIG), logs, local_zip=local)
    assert first == str(cache / sha256)
    assert (cache / sha256 / "models/acme/tiny/config.json").read_bytes() == CONFIG
    assert not (cache / sha256 / "models/acme/tiny/.gitattributes").exists()
    assert oct((cache / sha256).stat().st_mode & 0o777) == oct(0o755)
    marker = cache / sha256 / wu.HF_LAST_USED
    os.utime(marker, (1, 1))
    os.remove(local)
    assert wu.ensure_hf_cache(sha256, len(data), len(CONFIG), logs, local_zip=local) == first
    assert marker.stat().st_mtime > 1
    leftovers = [name for name in os.listdir(cache) if name not in (sha256, ".locks")]
    assert leftovers == []


def test_a_zip_that_does_not_match_its_hash_is_a_platform_failure(cache, tmp_path):
    local = _write(tmp_path / "local.zip", hf_zip_bytes())
    with pytest.raises(wu.HfCacheError, match="sha256"):
        wu.ensure_hf_cache("0" * 64, None, None, [], local_zip=local)
    assert os.listdir(cache) == [".locks"]


def test_the_worker_downloads_with_the_hf_zip_capability(cache, monkeypatch):
    data = hf_zip_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    seen = {}

    def fake_get(url, headers, timeout, stream):
        seen.update(url=url, capability=headers["X-Worker-Capability"])
        return SimpleNamespace(
            status_code=200, iter_content=lambda chunk_size: iter([data]), close=lambda: None
        )

    monkeypatch.setattr(wu.requests, "get", fake_get)
    metadata = {"main_server_url": "http://server", "worker_capabilities": {"hf_zip": "cap"}}
    path = wu.ensure_hf_cache(sha256, len(data), len(CONFIG), [], metadata=metadata)
    assert seen == {"url": f"http://server/api/worker/hf-zip/{sha256}", "capability": "cap"}
    assert os.path.isdir(os.path.join(path, "models"))


def test_the_sweep_removes_only_caches_unused_for_the_configured_days(cache, tmp_path):
    data = hf_zip_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    local = _write(tmp_path / "local.zip", data)
    wu.ensure_hf_cache(sha256, None, None, [], local_zip=local)
    fresh = "f" * 64
    (cache / fresh).mkdir()
    (cache / fresh / wu.HF_LAST_USED).touch()
    stale_temp = cache / ".extract-abc"
    stale_temp.mkdir()
    old = time.time() - (Config.HF_CACHE_UNUSED_DAYS + 1) * 86400
    os.utime(cache / sha256 / wu.HF_LAST_USED, (old, old))
    os.utime(stale_temp, (old, old))
    assert wu.run_hf_cache_sweep() == 1
    assert sorted(os.listdir(cache)) == [".locks", fresh]


def test_the_sweep_skips_a_cache_whose_lock_is_held(cache):
    sha256 = "a" * 64
    (cache / sha256).mkdir()
    old = time.time() - (Config.HF_CACHE_UNUSED_DAYS + 1) * 86400
    os.utime(cache / sha256, (old, old))
    with wu._file_lock(wu._hf_lock(sha256)):
        assert wu.run_hf_cache_sweep() == 0
    assert wu.run_hf_cache_sweep() == 1


# ── Sandbox mounts ──


def _cache_dir(cache, *roots):
    path = cache / ("b" * 64)
    for root in roots:
        (path / root / "acme" / "x").mkdir(parents=True)
    return str(path)


def test_a_worker_on_the_host_binds_its_cache_read_only(cache, monkeypatch):
    monkeypatch.setattr(wu, "_own_container_mounts", lambda client: None)
    directory = _cache_dir(cache, "models")
    mounts = wu.hf_sandbox_mounts(MagicMock(), directory)
    assert len(mounts) == 1
    assert mounts[0]["Target"] == "/models"
    assert mounts[0]["Source"] == os.path.join(directory, "models")
    assert (mounts[0]["Type"], mounts[0]["ReadOnly"]) == ("bind", True)


def test_a_worker_in_a_container_mounts_only_its_hash_from_the_volume(cache, monkeypatch):
    backing = {"Type": "volume", "Name": "lavbench_hf_cache", "Destination": str(cache)}
    monkeypatch.setattr(wu, "_own_container_mounts", lambda client: [backing])
    directory = _cache_dir(cache, "models", "datasets")
    mounts = wu.hf_sandbox_mounts(MagicMock(), directory)
    assert [mount["Target"] for mount in mounts] == ["/models", "/datasets"]
    for mount, root in zip(mounts, ("models", "datasets"), strict=True):
        assert mount["Source"] == "lavbench_hf_cache"
        assert mount["VolumeOptions"]["Subpath"] == f"{'b' * 64}/{root}"
        assert mount["ReadOnly"] is True


def test_a_bind_backed_cache_maps_to_the_host_path(cache, monkeypatch):
    backing = {"Type": "bind", "Source": "/srv/hf", "Destination": str(cache)}
    monkeypatch.setattr(wu, "_own_container_mounts", lambda client: [backing])
    mounts = wu.hf_sandbox_mounts(MagicMock(), _cache_dir(cache, "datasets"))
    assert mounts[0]["Source"] == f"/srv/hf/{'b' * 64}/datasets"


# ── One notebook in both layouts ──

NOTEBOOK_CODE = """
import json
with open("train.csv") as handle:
    rows = handle.read().split()
with open("../models/acme/tiny/config.json") as handle:
    config = json.load(handle)
print(json.dumps({"rows": rows, "model": config["model_type"]}))
"""


def _notebook(path):
    cells = [{"cell_type": "code", "metadata": {}, "outputs": [], "source": NOTEBOOK_CODE}]
    notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": cells}
    with open(path, "w") as handle:
        json.dump(notebook, handle)
    return str(path)


def _run_cells(notebook_path, cwd):
    from services.submission_service import extract_code_from_notebook

    code = "\n\n".join(extract_code_from_notebook(notebook_path))
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code], cwd=cwd, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def test_one_notebook_runs_unchanged_in_the_sandbox_and_the_workspace(
    db_session, sample_challenge, store, cache, tmp_path, monkeypatch
):
    data = hf_zip_bytes()
    sha256 = _store_zip(data)
    task = _task(db_session, sample_challenge, "sentiment", sha256)
    task.baseline_notebook_path = _notebook(tmp_path / "baseline.ipynb")
    task_dir = store / f"task_{task.id}"
    task_dir.mkdir()
    _write(task_dir / "saved-train.csv", b"a\nb\n")
    task.files = json.dumps([{"filename": "train.csv", "saved_name": "saved-train.csv"}])
    db_session.commit()

    # Workspace: nanoColab copies the package into /workspace and opens <folder>/solution.ipynb
    entries, _ = environment_package.package_entries([task])
    built = environment_package.build(entries, "v", str(tmp_path / "packages"))
    workspace = tmp_path / "workspace"
    with zipfile.ZipFile(built.path) as archive:
        archive.extractall(workspace)
    in_workspace = _run_cells(str(workspace / "sentiment/solution.ipynb"), workspace / "sentiment")

    # Sandbox: /app holds data/ and the public files; /models and /datasets come from the cache
    sandbox = tmp_path / "sandbox"
    app_dir = sandbox / "app"
    (app_dir / "data").mkdir(parents=True)
    _write(app_dir / "data" / "train.csv", b"a\nb\n")
    link_public_files(str(app_dir / "data"), str(app_dir), reserved={"submission.parquet"})
    hf_dir = wu.ensure_hf_cache(
        sha256, len(data), task.hf_unpacked_bytes, [], local_zip=hf_zip.hf_zip_path(sha256)
    )
    monkeypatch.setattr(wu, "_own_container_mounts", lambda client: None)
    for mount in wu.hf_sandbox_mounts(MagicMock(), hf_dir):
        os.symlink(mount["Source"], sandbox / mount["Target"].lstrip("/"))
    in_sandbox = _run_cells(task.baseline_notebook_path, app_dir)

    assert in_workspace["rows"] == in_sandbox["rows"] == ["a", "b"]
    assert in_workspace["model"] == in_sandbox["model"] == "bert"


def test_public_files_link_beside_the_code_without_shadowing_outputs(tmp_path):
    data = tmp_path / "run" / "data"
    data.mkdir(parents=True)
    _write(data / "train.csv", b"x")
    _write(data / "submission.parquet", b"stale")
    link_public_files(str(data), str(tmp_path / "run"), reserved={"submission.parquet"})
    assert (tmp_path / "run" / "train.csv").read_bytes() == b"x"
    assert os.stat(tmp_path / "run" / "train.csv").st_ino == os.stat(data / "train.csv").st_ino
    assert not (tmp_path / "run" / "submission.parquet").exists()
