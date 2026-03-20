import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime as _dt
from datetime import timezone as _tz
from pathlib import Path

import aiosqlite.core
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

try:
    import sqlcipher3  # type: ignore[import-untyped]
    # Monkey-patch aiosqlite to use sqlcipher3 instead of stdlib sqlite3.
    # Must happen before any engine or connection is created.
    aiosqlite.core.sqlite3 = sqlcipher3  # type: ignore[attr-defined]
except ImportError:
    # In test environments, ALLOW_PLAINTEXT_DB=1 permits falling back to stdlib
    # sqlite3 so tests can run without the native SQLCipher library.
    # In all other environments this is a fatal error — the database must be
    # encrypted.
    if os.environ.get("ALLOW_PLAINTEXT_DB") != "1":
        raise RuntimeError(
            "sqlcipher3-binary is not installed and ALLOW_PLAINTEXT_DB is not set. "
            "The database cannot be opened without encryption. "
            "Install sqlcipher3-binary or set ALLOW_PLAINTEXT_DB=1 for test environments only."
        ) from None
    import sqlite3 as sqlcipher3  # type: ignore[assignment]

logger = logging.getLogger("app.database")

DATABASE_URL = "sqlite+aiosqlite:////data/ynab_report.db"

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    pass


_db_key: bytes | None = None

_SENTINEL_PATH = Path("/data/migration_complete")
_DB_PATH = Path("/data/ynab_report.db")
_DB_ENC_PATH = Path("/data/ynab_report_enc.db")


def _on_connect(dbapi_connection: object, connection_record: object) -> None:
    """SQLAlchemy connect event: send PRAGMA key on every new raw connection."""
    if _db_key is None:
        return
    hex_key = _db_key.hex()
    dbapi_connection.execute(f"PRAGMA key = \"x'{hex_key}'\"")  # type: ignore[union-attr]


def set_database_key(key: bytes) -> None:
    """Store the encryption key and register the PRAGMA key event on the engine."""
    global _db_key  # noqa: PLW0603
    _db_key = key

    sync_engine = engine.sync_engine

    # Remove existing listener if present, then re-add to avoid duplicates.
    if event.contains(sync_engine, "connect", _on_connect):
        event.remove(sync_engine, "connect", _on_connect)
    event.listen(sync_engine, "connect", _on_connect)


def _migrate_sync(key: bytes) -> None:
    """Synchronous migration logic — intended to run via asyncio.to_thread."""
    hex_key = key.hex()

    # Check if DB is already encrypted by trying to open with the key.
    try:
        conn = sqlcipher3.connect(str(_DB_PATH))
        conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()
        logger.info("Database is already encrypted — skipping migration")
        _SENTINEL_PATH.write_text("done")
        return
    except Exception:
        pass  # DB is plaintext — proceed with migration

    logger.info("Migrating plaintext database to SQLCipher encryption")

    conn = sqlcipher3.connect(str(_DB_PATH))
    try:
        conn.execute(
            f"ATTACH DATABASE '{_DB_ENC_PATH}' AS encrypted"
            f" KEY \"x'{hex_key}'\""
        )
        conn.execute("SELECT sqlcipher_export('encrypted')")
        conn.execute("DETACH DATABASE encrypted")
    except Exception:
        conn.close()
        raise
    conn.close()

    _DB_ENC_PATH.replace(_DB_PATH)
    _SENTINEL_PATH.write_text("done")
    logger.info("Plaintext-to-encrypted migration completed successfully")


async def migrate_plaintext_to_encrypted(key: bytes) -> None:
    """
    One-time migration: convert an existing plaintext SQLite DB to SQLCipher.

    Idempotent — skips if the sentinel file exists, the DB is already encrypted,
    or no DB file exists yet (fresh install).
    """
    if _SENTINEL_PATH.exists():
        return

    if not _DB_PATH.exists():
        # Fresh install — create_all() will produce an encrypted DB.
        _SENTINEL_PATH.write_text("done")
        return

    try:
        await asyncio.to_thread(_migrate_sync, key)
    except Exception:
        logger.exception("Failed to migrate database to encrypted format")
        raise


