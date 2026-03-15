from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:////data/ynab_report.db"

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    pass


async def apply_migrations() -> None:
    """
    Add new columns to existing tables without requiring Alembic.
    Called at startup before create_all(). Each ALTER TABLE is attempted
    and silently ignored if the column already exists (SQLite behaviour).
    """
    _new_columns = [
        ("app_settings", "schedule_enabled",       "BOOLEAN NOT NULL DEFAULT 0"),
        ("app_settings", "schedule_frequency",     "VARCHAR(16)"),
        ("app_settings", "schedule_day_of_month",  "INTEGER"),
        ("app_settings", "schedule_day_of_week",   "VARCHAR(3)"),
        ("app_settings", "schedule_month",         "INTEGER"),
        ("app_settings", "schedule_report_target", "VARCHAR(16) NOT NULL DEFAULT 'previous_month'"),
        ("app_settings", "schedule_send_email",    "BOOLEAN NOT NULL DEFAULT 0"),
    ]
    async with engine.begin() as conn:
        for table, col, definition in _new_columns:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
            except Exception:
                pass  # Column already exists — ignore


async def create_all() -> None:
    """Create all database tables. Called during app lifespan startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
