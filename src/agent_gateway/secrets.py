"""Fernet-based encryption for user secrets in per-user agent configuration."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet(key: str | None = None) -> Fernet:
    """Build a Fernet instance from the provided key or environment variable.

    The key can be a raw Fernet key (44-char base64) or an arbitrary string
    that gets hashed to derive a valid key.
    """
    raw = key or os.environ.get("AGENT_GATEWAY_SECRET_KEY")
    if not raw:
        raise ValueError(
            "Secret key required for user secret encryption. "
            "Set AGENT_GATEWAY_SECRET_KEY environment variable."
        )
    # If it looks like a valid Fernet key, use directly
    try:
        Fernet(raw.encode() if isinstance(raw, str) else raw)
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception:
        pass
    # Otherwise derive a 32-byte key via SHA-256 and base64 encode
    derived = hashlib.sha256(raw.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_value(plaintext: str, key: str | None = None) -> str:
    """Encrypt a plaintext string, returning a base64-encoded ciphertext."""
    f = _get_fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str, key: str | None = None) -> str:
    """Decrypt a ciphertext string back to plaintext.

    Raises ValueError if the ciphertext is invalid or the key is wrong.
    """
    f = _get_fernet(key)
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Failed to decrypt secret: invalid key or corrupted data") from e


def get_sensitive_fields(setup_schema: dict[str, Any]) -> set[str]:
    """Extract field names marked as sensitive from a setup schema."""
    sensitive = set()
    props = setup_schema.get("properties", {})
    for name, prop in props.items():
        if prop.get("sensitive", False):
            sensitive.add(name)
    return sensitive
