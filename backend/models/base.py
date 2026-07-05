"""SQLAlchemy ORM base — db, GUID, uuid7, encryption helpers."""

import base64
import hashlib
import logging
import os
import sys
import uuid

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import CHAR, TypeDecorator

from config import Config

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))


def uuid7():
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


class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as standard UUID strings.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
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

    def process_result_value(self, value, dialect):
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

# Derive a stable symmetric encryption key from SECRET_KEY or ENCRYPTION_KEY
ENCRYPTION_KEY_BASE64 = Config.ENCRYPTION_KEY
if ENCRYPTION_KEY_BASE64:
    cipher_suite = Fernet(ENCRYPTION_KEY_BASE64.encode())
else:
    SECRET_KEY = Config.SECRET_KEY
    if not SECRET_KEY:
        logger.critical("SECRET_KEY environment variable is not set")
        sys.exit(1)
    DERIVED_KEY = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
    cipher_suite = Fernet(DERIVED_KEY)


def encrypt_field(text):
    """Encrypt a plaintext string using Fernet symmetric encryption."""
    if not text:
        return None
    try:
        return cipher_suite.encrypt(text.encode()).decode()
    except Exception:
        logger.exception("encrypt_field failed")
        return None


def decrypt_field(cipher_text):
    """Decrypt a Fernet-encrypted ciphertext back to plaintext."""
    if not cipher_text:
        return None
    try:
        return cipher_suite.decrypt(cipher_text.encode()).decode()
    except Exception:
        logger.exception("decrypt_field failed")
        return "[Decryption Error]"
