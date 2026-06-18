"""Per-user provider key management. Keys are encrypted at rest with Fernet."""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet

_SECRET_FILE = Path(__file__).parent.parent / ".keys_secret"


def _get_fernet() -> Fernet:
    secret = os.environ.get("KEYS_ENCRYPTION_SECRET")
    if not secret:
        if _SECRET_FILE.exists():
            secret = _SECRET_FILE.read_text().strip()
        else:
            secret = Fernet.generate_key().decode()
            _SECRET_FILE.write_text(secret)
            try:
                os.chmod(_SECRET_FILE, 0o600)
            except OSError:
                pass
    # secret might be a fernet key (urlsafe-b64 32 bytes) or arbitrary string
    try:
        Fernet(secret.encode())
        key = secret.encode()
    except (ValueError, TypeError):
        digest = hashlib.sha256(secret.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


_fernet = _get_fernet()

SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini", "ollama")


def encrypt_key(plain: str) -> str:
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_key(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


def mask(plain: str) -> str:
    if not plain:
        return ""
    if len(plain) <= 8:
        return "•" * len(plain)
    return plain[:4] + "•" * 8 + plain[-4:]
