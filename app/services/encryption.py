"""
Fernet-based encryption/decryption for secrets stored in the database.

Rules:
- Only two public functions: encrypt() and decrypt().
- Both require app.state.master_key to be set (i.e. the app must be unlocked).
- Decrypted values must NEVER be logged or returned in API responses.
- Encrypted columns in the DB are LargeBinary with names ending in _enc.
"""

from cryptography.fernet import Fernet


def encrypt(plaintext: str, master_key: bytes) -> bytes:
    """
    Encrypt a plaintext string using Fernet (AES-128-CBC + HMAC-SHA256).

    Args:
        plaintext: The secret value to encrypt.
        master_key: The 32-byte Fernet key from app.state.master_key.

    Returns:
        Fernet token as bytes, suitable for storage in a LargeBinary column.

    Raises:
        ValueError: If master_key is None (app is locked).
    """
    if master_key is None:
        raise ValueError("App is locked — master_key is not set. Unlock the app first.")
    fernet = Fernet(master_key)
    return fernet.encrypt(plaintext.encode())


def decrypt(ciphertext: bytes, master_key: bytes) -> str:
    """
    Decrypt a Fernet-encrypted ciphertext back to a plaintext string.

    Args:
        ciphertext: The encrypted bytes from a LargeBinary column.
        master_key: The 32-byte Fernet key from app.state.master_key.

    Returns:
        The decrypted plaintext string. Do NOT log this value.

    Raises:
        ValueError: If master_key is None (app is locked).
        cryptography.fernet.InvalidToken: If the ciphertext is corrupt or the
            key does not match.
    """
    if master_key is None:
        raise ValueError("App is locked — master_key is not set. Unlock the app first.")
    fernet = Fernet(master_key)
    return fernet.decrypt(ciphertext).decode()
