"""
YNAB → SQLite sync pipeline.

Pulls data from the YNAB API via YnabClient and upserts it into the local
SQLite database using the ORM. Writes a SyncLog row at the start (running)
and updates it at the end (success/failed).

Implemented in Phase 3.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ynab_client import YnabClient


async def run_sync(db: AsyncSession, api_key: str, budget_id: str) -> None:
    """
    Run a full delta sync: categories, accounts, transactions.
    Inserts a SyncLog row with status="running" at start;
    updates to "success" or "failed" at end.

    Args:
        db: Async SQLAlchemy session.
        api_key: Decrypted YNAB API key (do not log).
        budget_id: YNAB budget UUID to sync.
    """
    raise NotImplementedError
