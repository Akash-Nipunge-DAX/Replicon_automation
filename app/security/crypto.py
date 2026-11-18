"""Encrypt Replicon access tokens at rest (Fernet).

Pattern — keep secrets out of plaintext storage; derive key from SECRET_KEY.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    # Derive a stable 32-byte url-safe key from SECRET_KEY.
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_token(plain_token: str) -> str:
    return _fernet().encrypt(plain_token.encode("utf-8")).decode("utf-8")


def decrypt_token(token_encrypted: str) -> str:
    try:
        return _fernet().decrypt(token_encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Could not decrypt stored Replicon token. "
            "If SECRET_KEY changed, re-enter your token on the Setup page."
        ) from exc
