"""Tests for challenge archive structural validation.

Covers ``routes.challenges._validate_challenge_archive`` — the zip-slip,
zip-bomb, symlink and duplicate-member defenses applied to an uploaded
challenge archive before any member is read.
"""

import io
import stat
import zipfile

import pytest

from config import Config
from routes.challenges import _validate_challenge_archive

# ── Helpers ──


def _build_archive(members, compression=zipfile.ZIP_STORED):
    """Build an in-memory zip from ``(name, data, external_attr, flag_bits)`` tuples."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data, external_attr, flag_bits in members:
            info = zipfile.ZipInfo(name)
            info.external_attr = external_attr
            info.flag_bits |= flag_bits
            info.compress_type = compression
            zf.writestr(info, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _member(name, data=b"{}", external_attr=(stat.S_IFREG | 0o644) << 16, flag_bits=0):
    return (name, data, external_attr, flag_bits)


VALID_MEMBERS = [
    _member("challenge.json", b'{"title": "t"}'),
    _member("tasks/task-1/evaluator.py", b"print(1)"),
]


# ── Happy path ──


def test_valid_archive_passes():
    _validate_challenge_archive(_build_archive(VALID_MEMBERS))


def test_directory_members_are_allowed():
    members = [
        _member("tasks/", b"", (stat.S_IFDIR | 0o755) << 16),
        *VALID_MEMBERS,
    ]
    _validate_challenge_archive(_build_archive(members))


# ── Structure ──


def test_missing_challenge_json_is_rejected():
    members = [_member("tasks/task-1/evaluator.py", b"x")]
    with pytest.raises(ValueError, match=r"challenge\.json not found"):
        _validate_challenge_archive(_build_archive(members))


def test_unexpected_top_level_member_is_rejected():
    members = [*VALID_MEMBERS, _member("evil.sh", b"rm -rf /")]
    with pytest.raises(ValueError, match="Unexpected archive member"):
        _validate_challenge_archive(_build_archive(members))


def test_too_deeply_nested_task_member_is_rejected():
    members = [*VALID_MEMBERS, _member("tasks/task-1/nested/evaluator.py", b"x")]
    with pytest.raises(ValueError, match="Unexpected archive member"):
        _validate_challenge_archive(_build_archive(members))


# ── Path traversal (zip slip) ──


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "tasks/../../evil.txt",
        "tasks/task-1/../../../etc/passwd",
        "/etc/passwd",
    ],
)
def test_path_traversal_and_absolute_paths_are_rejected(name):
    members = [*VALID_MEMBERS, _member(name, b"x")]
    with pytest.raises(ValueError, match="Invalid archive member path"):
        _validate_challenge_archive(_build_archive(members))


def test_backslash_paths_are_rejected():
    members = [*VALID_MEMBERS, _member("tasks\\task-1\\evaluator.py", b"x")]
    with pytest.raises(ValueError, match="Invalid archive member path"):
        _validate_challenge_archive(_build_archive(members))


# ── Member kinds ──


def test_symlink_members_are_rejected():
    members = [
        *VALID_MEMBERS,
        _member("tasks/task-1/link.py", b"/etc/passwd", (stat.S_IFLNK | 0o777) << 16),
    ]
    with pytest.raises(ValueError, match="Special archive member"):
        _validate_challenge_archive(_build_archive(members))


def test_encrypted_members_are_rejected():
    """``writestr`` recomputes flag bits, so set the encryption bit on the read side."""
    archive = _build_archive([*VALID_MEMBERS, _member("tasks/task-1/secret.py", b"x")])
    archive.infolist()[-1].flag_bits |= 0x1
    with pytest.raises(ValueError, match="Encrypted ZIP members"):
        _validate_challenge_archive(archive)


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_duplicate_member_names_are_rejected():
    members = [*VALID_MEMBERS, _member("challenge.json", b'{"title": "other"}')]
    with pytest.raises(ValueError, match="duplicate member"):
        _validate_challenge_archive(_build_archive(members))


def test_members_colliding_on_sanitized_filename_are_rejected():
    """Two distinct names that ``secure_filename`` collapses onto one target."""
    members = [
        *VALID_MEMBERS,
        _member("tasks/task-2/a b.txt", b"x"),
        _member("tasks/task-2/a_b.txt", b"y"),
    ]
    with pytest.raises(ValueError, match="duplicate target"):
        _validate_challenge_archive(_build_archive(members))


# ── Resource bounds (zip bomb) ──


def test_member_count_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(Config, "CHALLENGE_ARCHIVE_MAX_MEMBERS", 2)
    members = [*VALID_MEMBERS, _member("tasks/task-1/extra.py", b"x")]
    with pytest.raises(ValueError, match="too many members"):
        _validate_challenge_archive(_build_archive(members))


def test_per_member_size_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(Config, "CHALLENGE_ARCHIVE_MAX_MEMBER_BYTES", 8)
    members = [*VALID_MEMBERS, _member("tasks/task-1/big.py", b"x" * 64)]
    with pytest.raises(ValueError, match="per-file size limit"):
        _validate_challenge_archive(_build_archive(members))


def test_aggregate_uncompressed_size_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(Config, "CHALLENGE_ARCHIVE_MAX_UNCOMPRESSED_BYTES", 32)
    members = [
        *VALID_MEMBERS,
        _member("tasks/task-1/a.py", b"x" * 24),
        _member("tasks/task-1/b.py", b"y" * 24),
    ]
    with pytest.raises(ValueError, match="aggregate uncompressed size limit"):
        _validate_challenge_archive(_build_archive(members))


def test_compression_ratio_limit_is_enforced(monkeypatch):
    """A highly compressible member is a zip bomb even when its stored size is small."""
    monkeypatch.setattr(Config, "CHALLENGE_ARCHIVE_MAX_COMPRESSION_RATIO", 10)
    members = [
        _member("challenge.json", b'{"title": "t"}'),
        _member("tasks/task-1/bomb.py", b"\0" * 200_000),
    ]
    archive = _build_archive(members, compression=zipfile.ZIP_DEFLATED)
    with pytest.raises(ValueError, match="compression-ratio limit"):
        _validate_challenge_archive(archive)
