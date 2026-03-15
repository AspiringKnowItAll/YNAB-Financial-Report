"""
Internal API routes — machine-readable endpoints for triggering actions
and checking integration health from the Settings UI.

POST /api/sync/trigger       → Manually trigger a YNAB sync
POST /api/report/generate    → Manually trigger report generation for a month
POST /api/test/ynab          → Test YNAB API connectivity
POST /api/test/ai            → Test AI provider connectivity
POST /api/test/smtp          → Test SMTP connectivity

Implemented in Phases 3–8 as each feature is built.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])


@router.post("/sync/trigger")
async def trigger_sync():
    raise NotImplementedError


@router.post("/report/generate")
async def trigger_report():
    raise NotImplementedError


@router.post("/test/ynab")
async def test_ynab():
    raise NotImplementedError


@router.post("/test/ai")
async def test_ai():
    raise NotImplementedError


@router.post("/test/smtp")
async def test_smtp():
    raise NotImplementedError
