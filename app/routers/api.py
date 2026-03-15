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
from app.models.user_profile import UserProfile
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


async def _get_profile(db: AsyncSession) -> UserProfile | None:
    result = await db.execute(select(UserProfile).where(UserProfile.id == 1))
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
# Report generation
# ---------------------------------------------------------------------------

@router.post("/report/generate")
async def trigger_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    month: str | None = None,
):
    """
    Generate (or regenerate) a report snapshot for a given month.

    Query parameter:
      month  YYYY-MM  The target month. Defaults to the most recent month
                      that has transaction data.

    Returns JSON with status and report_id on success.
    """
    from datetime import date

    settings = await _get_settings(db)
    if not settings or not settings.ynab_budget_id:
        return JSONResponse(
            {"status": "error", "message": "YNAB budget ID is not configured."},
            status_code=400,
        )

    profile = await _get_profile(db)
    if not profile:
        return JSONResponse(
            {"status": "error", "message": "User profile is not set up."},
            status_code=400,
        )

    # Determine target month
    if month:
        # Basic YYYY-MM validation
        parts = month.split("-")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return JSONResponse(
                {"status": "error", "message": "month must be in YYYY-MM format."},
                status_code=400,
            )
    else:
        # Default to the current calendar month
        today = date.today()
        month = f"{today.year:04d}-{today.month:02d}"

    master_key = request.app.state.master_key

    try:
        from app.services.report_service import generate_report
        snapshot = await generate_report(
            db=db,
            settings=settings,
            profile=profile,
            master_key=master_key,
            budget_id=settings.ynab_budget_id,
            month=month,
        )
        return JSONResponse({
            "status": "success",
            "report_id": snapshot.id,
            "month": snapshot.month,
        })
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"Report generation failed: {exc}"},
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
# AI provider test
# ---------------------------------------------------------------------------

@router.post("/test/ai")
async def test_ai(request: Request, db: AsyncSession = Depends(get_db)):
    """Verify the configured AI provider is reachable and the key is valid."""
    settings = await _get_settings(db)

    if not settings or not settings.ai_provider:
        return JSONResponse(
            {"status": "error", "message": "AI provider is not configured."},
            status_code=400,
        )

    master_key = request.app.state.master_key

    try:
        from app.services.ai_service import get_ai_provider
        provider = get_ai_provider(settings, master_key)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    try:
        ok = await provider.health_check()
        if ok:
            return JSONResponse({
                "status": "success",
                "message": f"Connected to {settings.ai_provider} successfully.",
            })
        return JSONResponse(
            {"status": "error", "message": "AI provider returned an unexpected response."},
            status_code=400,
        )
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"AI provider test failed: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# SMTP test (Phase 8)
# ---------------------------------------------------------------------------

@router.post("/test/smtp")
async def test_smtp():
    return JSONResponse(
        {"status": "not_implemented", "message": "SMTP test coming in Phase 8."},
        status_code=501,
    )
