"""
Reports routes — list and view monthly financial reports.

GET /reports          → List all report snapshots
GET /reports/{id}     → View a single report with charts and AI commentary

Implemented in Phase 6.
"""

from fastapi import APIRouter

router = APIRouter(tags=["reports"])


@router.get("/reports")
async def list_reports():
    raise NotImplementedError


@router.get("/reports/{report_id}")
async def get_report(report_id: int):
    raise NotImplementedError
