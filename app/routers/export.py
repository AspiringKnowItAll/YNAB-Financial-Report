"""
Export routes — download report snapshots as HTML or PDF.

GET /export/{id}/html   → Standalone interactive HTML file download
GET /export/{id}/pdf    → PDF file download via WeasyPrint
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.budget import Budget
from app.models.report import ReportSnapshot
from app.services.export_service import render_html, render_pdf

router = APIRouter(tags=["export"])


async def _get_snapshot_and_budget(
    report_id: int,
    db: AsyncSession,
) -> tuple[ReportSnapshot, str]:
    """Fetch snapshot + budget name, or raise 404."""
    result = await db.execute(
        select(ReportSnapshot).where(ReportSnapshot.id == report_id)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Report not found")

    result = await db.execute(select(Budget).where(Budget.id == snapshot.budget_id))
    budget = result.scalar_one_or_none()
    budget_name = budget.name if budget else "Your Budget"

    return snapshot, budget_name


@router.get("/export/{report_id}/html")
async def export_html(report_id: int, db: AsyncSession = Depends(get_db)):
    """Download report as a standalone interactive HTML file."""
    snapshot, budget_name = await _get_snapshot_and_budget(report_id, db)
    html = await render_html(snapshot, budget_name)
    filename = f"report-{snapshot.month}.html"
    safe_filename = quote(filename, safe="")
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"},
    )


@router.get("/export/{report_id}/pdf")
async def export_pdf(report_id: int, db: AsyncSession = Depends(get_db)):
    """Download report as a PDF file."""
    snapshot, budget_name = await _get_snapshot_and_budget(report_id, db)
    pdf_bytes = await render_pdf(snapshot, budget_name)
    filename = f"report-{snapshot.month}.pdf"
    safe_filename = quote(filename, safe="")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"},
    )
