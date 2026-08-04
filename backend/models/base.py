"""SQLAlchemy ORM base — db, GUID, uuid7, encryption helpers."""

import logging
import os
import sys
import uuid
from typing import Any

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import CHAR, TypeDecorator, TypeEngine

from config import Config

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


def uuid7() -> uuid.UUID:
    import os
    import time

    ms = int(time.time() * 1000)
    rand_bytes = os.urandom(10)
    b_ts = ms.to_bytes(6, byteorder="big")
    v_and_rand = 0x7000 | (int.from_bytes(rand_bytes[:2], byteorder="big") & 0x0FFF)
    b_vr = v_and_rand.to_bytes(2, byteorder="big")
    var_and_rand = 0x8000000000000000 | (
        int.from_bytes(rand_bytes[2:], byteorder="big") & 0x3FFFFFFFFFFFFFFF
    )
    b_var_rand = var_and_rand.to_bytes(8, byteorder="big")
    return uuid.UUID(bytes=b_ts + b_vr + b_var_rand)


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
# JWT key never compromises encrypted-at-rest data.
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
    dropped (M-A6) — a failed write surfaces as a visible error, not a lost
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
