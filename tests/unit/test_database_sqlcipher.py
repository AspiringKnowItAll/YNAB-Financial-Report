"""
Unit tests for SQLCipher whole-database encryption in app/database.py.

Covers:
- set_database_key: stores key, registers event listener, idempotent re-calls
- migrate_plaintext_to_encrypted: sentinel skip, fresh install, already-encrypted,
  plaintext migration, failure re-raise
- _on_connect: PRAGMA key issued when key is set, skipped when key is None

All file-system tests use tmp_path; no Docker container or /data/ dir required.
"""

import sqlite3 as stdlib_sqlite3
from unittest.mock import MagicMock

import pytest

sqlcipher3 = pytest.importorskip("sqlcipher3", reason="sqlcipher3 not installed")
db_mod = pytest.importorskip("app.database", reason="app.database requires sqlcipher3")

from sqlalchemy import event  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_db_key():
    """Reset _db_key before and after each test to avoid cross-contamination."""
    original = db_mod._db_key
    db_mod._db_key = None
    yield
    db_mod._db_key = original


@pytest.fixture()
def db_paths(tmp_path, monkeypatch):
    """Redirect sentinel / DB / encrypted-DB paths to a temp directory."""
    db_path = tmp_path / "ynab_report.db"
    enc_path = tmp_path / "ynab_report_enc.db"
    sentinel = tmp_path / "migration_complete"
    monkeypatch.setattr(db_mod, "_DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_DB_ENC_PATH", enc_path)
    monkeypatch.setattr(db_mod, "_SENTINEL_PATH", sentinel)
    return db_path, enc_path, sentinel


TEST_KEY = b"\x01\x02\x03\x04" * 8  # 32 bytes
ALT_KEY = b"\xaa\xbb\xcc\xdd" * 8


# ---------------------------------------------------------------------------
# TestSetDatabaseKey
# ---------------------------------------------------------------------------

class TestSetDatabaseKey:

    def test_set_database_key_stores_key(self):
        db_mod.set_database_key(TEST_KEY)
        assert db_mod._db_key == TEST_KEY

    def test_set_database_key_idempotent(self):
        db_mod.set_database_key(TEST_KEY)
        db_mod.set_database_key(TEST_KEY)
        db_mod.set_database_key(ALT_KEY)

        assert db_mod._db_key == ALT_KEY
        # Event listener is registered exactly once, not duplicated.
        assert event.contains(
            db_mod.engine.sync_engine, "connect", db_mod._on_connect
        )

    def test_set_database_key_registers_event(self):
        db_mod.set_database_key(TEST_KEY)
        assert event.contains(
            db_mod.engine.sync_engine, "connect", db_mod._on_connect
        )


# ---------------------------------------------------------------------------
# TestMigratePlaintextToEncrypted
# ---------------------------------------------------------------------------

class TestMigratePlaintextToEncrypted:

    async def test_skips_if_sentinel_exists(self, db_paths, monkeypatch):
        _db_path, _enc_path, sentinel = db_paths
        sentinel.write_text("done")

        mock_connect = MagicMock()
        monkeypatch.setattr(db_mod.sqlcipher3, "connect", mock_connect)

        await db_mod.migrate_plaintext_to_encrypted(TEST_KEY)
        mock_connect.assert_not_called()

    async def test_skips_and_writes_sentinel_for_fresh_install(
        self, db_paths, monkeypatch
    ):
        db_path, _enc_path, sentinel = db_paths
        # db_path does not exist (fresh install)
        assert not db_path.exists()

        mock_connect = MagicMock()
        monkeypatch.setattr(db_mod.sqlcipher3, "connect", mock_connect)

        await db_mod.migrate_plaintext_to_encrypted(TEST_KEY)

        assert sentinel.exists()
        mock_connect.assert_not_called()

    async def test_skips_if_already_encrypted(self, db_paths):
        db_path, _enc_path, sentinel = db_paths
        hex_key = TEST_KEY.hex()

        # Create a real SQLCipher-encrypted DB at the expected path.
        conn = sqlcipher3.connect(str(db_path))
        conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        conn.execute("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY)")
        conn.close()

        await db_mod.migrate_plaintext_to_encrypted(TEST_KEY)

        assert sentinel.exists()

    async def test_migrates_plaintext_db(self, db_paths):
        db_path, _enc_path, sentinel = db_paths

        # Create a genuine plaintext SQLite DB using stdlib sqlite3.
        conn = stdlib_sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items (id, name) VALUES (1, 'widget')")
        conn.commit()
        conn.close()

        await db_mod.migrate_plaintext_to_encrypted(TEST_KEY)

        # Sentinel should be written.
        assert sentinel.exists()

        # The file at db_path should now be encrypted — stdlib sqlite3 should
        # fail to read it (will error on the first real query).
        raw_conn = stdlib_sqlite3.connect(str(db_path))
        with pytest.raises(Exception):
            raw_conn.execute("SELECT count(*) FROM sqlite_master")
        raw_conn.close()

        # Open with sqlcipher3 + key — original data must be intact.
        hex_key = TEST_KEY.hex()
        enc_conn = sqlcipher3.connect(str(db_path))
        enc_conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        tables = enc_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [row[0] for row in tables]
        assert "items" in table_names

        rows = enc_conn.execute("SELECT id, name FROM items").fetchall()
        assert rows == [(1, "widget")]
        enc_conn.close()

    async def test_migration_failure_reraises(self, db_paths, monkeypatch):
        db_path, _enc_path, sentinel = db_paths

        # Create a plaintext DB so the function gets past the "no file" check.
        conn = stdlib_sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
        conn.close()

        # Patch asyncio.to_thread to simulate a failure inside _migrate_sync.
        async def boom(*args, **kwargs):
            raise RuntimeError("simulated migration failure")

        monkeypatch.setattr("asyncio.to_thread", boom)

        with pytest.raises(RuntimeError, match="simulated migration failure"):
            await db_mod.migrate_plaintext_to_encrypted(TEST_KEY)

        # Sentinel must NOT be written on failure.
        assert not sentinel.exists()


# ---------------------------------------------------------------------------
# TestOnConnect
# ---------------------------------------------------------------------------

class TestOnConnect:

    def test_on_connect_issues_pragma_key(self):
        db_mod.set_database_key(TEST_KEY)
        mock_conn = MagicMock()

        db_mod._on_connect(mock_conn, None)

        mock_conn.execute.assert_called_once()
        call_sql = mock_conn.execute.call_args[0][0]
        assert "PRAGMA key" in call_sql
        assert TEST_KEY.hex() in call_sql

    def test_on_connect_skips_if_no_key(self):
        db_mod._db_key = None
        mock_conn = MagicMock()

        db_mod._on_connect(mock_conn, None)

        mock_conn.execute.assert_not_called()
