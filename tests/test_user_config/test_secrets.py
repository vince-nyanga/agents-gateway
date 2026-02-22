"""Tests for user secret encryption/decryption."""

from __future__ import annotations

import pytest

from agent_gateway.secrets import decrypt_value, encrypt_value, get_sensitive_fields


class TestEncryptDecrypt:
    """Test Fernet encryption/decryption."""

    def test_roundtrip_with_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_GATEWAY_SECRET_KEY", "test-secret-key-for-encryption")
        plaintext = "my-super-secret-password"
        ciphertext = encrypt_value(plaintext)
        assert ciphertext != plaintext
        assert decrypt_value(ciphertext) == plaintext

    def test_roundtrip_with_explicit_key(self) -> None:
        key = "explicit-test-key"
        plaintext = "another-secret"
        ciphertext = encrypt_value(plaintext, key=key)
        assert decrypt_value(ciphertext, key=key) == plaintext

    def test_wrong_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_GATEWAY_SECRET_KEY", "key-one")
        ciphertext = encrypt_value("secret")
        monkeypatch.setenv("AGENT_GATEWAY_SECRET_KEY", "key-two")
        with pytest.raises(ValueError, match="Failed to decrypt"):
            decrypt_value(ciphertext)

    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_GATEWAY_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="Secret key required"):
            encrypt_value("test")

    def test_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_GATEWAY_SECRET_KEY", "test-key")
        ciphertext = encrypt_value("")
        assert decrypt_value(ciphertext) == ""


class TestGetSensitiveFields:
    """Test sensitive field extraction from setup schemas."""

    def test_extracts_sensitive_fields(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "password": {"type": "string", "sensitive": True},
                "api_key": {"type": "string", "sensitive": True},
                "name": {"type": "string", "sensitive": False},
            },
        }
        assert get_sensitive_fields(schema) == {"password", "api_key"}

    def test_no_sensitive_fields(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        assert get_sensitive_fields(schema) == set()

    def test_empty_schema(self) -> None:
        assert get_sensitive_fields({}) == set()
