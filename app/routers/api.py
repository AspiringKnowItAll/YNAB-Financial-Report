"""
Internal API routes — machine-readable endpoints for triggering actions
and checking integration health from the Settings UI.

POST /api/sync/trigger           → Manually trigger a YNAB sync
POST /api/report/generate        → Manually trigger report generation for a month
POST /api/report/email/{id}      → Email a report snapshot via SMTP
POST /api/test/ynab              → Test YNAB API connectivity
POST /api/test/ai                → Test AI provider connectivity
POST /api/test/smtp              → Test SMTP connectivity

Phases 3–8.
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
        budgets = [{"id": b.id, "name": b.name} for b in budgets_response.budgets]
        return JSONResponse({"status": "success", "budgets": budgets})
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
    """
    Verify AI provider connectivity and return available models.

    Accepts provider config directly from the form so the user can test
    before saving settings. Falls back to a previously-saved API key if
    the form field is left blank (existing key placeholder).
    """
    form = await request.form()
    provider_name = (form.get("ai_provider") or "").strip()
    api_key = (form.get("ai_api_key") or "").strip()
    base_url = (form.get("ai_base_url") or "").strip() or None

    if not provider_name:
        return JSONResponse(
            {"status": "error", "message": "Select an AI provider first."},
            status_code=400,
        )

    # If no API key was typed, fall back to the saved (encrypted) key
    if not api_key:
        settings = await _get_settings(db)
        if settings and settings.ai_api_key_enc:
            master_key = request.app.state.master_key
            try:
                api_key = decrypt(settings.ai_api_key_enc, master_key)
            except ValueError as exc:
                return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    try:
        from app.services.ai_service import get_ai_provider_from_params
        provider = get_ai_provider_from_params(provider_name, api_key, base_url)
    except ValueError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    try:
        models = await provider.list_models()
        return JSONResponse({
            "status": "success",
            "message": f"Connected to {provider_name} successfully.",
            "models": models,
        })
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"AI provider test failed: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# SMTP connection test
# ---------------------------------------------------------------------------

@router.post("/test/smtp")
async def test_smtp(request: Request, db: AsyncSession = Depends(get_db)):
    """Verify SMTP connectivity by connecting and authenticating (no email sent)."""
    settings = await _get_settings(db)

    if not settings or not settings.smtp_host:
        return JSONResponse(
            {"status": "error", "message": "SMTP host is not configured."},
            status_code=400,
        )

    master_key = request.app.state.master_key

    try:
        from app.services.email_service import test_smtp_connection
        await test_smtp_connection(settings, master_key)
        return JSONResponse({
            "status": "success",
            "message": f"Connected to {settings.smtp_host}:{settings.smtp_port} successfully.",
        })
    except RuntimeError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"SMTP connection failed: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# Email report delivery
# ---------------------------------------------------------------------------

@router.post("/report/email/{report_id}")
async def email_report(
    request: Request,
    report_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a report snapshot by email.

    Renders the email HTML body and attaches a PDF, then delivers via
    the user-configured SMTP server. Requires email_enabled=True in Settings.
    """
    from app.models.budget import Budget
    from app.models.report import ReportSnapshot
    from app.services.email_service import build_report_email_html, send_report_email
    from app.services.export_service import render_pdf

    settings = await _get_settings(db)

    if not settings:
        return JSONResponse(
            {"status": "error", "message": "Settings are not configured."},
            status_code=400,
        )
    if not settings.email_enabled:
        return JSONResponse(
            {"status": "error", "message": "Email delivery is not enabled in Settings."},
            status_code=400,
        )

    # Load snapshot
    result = await db.execute(
        select(ReportSnapshot).where(ReportSnapshot.id == report_id)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        return JSONResponse(
            {"status": "error", "message": f"Report #{report_id} does not exist."},
            status_code=404,
        )

    # Budget name
    result = await db.execute(select(Budget).where(Budget.id == snapshot.budget_id))
    budget = result.scalar_one_or_none()
    budget_name = budget.name if budget else "Your Budget"

    master_key = request.app.state.master_key

    try:
        html_body = build_report_email_html(budget_name, snapshot)
        pdf_bytes = await render_pdf(snapshot, budget_name)
        subject = f"YNAB Financial Report \u2014 {budget_name} \u2014 {snapshot.month}"
        await send_report_email(
            settings=settings,
            master_key=master_key,
            subject=subject,
            html_body=html_body,
            pdf_attachment=pdf_bytes,
        )
        return JSONResponse({"status": "success", "message": "Report emailed successfully."})
    except RuntimeError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"Email delivery failed: {exc}"},
            status_code=502,
        )
