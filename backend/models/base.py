"""SQLAlchemy ORM base — db, GUID, uuid7, encryption helpers."""

import logging
import os
import sys
import threading
import time
import uuid
from typing import Any

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import CHAR, TypeDecorator, TypeEngine

from config import Config

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


_UUID7_LOCK = threading.Lock()
_uuid7_last_ms: int | None = None
_uuid7_last_counter = 0
# Version 7 in bits 76-79 and the RFC 9562 variant (0b10) in bits 62-63
_UUID7_FLAGS = (0x7 << 76) | (0x2 << 62)


def _uuid7_counter_and_tail() -> tuple[int, int]:
    rand = int.from_bytes(os.urandom(10), byteorder="big")
    # A 42-bit counter with its top bit clear, so it can count up within the millisecond
    return (rand >> 32) & 0x1FF_FFFF_FFFF, rand & 0xFFFF_FFFF


def uuid7() -> uuid.UUID:
    """Return a UUIDv7 that is larger than every one this process made before.

    RFC 9562 section 6.2, method 1, as CPython 3.14's uuid.uuid7() does it: a 42-bit
    counter, seeded randomly each millisecond, follows the 48-bit timestamp, so ids
    made within one millisecond (all the tasks of an imported challenge) still sort
    in creation order. Replace with uuid.uuid7 once the backend runs on Python 3.14.
    """
    global _uuid7_last_ms, _uuid7_last_counter
    with _UUID7_LOCK:
        timestamp_ms = time.time_ns() // 1_000_000
        if _uuid7_last_ms is None or timestamp_ms > _uuid7_last_ms:
            counter, tail = _uuid7_counter_and_tail()
        else:
            if timestamp_ms < _uuid7_last_ms:
                # The clock went back: stay after the last id
                timestamp_ms = _uuid7_last_ms + 1
            counter = _uuid7_last_counter + 1
            if counter > 0x3FF_FFFF_FFFF:
                # The counter is exhausted: borrow the next millisecond
                timestamp_ms += 1
                counter, tail = _uuid7_counter_and_tail()
            else:
                tail = int.from_bytes(os.urandom(4), byteorder="big")
        _uuid7_last_ms = timestamp_ms
        _uuid7_last_counter = counter
    value = (timestamp_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= ((counter >> 30) & 0x0FFF) << 64
    value |= (counter & 0x3FFF_FFFF) << 32
    value |= tail
    return uuid.UUID(int=value | _UUID7_FLAGS)


class GUID(TypeDecorator[Any]):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as standard UUID strings.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))  # type: ignore[no-any-return]
        else:
            return dialect.type_descriptor(CHAR(36))  # type: ignore[no-any-return]

    def process_bind_param(self, value: Any, dialect: Any) -> str | uuid.UUID | None:
        if value is None:
            return value
        try:
            if isinstance(value, uuid.UUID):
                u = value
            elif isinstance(value, int):
                u = uuid.UUID(int=value)
            else:
                val_str = str(value)
                try:
                    u = uuid.UUID(val_str)
                except ValueError:
                    try:
                        u = uuid.UUID(int=int(val_str))
                    except ValueError:
                        u = uuid.UUID(int=0)
        except Exception:
            u = uuid.UUID(int=0)

        if dialect.name == "postgresql":
            return u
        else:
            return str(u)

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        try:
            return str(uuid.UUID(str(value)))
        except ValueError:
            return str(value)


logger = logging.getLogger(__name__)

db = SQLAlchemy()

# Symmetric encryption key for PII fields. Must be explicitly configured.
# Server: ENCRYPTION_KEY. Workers: WORKER_ENCRYPTION_KEY (via config.py).
# We deliberately never derive it from SECRET_KEY so a worker leak of the
# JWT key never compromises encrypted-at-rest data
ENCRYPTION_KEY_BASE64 = Config.ENCRYPTION_KEY
if not ENCRYPTION_KEY_BASE64:
    logger.critical(
        "ENCRYPTION_KEY (server) or WORKER_ENCRYPTION_KEY (worker) is not set — "
        "refusing to start without an explicit encryption key."
    )
    sys.exit(1)
cipher_suite = Fernet(ENCRYPTION_KEY_BASE64.encode())


def encrypt_field(text: str | None) -> str | None:
    """Encrypt a plaintext string using Fernet symmetric encryption.

    Raises on failure instead of returning None so PII is never silently
    dropped — a failed write surfaces as a visible error, not a lost
    field.
    """
    if not text:
        return None
    try:
        return cipher_suite.encrypt(text.encode()).decode()
    except Exception:
        logger.exception("encrypt_field failed — re-raising to avoid silent data loss")
        raise


def decrypt_field(cipher_text: str | None) -> str | None:
    """Decrypt a Fernet-encrypted ciphertext back to plaintext."""
    if not cipher_text:
        return None
    try:
        return cipher_suite.decrypt(cipher_text.encode()).decode()
    except Exception:
        logger.exception("decrypt_field failed")
        return "[Decryption Error]"