async def apply_migrations() -> None:
    """
    Add new columns to existing tables without requiring Alembic.
    Called at startup before create_all(). Each ALTER TABLE is attempted
    and silently ignored if the column already exists (SQLite behaviour).

    Also performs one-time table mutations (drop user_profile — Phase 12).
    """
    _new_columns = [
        ("app_settings", "schedule_enabled",             "BOOLEAN NOT NULL DEFAULT 0"),
        ("app_settings", "schedule_frequency",           "VARCHAR(16)"),
        ("app_settings", "schedule_day_of_month",        "INTEGER"),
        ("app_settings", "schedule_day_of_week",         "VARCHAR(3)"),
        ("app_settings", "schedule_month",               "INTEGER"),
        ("app_settings", "schedule_report_target",       "VARCHAR(16) NOT NULL DEFAULT 'previous_month'"),
        ("app_settings", "schedule_send_email",          "BOOLEAN NOT NULL DEFAULT 0"),
        ("app_settings", "ynab_budget_name",             "VARCHAR(256)"),
        ("app_settings", "life_context_pre_prompt_enc",          "BLOB"),
        # Phase 14
        ("app_settings", "custom_css_enc",                       "BLOB"),
        ("app_settings", "projection_expected_return_rate",      "REAL"),
        ("app_settings", "projection_retirement_target",         "INTEGER"),
    ]
    # Block 1: ALTER TABLE column additions + DROP TABLE
    # Uses try/except per statement — caught exceptions can deactivate the
    # async connection, so this block must be separate from Block 2.
    async with engine.begin() as conn:
        for table, col, definition in _new_columns:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
            except Exception:
                pass  # Column already exists — ignore

        # Phase 12: drop the user_profile table (replaced by life context chat)
        try:
            await conn.execute(text("DROP TABLE IF EXISTS user_profile"))
        except Exception:
            pass

    # Block 2: CREATE TABLE IF NOT EXISTS + seeding (fresh connection so prior
    # caught exceptions in Block 1 cannot contaminate this transaction).
    async with engine.begin() as conn:
        # Phase 14: create dashboard tables if not yet present, then seed default
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dashboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                is_default BOOLEAN NOT NULL DEFAULT 0,
                grid_columns INTEGER NOT NULL DEFAULT 12,
                default_time_period VARCHAR(32),
                custom_css TEXT,
                created_at VARCHAR(32) NOT NULL,
                updated_at VARCHAR(32) NOT NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS dashboard_widget (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dashboard_id INTEGER NOT NULL REFERENCES dashboard(id),
                widget_type VARCHAR(64) NOT NULL,
                grid_x INTEGER NOT NULL DEFAULT 0,
                grid_y INTEGER NOT NULL DEFAULT 0,
                grid_w INTEGER NOT NULL DEFAULT 4,
                grid_h INTEGER NOT NULL DEFAULT 3,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at VARCHAR(32) NOT NULL,
                updated_at VARCHAR(32) NOT NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS net_worth_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                budget_id VARCHAR(64) NOT NULL,
                snapped_at VARCHAR(10) NOT NULL,
                ynab_balance_milliunits INTEGER NOT NULL
            )
        """))
        # Seed a default dashboard on Phase 14 first-run if none exist
        _now = _dt.now(_tz.utc).isoformat()
        _count_result = await conn.execute(text("SELECT COUNT(*) FROM dashboard"))
        _count = _count_result.scalar()
        if _count == 0:
            await conn.execute(text(
                "INSERT INTO dashboard (name, description, is_default, grid_columns, "
                "default_time_period, custom_css, created_at, updated_at) "
                "VALUES ('Default Dashboard', 'Auto-created on Phase 14 upgrade', 1, 12, "
                "'last_12_months', NULL, :now, :now)"
            ), {"now": _now})
            _id_result = await conn.execute(text("SELECT last_insert_rowid()"))
            _dash_id = _id_result.scalar()
            _default_widgets = [
                ("income_card",           0,  0, 4, 3),
                ("spending_card",         4,  0, 4, 3),
                ("net_savings_card",      8,  0, 4, 3),
                ("net_worth_card",        0,  3, 4, 3),
                ("income_spending_trend", 0,  6, 12, 5),
                ("category_breakdown",    0, 11, 12, 6),
            ]
            for _wt, _gx, _gy, _gw, _gh in _default_widgets:
                await conn.execute(text(
                    "INSERT INTO dashboard_widget (dashboard_id, widget_type, grid_x, grid_y, "
                    "grid_w, grid_h, config_json, created_at, updated_at) "
                    "VALUES (:did, :wt, :gx, :gy, :gw, :gh, '{}', :now, :now)"
                ), {"did": _dash_id, "wt": _wt, "gx": _gx, "gy": _gy, "gw": _gw, "gh": _gh, "now": _now})


async def create_all() -> None:
    """Create all database tables. Called during app lifespan startup."""
    import app.models.life_context  # noqa: F401 — registers LifeContextSession/Block with Base
    import app.models.import_data   # noqa: F401 — registers InstitutionProfile/ImportSession/ExternalAccount/ExternalTransaction/ExternalBalance with Base
    import app.models.dashboard     # noqa: F401 — registers Dashboard/DashboardWidget/NetWorthSnapshot with Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
