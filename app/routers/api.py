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
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["api"])


@router.post("/sync/trigger")
async def trigger_sync():
    return JSONResponse({"status": "not_implemented", "message": "YNAB sync coming in Phase 3."}, status_code=501)


@router.post("/report/generate")
async def trigger_report():
    return JSONResponse({"status": "not_implemented", "message": "Report generation coming in Phase 6."}, status_code=501)


@router.post("/test/ynab")
async def test_ynab():
    return JSONResponse({"status": "not_implemented", "message": "YNAB test coming in Phase 3."}, status_code=501)


@router.post("/test/ai")
async def test_ai():
    return JSONResponse({"status": "not_implemented", "message": "AI test coming in Phase 6."}, status_code=501)


@router.post("/test/smtp")
async def test_smtp():
    return JSONResponse({"status": "not_implemented", "message": "SMTP test coming in Phase 8."}, status_code=501)
