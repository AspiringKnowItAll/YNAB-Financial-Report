"""
Dashboard route — the app's main landing page after setup.

GET /   → Render the financial dashboard with recent summary charts.

Implemented in Phase 5.
"""

from fastapi import APIRouter

router = APIRouter(tags=["dashboard"])


@router.get("/")
async def get_dashboard():
    raise NotImplementedError
