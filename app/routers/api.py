"""
Internal API routes — machine-readable endpoints for triggering actions
and checking integration health from the Settings UI.

POST /api/sync/trigger           → Manually trigger a YNAB sync
POST /api/report/generate        → Manually trigger report generation for a month
POST /api/report/email/{id}      → Email a report snapshot via SMTP
POST /api/test/ynab              → Test YNAB API connectivity
POST /api/test/ai                → Test AI provider connectivity
POST /api/test/smtp              → Test SMTP connectivity
POST /api/test/smtp/send         → Test SMTP by sending a real email to report_to_email

Phases 3–8.
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
    """
    Verify the YNAB API key and return the list of accessible budgets.

    Accepts the API key directly from the form so the user can test
    before saving settings. Falls back to the previously-saved key if
    the form field is left blank.
    """
    form = await request.form()
    api_key = (form.get("ynab_api_key") or "").strip()

    # If no key was typed, fall back to the saved (encrypted) key
    if not api_key:
        settings = await _get_settings(db)
        if settings and settings.ynab_api_key_enc:
            master_key = request.app.state.master_key
            try:
                api_key = decrypt(settings.ynab_api_key_enc, master_key)
            except ValueError as exc:
                return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    if not api_key:
        return JSONResponse(
            {"status": "error", "message": "Enter a YNAB personal access token first."},
            status_code=400,
        )

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
    """
    Verify SMTP connectivity by connecting and authenticating (no email sent).

    Accepts SMTP fields directly from the form so the user can test
    before saving settings. Falls back to saved values for any field
    left blank.
    """
    form = await request.form()
    settings = await _get_settings(db)
    master_key = request.app.state.master_key

    # Read from form, fall back to saved settings
    smtp_host = (form.get("smtp_host") or "").strip() or (settings.smtp_host if settings else None)
    smtp_port_raw = (form.get("smtp_port") or "").strip()
    smtp_port = int(smtp_port_raw) if smtp_port_raw else (settings.smtp_port if settings else 587)
    smtp_username = (form.get("smtp_username") or "").strip() or (settings.smtp_username if settings else None)
    # Use 'is not None' so an explicitly-sent empty string (unchecked checkbox)
    # is treated as False rather than falling back to the saved DB value.
    tls_raw = form.get("smtp_use_tls")
    smtp_use_tls = (tls_raw == "1") if tls_raw is not None else (settings.smtp_use_tls if settings else True)

    # Password: form field first, then saved encrypted value
    smtp_password: str | None = (form.get("smtp_password") or "").strip() or None
    if not smtp_password and settings and settings.smtp_password_enc:
        try:
            smtp_password = decrypt(settings.smtp_password_enc, master_key)
        except ValueError as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    if not smtp_host:
        return JSONResponse(
            {"status": "error", "message": "Enter an SMTP host first."},
            status_code=400,
        )

    try:
        import aiosmtplib
        # Port 465 = implicit TLS; port 587 (or other) = STARTTLS when TLS enabled.
        use_implicit_tls = smtp_use_tls and smtp_port == 465

        smtp = aiosmtplib.SMTP(
            hostname=smtp_host,
            port=smtp_port,
            use_tls=use_implicit_tls,
        )
        await smtp.connect()
        try:
            if smtp_use_tls and not use_implicit_tls:
                await smtp.starttls()
            if smtp_username:
                await smtp.login(smtp_username, smtp_password or "")
        finally:
            await smtp.quit()

        return JSONResponse({
            "status": "success",
            "message": f"Connected to {smtp_host}:{smtp_port} successfully.",
        })
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"SMTP connection failed: {exc}"},
            status_code=502,
        )


# ---------------------------------------------------------------------------
# SMTP test send
# ---------------------------------------------------------------------------

@router.post("/test/smtp/send")
async def test_smtp_send(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Verify SMTP by sending a real test email to report_to_email.

    Accepts SMTP fields directly from the form so the user can test before
    saving. Falls back to saved values for any field left blank.
    """
    from email.mime.text import MIMEText
    import aiosmtplib

    form = await request.form()
    settings = await _get_settings(db)
    master_key = request.app.state.master_key

    smtp_host = (form.get("smtp_host") or "").strip() or (settings.smtp_host if settings else None)
    smtp_port_raw = (form.get("smtp_port") or "").strip()
    smtp_port = int(smtp_port_raw) if smtp_port_raw else (settings.smtp_port if settings else 587)
    smtp_username = (form.get("smtp_username") or "").strip() or (settings.smtp_username if settings else None)
    tls_raw = form.get("smtp_use_tls")
    smtp_use_tls = (tls_raw == "1") if tls_raw is not None else (settings.smtp_use_tls if settings else True)
    smtp_from_email = (form.get("smtp_from_email") or "").strip() or (settings.smtp_from_email if settings else None)
    report_to_email = (form.get("report_to_email") or "").strip() or (settings.report_to_email if settings else None)

    smtp_password: str | None = (form.get("smtp_password") or "").strip() or None
    if not smtp_password and settings and settings.smtp_password_enc:
        try:
            smtp_password = decrypt(settings.smtp_password_enc, master_key)
        except ValueError as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    missing = []
    if not smtp_host:
        missing.append("SMTP host")
    if not smtp_from_email:
        missing.append("From address")
    if not report_to_email:
        missing.append("Send reports to")
    if missing:
        return JSONResponse(
            {"status": "error", "message": f"Configure these fields first: {', '.join(missing)}."},
            status_code=400,
        )

    try:
        msg = MIMEText(
            "This is a test email from YNAB Financial Report.\n\n"
            "If you received this, your SMTP settings are configured correctly.",
            "plain",
            "utf-8",
        )
        # report_to_email may be comma-separated; build explicit recipient list.
        recipients = [a.strip() for a in (report_to_email or "").split(",") if a.strip()]

        msg["Subject"] = "YNAB Financial Report — SMTP test"
        msg["From"] = smtp_from_email
        msg["To"] = ", ".join(recipients)

        use_implicit_tls = smtp_use_tls and smtp_port == 465

        smtp = aiosmtplib.SMTP(
            hostname=smtp_host,
            port=smtp_port,
            use_tls=use_implicit_tls,
        )
        await smtp.connect()
        try:
            if smtp_use_tls and not use_implicit_tls:
                await smtp.starttls()
            if smtp_username:
                await smtp.login(smtp_username, smtp_password or "")
            await smtp.send_message(msg, recipients=recipients)
        finally:
            await smtp.quit()

        return JSONResponse({
            "status": "success",
            "message": f"Test email sent to {', '.join(recipients)}.",
        })
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "message": f"SMTP send failed: {exc}"},
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
