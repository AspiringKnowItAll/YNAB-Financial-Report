"""
Profile setup wizard routes.

Multi-step wizard that collects personal context used by the AI report generator:
  - Household size
  - Income type (salary / variable / mixed)
  - Financial goals (free text)
  - Housing type (rent / own / other)
  - Additional notes (free text)

GET  /setup   → Render wizard form
POST /setup   → Save profile, set setup_complete=True, redirect to dashboard

Implemented in Phase 4.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["setup"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/setup", response_class=HTMLResponse)
async def get_setup(request: Request):
    return templates.TemplateResponse("placeholder.html", {
        "request": request,
        "title": "Profile Setup",
        "message": "Profile setup wizard coming in Phase 4.",
    })


@router.post("/setup", response_class=HTMLResponse)
async def post_setup(request: Request):
    return templates.TemplateResponse("placeholder.html", {
        "request": request,
        "title": "Profile Setup",
        "message": "Profile setup wizard coming in Phase 4.",
    })
