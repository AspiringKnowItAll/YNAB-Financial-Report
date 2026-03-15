"""
Report assembly service.

Loads transaction and category data from the database, runs analysis,
calls the AI provider for commentary, and persists a ReportSnapshot.

Implemented in Phase 6.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import ReportSnapshot
from app.models.settings import AppSettings
from app.models.user_profile import UserProfile


async def generate_report(
    db: AsyncSession,
    settings: AppSettings,
    profile: UserProfile,
    master_key: bytes,
    budget_id: str,
    month: str,
) -> ReportSnapshot:
    """
    Assemble report data, run outlier detection, generate AI commentary,
    build Plotly chart JSON, and persist a ReportSnapshot row.

    Args:
        db: Async SQLAlchemy session.
        settings: AppSettings singleton (id=1).
        profile: UserProfile singleton (id=1).
        master_key: From app.state.master_key.
        budget_id: YNAB budget UUID.
        month: Target month in YYYY-MM format.

    Returns:
        The persisted ReportSnapshot ORM row.
    """
    raise NotImplementedError


async def get_report(db: AsyncSession, report_id: int) -> ReportSnapshot | None:
    """Fetch a single report snapshot by ID."""
    raise NotImplementedError


async def list_reports(
    db: AsyncSession, budget_id: str, limit: int = 24
) -> list[ReportSnapshot]:
    """List the most recent N report snapshots for a budget."""
    raise NotImplementedError
