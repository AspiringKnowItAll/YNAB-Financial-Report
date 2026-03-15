"""
Export routes — download report snapshots as HTML or PDF.

GET /export/{id}/html   → Stream rendered HTML
GET /export/{id}/pdf    → Stream PDF download

Implemented in Phase 7.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["export"])


@router.get("/export/{report_id}/html")
async def export_html(report_id: int):
    return JSONResponse({"status": "not_implemented", "message": "HTML export coming in Phase 7."}, status_code=501)


@router.get("/export/{report_id}/pdf")
async def export_pdf(report_id: int):
    return JSONResponse({"status": "not_implemented", "message": "PDF export coming in Phase 7."}, status_code=501)
