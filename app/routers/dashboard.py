"""
Dashboard route — the app's main landing page after setup.

GET /   → Render the financial dashboard with recent summary charts.

Implemented in Phase 5.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse("placeholder.html", {
        "request": request,
        "title": "Dashboard",
        "message": "Dashboard coming in Phase 5.",
    })
