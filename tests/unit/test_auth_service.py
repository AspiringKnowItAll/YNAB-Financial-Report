"""
Unit tests for app/services/auth_service.py

Covers:
- is_setup_complete: False before setup, True after
- setup_master_password: creates salt/verify/recovery files, returns 8 codes,
                         code format, code uniqueness, raises if already done
- unlock: correct password returns a Fernet key, wrong password raises ValueError
- use_recovery_code: valid code returns master key, marks slot used,
                     reuse of used code raises ValueError, wrong code raises ValueError

Argon2id is patched to minimal parameters (time_cost=1, memory_cost=8192) so
tests complete in milliseconds without compromising coverage of the logic paths.
"""

import json
import re

import pytest

import app.services.auth_service as auth_mod
from app.services.auth_service import (
    is_setup_complete,
    setup_master_password,
    unlock,
    use_recovery_code,
)

RECOVERY_CODE_RE = re.compile(r"^[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    """Replace Argon2id parameters with minimal values for test speed."""
    monkeypatch.setattr(auth_mod, "ARGON2_TIME_COST", 1)
    monkeypatch.setattr(auth_mod, "ARGON2_MEMORY_COST", 8192)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all file I/O to a temporary directory."""
    salt = tmp_path / "master.salt"
    verify = tmp_path / "master.verify"
    recovery = tmp_path / "recovery_keys.json"
    monkeypatch.setattr(auth_mod, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth_mod, "SALT_PATH", str(salt))
    monkeypatch.setattr(auth_mod, "VERIFY_PATH", str(verify))
    monkeypatch.setattr(auth_mod, "RECOVERY_PATH", str(recovery))
    return tmp_path


# ---------------------------------------------------------------------------
# is_setup_complete
# ---------------------------------------------------------------------------

def test_is_setup_complete_false_before_setup(data_dir):
    assert is_setup_complete() is False


async def test_is_setup_complete_true_after_setup(data_dir):
    await setup_master_password("correct-horse-battery-staple")
    assert is_setup_complete() is True


# ---------------------------------------------------------------------------
# setup_master_password
# ---------------------------------------------------------------------------

async def test_setup_creates_required_files(data_dir):
    await setup_master_password("correct-horse-battery-staple")
    assert (data_dir / "master.salt").exists()
    assert (data_dir / "master.verify").exists()
    assert (data_dir / "recovery_keys.json").exists()


async def test_setup_returns_eight_codes(data_dir):
    codes = await setup_master_password("correct-horse-battery-staple")
    assert len(codes) == 8


async def test_setup_code_format(data_dir):
    codes = await setup_master_password("correct-horse-battery-staple")
    for code in codes:
        assert RECOVERY_CODE_RE.match(code), f"Bad code format: {code}"


async def test_setup_codes_are_unique(data_dir):
    codes = await setup_master_password("correct-horse-battery-staple")
    assert len(set(codes)) == 8


async def test_setup_recovery_json_has_eight_slots(data_dir):
    await setup_master_password("correct-horse-battery-staple")
    slots = json.loads((data_dir / "recovery_keys.json").read_text())
    assert len(slots) == 8
    for slot in slots:
        assert slot["used"] is False


async def test_setup_raises_if_already_done(data_dir):
    await setup_master_password("correct-horse-battery-staple")
    with pytest.raises(RuntimeError, match="already been set up"):
        await setup_master_password("another-password")


# ---------------------------------------------------------------------------
# unlock
# ---------------------------------------------------------------------------

async def test_unlock_correct_password_returns_key(data_dir):
    password = "correct-horse-battery-staple"
    await setup_master_password(password)
    key = await unlock(password)
    assert isinstance(key, bytes)
    assert len(key) > 0


async def test_unlock_returns_same_key_each_time(data_dir):
    password = "correct-horse-battery-staple"
    await setup_master_password(password)
    key1 = await unlock(password)
    key2 = await unlock(password)
    assert key1 == key2


async def test_unlock_wrong_password_raises(data_dir):
    await setup_master_password("correct-horse-battery-staple")
    with pytest.raises(ValueError, match="Incorrect master password"):
        await unlock("wrong-password")


def test_unlock_missing_salt_raises(data_dir):
    with pytest.raises(FileNotFoundError):
        import asyncio
        asyncio.get_event_loop().run_until_complete(unlock("any-password"))


# ---------------------------------------------------------------------------
# use_recovery_code
# ---------------------------------------------------------------------------

async def test_recovery_code_returns_master_key(data_dir):
    password = "correct-horse-battery-staple"
    codes = await setup_master_password(password)
    master_key = await unlock(password)

    recovered_key = await use_recovery_code(codes[0])
    assert recovered_key == master_key


async def test_recovery_code_marks_slot_used(data_dir):
    codes = await setup_master_password("correct-horse-battery-staple")
    await use_recovery_code(codes[0])

    slots = json.loads((data_dir / "recovery_keys.json").read_text())
    used_slots = [s for s in slots if s["used"]]
    assert len(used_slots) == 1


async def test_recovery_code_cannot_be_reused(data_dir):
    codes = await setup_master_password("correct-horse-battery-staple")
    await use_recovery_code(codes[0])
    with pytest.raises(ValueError, match="invalid or has already been used"):
        await use_recovery_code(codes[0])


async def test_invalid_recovery_code_raises(data_dir):
    await setup_master_password("correct-horse-battery-staple")
    with pytest.raises(ValueError, match="invalid or has already been used"):
        await use_recovery_code("AAAAA-BBBBB-CCCCC-DDDDD")


async def test_remaining_codes_still_valid_after_one_used(data_dir):
    codes = await setup_master_password("correct-horse-battery-staple")
    await use_recovery_code(codes[0])
    # A different code should still work
    key = await use_recovery_code(codes[1])
    assert isinstance(key, bytes)
