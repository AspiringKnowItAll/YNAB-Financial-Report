"""
Settings routes — manage YNAB, AI, email, and Notion configuration.

GET  /settings   → Render settings page (secrets shown as ●●●●●●●● placeholders)
POST /settings   → Save and encrypt updated settings

All inputs validated through Pydantic schemas in app/schemas/settings.py.
Secret fields are NEVER pre-populated with decrypted values in the form.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import AppSettings
from app.schemas.settings import (
    AiSettingsUpdate,
    NotionSettingsUpdate,
    SmtpSettingsUpdate,
    YnabSettingsUpdate,
)
from app.services.encryption import decrypt, encrypt

router = APIRouter(tags=["settings"])
templates = Jinja2Templates(directory="app/templates")


async def _get_or_create_settings(db: AsyncSession) -> AppSettings:
    """Return the singleton AppSettings row (id=1), creating it if absent."""
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = AppSettings(id=1)
        db.add(settings)
        await db.flush()
    return settings


@router.get("/settings", response_class=HTMLResponse)
async def get_settings(request: Request, db: AsyncSession = Depends(get_db)):
    settings = await _get_or_create_settings(db)
    # Build a context dict with only non-secret values; secrets are indicated
    # by a boolean flag so the template can show a placeholder.
    context = {
        "request": request,
        "settings": settings,
        "has_ynab_key": bool(settings.ynab_api_key_enc),
        "has_ai_key": bool(settings.ai_api_key_enc),
        "has_smtp_password": bool(settings.smtp_password_enc),
        "has_notion_token": bool(settings.notion_token_enc),
        "saved": request.query_params.get("saved") == "1",
    }
    return templates.TemplateResponse("settings/settings.html", context)


@router.post("/settings", response_class=HTMLResponse)
async def post_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    # YNAB
    ynab_api_key: str = Form(default=""),
    ynab_budget_id: str = Form(default=""),
    # AI
    ai_provider: str = Form(default=""),
    ai_model: str = Form(default=""),
    ai_api_key: str = Form(default=""),
    ai_base_url: str = Form(default=""),
    # SMTP
    email_enabled: str = Form(default=""),
    smtp_host: str = Form(default=""),
    smtp_port: str = Form(default="587"),
    smtp_username: str = Form(default=""),
    smtp_password: str = Form(default=""),
    smtp_use_tls: str = Form(default=""),
    smtp_from_email: str = Form(default=""),
    report_to_email: str = Form(default=""),
    # Notion
    notion_enabled: str = Form(default=""),
    notion_token: str = Form(default=""),
    notion_database_id: str = Form(default=""),
):
    master_key = request.app.state.master_key
    settings = await _get_or_create_settings(db)
    errors: list[str] = []

    # --- YNAB ---
    if ynab_api_key.strip() or ynab_budget_id.strip():
        try:
            ynab = YnabSettingsUpdate(
                ynab_api_key=ynab_api_key,
                ynab_budget_id=ynab_budget_id,
            )
            settings.ynab_api_key_enc = encrypt(ynab.ynab_api_key, master_key)
            settings.ynab_budget_id = ynab.ynab_budget_id
        except Exception as exc:
            _collect_errors(exc, errors, "YNAB")

    # --- AI ---
    if ai_provider.strip():
        try:
            ai = AiSettingsUpdate(
                ai_provider=ai_provider,
                ai_model=ai_model,
                ai_api_key=ai_api_key or None,
                ai_base_url=ai_base_url or None,
            )
            settings.ai_provider = ai.ai_provider
            settings.ai_model = ai.ai_model
            if ai.ai_api_key:
                settings.ai_api_key_enc = encrypt(ai.ai_api_key, master_key)
            settings.ai_base_url = str(ai.ai_base_url) if ai.ai_base_url else None
        except Exception as exc:
            _collect_errors(exc, errors, "AI")

    # --- SMTP ---
    if smtp_host.strip() or email_enabled:
        try:
            smtp = SmtpSettingsUpdate(
                email_enabled=bool(email_enabled),
                smtp_host=smtp_host,
                smtp_port=int(smtp_port) if smtp_port.strip() else 587,
                smtp_username=smtp_username,
                smtp_password=smtp_password or None,
                smtp_use_tls=bool(smtp_use_tls),
                smtp_from_email=smtp_from_email,
                report_to_email=report_to_email,
            )
            settings.email_enabled = smtp.email_enabled
            settings.smtp_host = smtp.smtp_host
            settings.smtp_port = smtp.smtp_port
            settings.smtp_username = smtp.smtp_username
            if smtp.smtp_password:
                settings.smtp_password_enc = encrypt(smtp.smtp_password, master_key)
            settings.smtp_use_tls = smtp.smtp_use_tls
            settings.smtp_from_email = str(smtp.smtp_from_email)
            settings.report_to_email = str(smtp.report_to_email)
        except Exception as exc:
            _collect_errors(exc, errors, "Email")

    # --- Notion ---
    if notion_token.strip() or notion_database_id.strip() or notion_enabled:
        try:
            notion = NotionSettingsUpdate(
                notion_enabled=bool(notion_enabled),
                notion_token=notion_token or None,
                notion_database_id=notion_database_id or None,
            )
            settings.notion_enabled = notion.notion_enabled
            if notion.notion_token:
                settings.notion_token_enc = encrypt(notion.notion_token, master_key)
            settings.notion_database_id = notion.notion_database_id
        except Exception as exc:
            _collect_errors(exc, errors, "Notion")

    if errors:
        context = {
            "request": request,
            "settings": settings,
            "has_ynab_key": bool(settings.ynab_api_key_enc),
            "has_ai_key": bool(settings.ai_api_key_enc),
            "has_smtp_password": bool(settings.smtp_password_enc),
            "has_notion_token": bool(settings.notion_token_enc),
            "errors": errors,
            "saved": False,
        }
        await db.rollback()
        return templates.TemplateResponse("settings/settings.html", context, status_code=422)

    # Mark settings complete if minimum required fields are present
    if settings.ynab_api_key_enc and settings.ynab_budget_id and settings.ai_provider:
        settings.settings_complete = True

    await db.commit()
    return RedirectResponse("/settings?saved=1", status_code=302)


def _collect_errors(exc: Exception, errors: list[str], section: str) -> None:
    if hasattr(exc, "errors"):
        for e in exc.errors():
            errors.append(f"{section}: {e['msg']}")
    else:
        errors.append(f"{section}: {exc}")
