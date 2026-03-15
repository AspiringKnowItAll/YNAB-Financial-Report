"""
Reports routes — list and view monthly financial reports.

GET /reports          → List all report snapshots
GET /reports/{id}     → View a single report with charts and AI commentary
"""

import json

import bleach
import markdown
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.budget import Budget
from app.models.settings import AppSettings
from app.services.report_service import get_report, list_reports

router = APIRouter(tags=["reports"])
templates = Jinja2Templates(directory="app/templates")

# HTML tags and attributes allowed in AI-generated commentary
_ALLOWED_TAGS = [
    "p", "br", "strong", "em", "b", "i", "ul", "ol", "li",
    "blockquote", "code", "pre", "h1", "h2", "h3", "h4",
]
_ALLOWED_ATTRS: dict = {}


def _render_commentary(raw_markdown: str) -> str:
    """Convert AI-generated markdown to sanitized HTML."""
    html = markdown.markdown(raw_markdown, extensions=["nl2br"])
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)


# ---------------------------------------------------------------------------
# GET /reports — list
# ---------------------------------------------------------------------------

@router.get("/reports", response_class=HTMLResponse)
async def list_reports_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    budget_id: str | None = settings.ynab_budget_id if settings else None

    budget_name = "Your Budget"
    if budget_id:
        result = await db.execute(select(Budget).where(Budget.id == budget_id))
        budget = result.scalar_one_or_none()
        if budget:
            budget_name = budget.name

    reports = []
    if budget_id:
        reports = await list_reports(db, budget_id)

    return templates.TemplateResponse(request, "reports/reports_list.html", {
        "budget_name": budget_name,
        "budget_id": budget_id,
        "reports": reports,
        "ai_configured": bool(settings and settings.ai_provider),
    })


# ---------------------------------------------------------------------------
# GET /reports/{report_id} — detail
# ---------------------------------------------------------------------------

@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def get_report_page(request: Request, report_id: int, db: AsyncSession = Depends(get_db)):
    snapshot = await get_report(db, report_id)
    if snapshot is None:
        return templates.TemplateResponse(request, "placeholder.html", {
            "title": "Report Not Found",
            "message": f"Report #{report_id} does not exist.",
        }, status_code=404)

    # Parse stored chart data
    trend_chart_json: str | None = None
    category_chart_json: str | None = None
    if snapshot.chart_data:
        try:
            chart_data = json.loads(snapshot.chart_data)
            trend_chart_json = chart_data.get("trend")
            category_chart_json = chart_data.get("category")
        except (json.JSONDecodeError, AttributeError):
            pass

    # Parse outliers
    outliers: list = []
    if snapshot.outliers_excluded:
        try:
            outliers = json.loads(snapshot.outliers_excluded)
        except json.JSONDecodeError:
            pass

    # Render AI commentary as sanitized HTML
    commentary_html: str | None = None
    if snapshot.ai_commentary:
        commentary_html = _render_commentary(snapshot.ai_commentary)

    # Budget name
    result = await db.execute(select(Budget).where(Budget.id == snapshot.budget_id))
    budget = result.scalar_one_or_none()
    budget_name = budget.name if budget else "Your Budget"

    # Email configured: enabled + host + both addresses present
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    email_configured = bool(
        settings
        and settings.email_enabled
        and settings.smtp_host
        and settings.smtp_from_email
        and settings.report_to_email
    )

    return templates.TemplateResponse(request, "reports/report_detail.html", {
        "snapshot": snapshot,
        "budget_name": budget_name,
        "trend_chart_json": trend_chart_json,
        "category_chart_json": category_chart_json,
        "outliers": outliers,
        "commentary_html": commentary_html,
        "email_configured": email_configured,
    })
