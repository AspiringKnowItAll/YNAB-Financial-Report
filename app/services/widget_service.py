"""
Widget data service — Phase 14.

Dispatches widget data queries based on widget_type and config_json.
Fully implemented in Milestone 3. This stub returns placeholder data
so the dashboard shell renders without errors.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import DashboardWidget
from app.models.settings import AppSettings

logger = logging.getLogger(__name__)


async def get_widget_data(
    widget: DashboardWidget,
    db: AsyncSession,
    settings: AppSettings | None,
) -> dict:
    """Return live data for a single widget. Stub implementation for M1."""
    return {
        "widget_id": widget.id,
        "widget_type": widget.widget_type,
        "status": "pending_implementation",
        "data": None,
    }
