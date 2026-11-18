"""Build Hugging Face ZIPs in the layout ``hf download --local-dir`` writes."""

from __future__ import annotations

import io
import stat
import zipfile

CONFIG = b'{"model_type": "bert", "hidden_size": 8}'


def hf_zip_bytes(
    files: dict[str, bytes] | None = None,
    *,
    symlinks: dict[str, str] | None = None,
    compression: int = zipfile.ZIP_DEFLATED,
    encrypted: tuple[str, ...] = (),
) -> bytes:
    """A ZIP of ``files``; the default is one small model with its hidden HF metadata."""
    if files is None:
        files = {
            "models/acme/tiny/config.json": CONFIG,
            "models/acme/tiny/.gitattributes": b"*.bin filter=lfs\n",
            "models/acme/tiny/.cache/huggingface/download/config.json.metadata": b"x",
        }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    raw = bytearray(buffer.getvalue())
    if encrypted:
        _set_encrypted_flags(raw, encrypted)
    return bytes(raw)


def _set_encrypted_flags(raw: bytearray, names: tuple[str, ...]) -> None:
    """Set the encryption bit in the central directory entries of ``names``."""
    position = 0
    while (position := raw.find(b"PK\x01\x02", position)) >= 0:
        name_length = int.from_bytes(raw[position + 28 : position + 30], "little")
        name = raw[position + 46 : position + 46 + name_length].decode()
        if name in names:
            flags = int.from_bytes(raw[position + 8 : position + 10], "little") | 1
            raw[position + 8 : position + 10] = flags.to_bytes(2, "little")
        position += 4
