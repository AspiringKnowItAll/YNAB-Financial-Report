"""
Unit tests for app/services/encryption.py

Covers:
- Basic encrypt/decrypt round-trip
- Locked-app (master_key=None) raises ValueError
- Wrong key raises InvalidToken
- Fernet is non-deterministic (random IV per call)
- Empty string and unicode round-trips
"""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services.encryption import decrypt, encrypt


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------

def test_encrypt_returns_bytes(master_key):
    result = encrypt("hello", master_key)
    assert isinstance(result, bytes)


def test_roundtrip(master_key):
    plaintext = "super-secret-api-key-1234"
    assert decrypt(encrypt(plaintext, master_key), master_key) == plaintext


def test_empty_string_roundtrip(master_key):
    assert decrypt(encrypt("", master_key), master_key) == ""


def test_unicode_roundtrip(master_key):
    text = "café ñoño 日本語 🔐"
    assert decrypt(encrypt(text, master_key), master_key) == text


def test_long_value_roundtrip(master_key):
    long_value = "x" * 512
    assert decrypt(encrypt(long_value, master_key), master_key) == long_value


def test_encrypt_is_nondeterministic(master_key):
    # Fernet uses a random IV — the same plaintext must produce different tokens
    c1 = encrypt("same-input", master_key)
    c2 = encrypt("same-input", master_key)
    assert c1 != c2


# ---------------------------------------------------------------------------
# Locked-app guard
# ---------------------------------------------------------------------------

def test_encrypt_none_key_raises_value_error():
    with pytest.raises(ValueError, match="locked"):
        encrypt("secret", None)


def test_decrypt_none_key_raises_value_error(master_key):
    token = encrypt("secret", master_key)
    with pytest.raises(ValueError, match="locked"):
        decrypt(token, None)


# ---------------------------------------------------------------------------
# Invalid ciphertext / wrong key
# ---------------------------------------------------------------------------

def test_decrypt_wrong_key_raises(master_key):
    token = encrypt("secret", master_key)
    wrong_key = Fernet.generate_key()
    with pytest.raises(InvalidToken):
        decrypt(token, wrong_key)


def test_decrypt_corrupted_bytes_raises(master_key):
    with pytest.raises(Exception):
        decrypt(b"not-a-valid-fernet-token", master_key)
