"""
Export routes — download report snapshots as HTML or PDF.

GET /export/{id}/html   → Stream rendered HTML
GET /export/{id}/pdf    → Stream PDF download

Implemented in Phase 7.
"""

from fastapi import APIRouter

router = APIRouter(tags=["export"])


@router.get("/export/{report_id}/html")
async def export_html(report_id: int):
    raise NotImplementedError


@router.get("/export/{report_id}/pdf")
async def export_pdf(report_id: int):
    raise NotImplementedError
