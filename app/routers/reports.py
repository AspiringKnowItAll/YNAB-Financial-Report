"""
Reports routes — list and view monthly financial reports.

GET /reports          → List all report snapshots
GET /reports/{id}     → View a single report with charts and AI commentary

Implemented in Phase 6.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["reports"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/reports", response_class=HTMLResponse)
async def list_reports(request: Request):
    return templates.TemplateResponse("placeholder.html", {
        "request": request,
        "title": "Reports",
        "message": "Reports coming in Phase 6.",
    })


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def get_report(request: Request, report_id: int):
    return templates.TemplateResponse("placeholder.html", {
        "request": request,
        "title": f"Report #{report_id}",
        "message": "Report detail view coming in Phase 6.",
    })
