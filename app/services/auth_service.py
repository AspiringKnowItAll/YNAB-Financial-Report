"""
Master password setup, unlock, and recovery code management.

Security design:
- Master password is NEVER stored. Only the Argon2id salt and a Fernet
  verification token are persisted to disk.
- On unlock, the password is re-derived using the stored salt and verified
  against the stored token. The derived key is held in app.state.master_key.
- 8 recovery codes are generated after setup using key-wrapping (LUKS-style):
  each code derives its own key via Argon2id which wraps (Fernet-encrypts) the
  master key. Wrapped keys are stored in /data/recovery_keys.json.
- Recovery codes are single-use. Using one marks it used=True and immediately
  prompts the user to set a new master password.
"""

import base64
import json
import os
import secrets
import string
import threading

from argon2.low_level import Type, hash_secret_raw
from cryptography.fernet import Fernet, InvalidToken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = "/data"
SALT_PATH = os.path.join(DATA_DIR, "master.salt")
VERIFY_PATH = os.path.join(DATA_DIR, "master.verify")
RECOVERY_PATH = os.path.join(DATA_DIR, "recovery_keys.json")

ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536  # 64 MB
ARGON2_PARALLELISM = 1
ARGON2_HASH_LEN = 32

RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_ALPHABET = string.ascii_uppercase + string.digits
RECOVERY_CODE_GROUP_LEN = 5
RECOVERY_CODE_GROUPS = 4

# Known plaintext encrypted into master.verify for password verification
_VERIFY_PLAINTEXT = b"ynab-financial-report-verify-v1"

# Lock to prevent TOCTOU race in use_recovery_code()
_recovery_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet-compatible key from password + salt via Argon2id."""
    raw = hash_secret_raw(
        secret=password.encode(),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,
    )
    # Fernet requires a 32-byte URL-safe base64-encoded key
    return base64.urlsafe_b64encode(raw)


def _generate_recovery_code() -> str:
    """Generate one recovery code in XXXXX-XXXXX-XXXXX-XXXXX format."""
    groups = [
        "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(RECOVERY_CODE_GROUP_LEN))
        for _ in range(RECOVERY_CODE_GROUPS)
    ]
    return "-".join(groups)


def _wrap_master_key(master_key: bytes, code: str) -> dict:
    """
    Key-wrap master_key using a key derived from the recovery code.
    Returns a dict with {salt_b64, wrapped_key_b64, used}.
    """
    salt = secrets.token_bytes(16)
    code_key = _derive_key(code, salt)
    f = Fernet(code_key)
    wrapped = f.encrypt(master_key)
    return {
        "salt_b64": base64.b64encode(salt).decode(),
        "wrapped_key_b64": base64.b64encode(wrapped).decode(),
        "used": False,
    }


def _unwrap_master_key(slot: dict, code: str) -> bytes:
    """
    Unwrap master_key from a recovery slot using the recovery code.
    Raises ValueError if the code is wrong.
    """
    salt = base64.b64decode(slot["salt_b64"])
    wrapped = base64.b64decode(slot["wrapped_key_b64"])
    code_key = _derive_key(code, salt)
    f = Fernet(code_key)
    try:
        return f.decrypt(wrapped)
    except InvalidToken as exc:
        raise ValueError("Invalid recovery code.") from exc


def _read_recovery_slots() -> list[dict]:
    with open(RECOVERY_PATH) as fh:
        return json.load(fh)


def _write_recovery_slots(slots: list[dict]) -> None:
    tmp_path = RECOVERY_PATH + ".tmp"
    with open(tmp_path, "w") as fh:
        json.dump(slots, fh, indent=2)
    os.replace(tmp_path, RECOVERY_PATH)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def setup_master_password(password: str) -> list[str]:
    """
    First-run: derive a master key from password, persist salt + verify token,
    generate 8 recovery codes, write key-wrapped recovery data to disk.

    Returns:
        List of 8 plaintext recovery codes to display once to the user.

    Raises:
        RuntimeError: If master password has already been set up.
    """
    if os.path.exists(SALT_PATH):
        raise RuntimeError("Master password has already been set up.")

    os.makedirs(DATA_DIR, exist_ok=True)

    # Derive master key
    salt = secrets.token_bytes(16)
    master_key = _derive_key(password, salt)

    # Persist salt
    with open(SALT_PATH, "wb") as fh:
        fh.write(salt)

    # Persist verification token
    f = Fernet(master_key)
    verify_token = f.encrypt(_VERIFY_PLAINTEXT)
    with open(VERIFY_PATH, "wb") as fh:
        fh.write(verify_token)

    # Generate recovery codes and key-wrap the master key for each
    codes: list[str] = []
    slots: list[dict] = []
    for _ in range(RECOVERY_CODE_COUNT):
        code = _generate_recovery_code()
        codes.append(code)
        slots.append(_wrap_master_key(master_key, code))

    _write_recovery_slots(slots)

    return codes


async def unlock(password: str) -> bytes:
    """
    Verify the password against the stored salt + verify token.

    Returns:
        The Fernet master key (to be stored in app.state.master_key).

    Raises:
        ValueError: If the password is incorrect.
        FileNotFoundError: If master.salt or master.verify do not exist.
    """
    with open(SALT_PATH, "rb") as fh:
        salt = fh.read()

    with open(VERIFY_PATH, "rb") as fh:
        verify_token = fh.read()

    master_key = _derive_key(password, salt)

    f = Fernet(master_key)
    try:
        plaintext = f.decrypt(verify_token)
    except InvalidToken as exc:
        raise ValueError("Incorrect master password.") from exc

    if plaintext != _VERIFY_PLAINTEXT:
        raise ValueError("Incorrect master password.")

    return master_key


async def use_recovery_code(code: str) -> bytes:
    """
    Validate a recovery code, unwrap the master key, and mark the slot used.

    Returns:
        The Fernet master key.

    Raises:
        ValueError: If the code is invalid or has already been used.
    """
    with _recovery_lock:
        slots = _read_recovery_slots()

        for i, slot in enumerate(slots):
            if slot["used"]:
                continue
            try:
                master_key = _unwrap_master_key(slot, code)
            except ValueError:
                continue

            # Valid code found — mark it used immediately
            slots[i]["used"] = True
            _write_recovery_slots(slots)
            return master_key

    raise ValueError("Recovery code is invalid or has already been used.")


def is_setup_complete() -> bool:
    """Return True if master.salt exists on disk (first-run has been completed)."""
    return os.path.exists(SALT_PATH)
