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

from fastapi import APIRouter

router = APIRouter(tags=["setup"])


@router.get("/setup")
async def get_setup():
    raise NotImplementedError


@router.post("/setup")
async def post_setup():
    raise NotImplementedError
