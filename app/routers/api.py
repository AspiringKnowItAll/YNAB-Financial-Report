"""
Internal API routes — machine-readable endpoints for triggering actions
and checking integration health from the Settings UI.

POST /api/sync/trigger       → Manually trigger a YNAB sync
POST /api/report/generate    → Manually trigger report generation for a month
POST /api/test/ynab          → Test YNAB API connectivity
POST /api/test/ai            → Test AI provider connectivity
POST /api/test/smtp          → Test SMTP connectivity

Phases 3–8 as each feature is built.
"""

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import AppSettings
from app.services.encryption import decrypt
from app.services.sync_service import run_sync
from app.services.ynab_client import YnabClient

router = APIRouter(prefix="/api", tags=["api"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_settings(db: AsyncSession) -> AppSettings | None:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# YNAB sync
# ---------------------------------------------------------------------------

@router.post("/sync/trigger")
async def trigger_sync(request: Request, db: AsyncSession = Depends(get_db)):
    """Trigger a full delta sync against the YNAB API."""
    settings = await _get_settings(db)

    if not settings or not settings.ynab_api_key_enc or not settings.ynab_budget_id:
        return JSONResponse(
            {"status": "error", "message": "YNAB API key or budget ID is not configured."},
            status_code=400,
        )

    master_key = request.app.state.master_key
    try:
        api_key = decrypt(settings.ynab_api_key_enc, master_key)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    try:
        sync_log = await run_sync(db, api_key, settings.ynab_budget_id)
        return JSONResponse({
            "status": "success",
            "transactions_added": sync_log.transactions_added,
            "transactions_updated": sync_log.transactions_updated,
            "knowledge_of_server": sync_log.knowledge_of_server,
        })
    except Exception:
        return JSONResponse(
            {"status": "error", "message": "Sync failed. Check the sync log for details."},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# YNAB connection test
# ---------------------------------------------------------------------------

@router.post("/test/ynab")
async def test_ynab(request: Request, db: AsyncSession = Depends(get_db)):
    """Verify the YNAB API key and return the list of accessible budgets."""
    settings = await _get_settings(db)

    if not settings or not settings.ynab_api_key_enc:
        return JSONResponse(
            {"status": "error", "message": "YNAB API key is not configured."},
            status_code=400,
        )

    master_key = request.app.state.master_key
    try:
        api_key = decrypt(settings.ynab_api_key_enc, master_key)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    try:
        client = YnabClient(api_key)
        budgets_response = await client.get_budgets()
        budget_names = [b.name for b in budgets_response.budgets]
        return JSONResponse({"status": "success", "budgets": budget_names})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            return JSONResponse(
                {"status": "error", "message": "Invalid YNAB API key — authentication failed."},
                status_code=400,
            )
        return JSONResponse(
            {"status": "error", "message": f"YNAB API returned HTTP {exc.response.status_code}."},
            status_code=400,
        )
    except httpx.RequestError:
        return JSONResponse(
            {"status": "error", "message": "Could not reach the YNAB API. Check your network connection."},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# Stubs for later phases
# ---------------------------------------------------------------------------

@router.post("/report/generate")
async def trigger_report():
    return JSONResponse(
        {"status": "not_implemented", "message": "Report generation coming in Phase 6."},
        status_code=501,
    )


@router.post("/test/ai")
async def test_ai():
    return JSONResponse(
        {"status": "not_implemented", "message": "AI test coming in Phase 6."},
        status_code=501,
    )


@router.post("/test/smtp")
async def test_smtp():
    return JSONResponse(
        {"status": "not_implemented", "message": "SMTP test coming in Phase 8."},
        status_code=501,
    )
