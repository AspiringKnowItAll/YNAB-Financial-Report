"""
Settings routes — manage YNAB, AI, email, and Notion configuration.

GET  /settings   → Render settings page (secrets shown as ●●●●●●●● placeholders)
POST /settings   → Save and encrypt updated settings

All inputs validated through Pydantic schemas in app/schemas/settings.py.
Secret fields are NEVER pre-populated with decrypted values in the form.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import AppSettings
from app.schemas.settings import (
    AiSettingsUpdate,
    AppearanceSettingsUpdate,
    LifeContextSettingsUpdate,
    NotionSettingsUpdate,
    ProjectionSettingsUpdate,
    ScheduleSettingsUpdate,
    SmtpSettingsUpdate,
    YnabSettingsUpdate,
)
from app.services.encryption import decrypt, encrypt
from app.services.settings_service import get_global_custom_css

from app.templates_config import templates

router = APIRouter(tags=["settings"])


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
    from app.services.life_context_service import DEFAULT_PRE_PROMPT
    settings = await _get_or_create_settings(db)
    master_key = request.app.state.master_key

    # Decrypt the current pre-prompt override so the user can read and edit it.
    # Falls back to empty string if none is set (template shows the default instead).
    life_context_pre_prompt_value = ""
    if settings.life_context_pre_prompt_enc:
        try:
            life_context_pre_prompt_value = decrypt(settings.life_context_pre_prompt_enc, master_key)
        except Exception:
            life_context_pre_prompt_value = ""

    global_custom_css_value = await get_global_custom_css(db, master_key) or ""

    context = {
        "settings": settings,
        "has_ynab_key": bool(settings.ynab_api_key_enc),
        "has_ai_key": bool(settings.ai_api_key_enc),
        "has_smtp_password": bool(settings.smtp_password_enc),
        "has_notion_token": bool(settings.notion_token_enc),
        "has_life_context_pre_prompt": bool(settings.life_context_pre_prompt_enc),
        "life_context_pre_prompt_value": life_context_pre_prompt_value,
        "life_context_pre_prompt_default": DEFAULT_PRE_PROMPT,
        "global_custom_css_value": global_custom_css_value,
        "global_custom_css": "",
        "saved": request.query_params.get("saved") == "1",
        "current_page": "settings",
    }
    return templates.TemplateResponse(request, "settings/settings.html", context)


@router.post("/settings", response_class=HTMLResponse)
async def post_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    # YNAB
    ynab_api_key: str = Form(default=""),
    ynab_budget_id: str = Form(default=""),
    ynab_budget_name: str = Form(default=""),
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
    # Scheduler
    schedule_enabled: str = Form(default=""),
    schedule_frequency: str = Form(default=""),
    schedule_day_of_month: str = Form(default=""),
    schedule_day_of_week: str = Form(default=""),
    schedule_month: str = Form(default=""),
    schedule_report_target: str = Form(default="previous_month"),
    schedule_send_email: str = Form(default=""),
    # Life context
    life_context_pre_prompt: str = Form(default=""),
    # Financial projections
    projection_expected_return_rate: str = Form(default=""),
    projection_retirement_target: str = Form(default=""),
    # Appearance
    custom_css_global: str = Form(default=""),
):
    master_key = request.app.state.master_key
    settings = await _get_or_create_settings(db)
    errors: list[str] = []

    # --- YNAB ---
    # API key and budget are saved independently so that re-entering the key
    # is not required when only selecting a different budget (and vice versa).
    if ynab_api_key.strip():
        try:
            ynab = YnabSettingsUpdate(
                ynab_api_key=ynab_api_key,
                ynab_budget_id=ynab_budget_id or "placeholder",
            )
            settings.ynab_api_key_enc = encrypt(ynab.ynab_api_key, master_key)
        except Exception as exc:
            _collect_errors(exc, errors, "YNAB")

    if ynab_budget_id.strip():
        bid = ynab_budget_id.strip()[:64]
        settings.ynab_budget_id = bid
        if ynab_budget_name.strip():
            settings.ynab_budget_name = ynab_budget_name.strip()[:256]

    # --- AI ---
    if ai_provider.strip():
        try:
            ai = AiSettingsUpdate(
                ai_provider=ai_provider,
                ai_model=ai_model.strip() or None,
                ai_api_key=ai_api_key or None,
                ai_base_url=ai_base_url or None,
            )
            settings.ai_provider = ai.ai_provider
            if ai.ai_model:
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
                email_enabled=(email_enabled == "1"),
                smtp_host=smtp_host,
                smtp_port=int(smtp_port) if smtp_port.strip() else 587,
                smtp_username=smtp_username,
                smtp_password=smtp_password or None,
                smtp_use_tls=(smtp_use_tls == "1"),
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
                notion_enabled=(notion_enabled == "1"),
                notion_token=notion_token or None,
                notion_database_id=notion_database_id or None,
            )
            settings.notion_enabled = notion.notion_enabled
            if notion.notion_token:
                settings.notion_token_enc = encrypt(notion.notion_token, master_key)
            settings.notion_database_id = notion.notion_database_id
        except Exception as exc:
            _collect_errors(exc, errors, "Notion")

    # --- Scheduler ---
    try:
        sched = ScheduleSettingsUpdate(
            schedule_enabled=(schedule_enabled == "1"),
            schedule_frequency=schedule_frequency or None,
            schedule_day_of_month=int(schedule_day_of_month) if schedule_day_of_month.strip() else None,
            schedule_day_of_week=schedule_day_of_week or None,
            schedule_month=int(schedule_month) if schedule_month.strip() else None,
            schedule_report_target=schedule_report_target or "previous_month",
            schedule_send_email=(schedule_send_email == "1"),
        )
        settings.schedule_enabled = sched.schedule_enabled
        settings.schedule_frequency = sched.schedule_frequency
        settings.schedule_day_of_month = sched.schedule_day_of_month
        settings.schedule_day_of_week = sched.schedule_day_of_week
        settings.schedule_month = sched.schedule_month
        settings.schedule_report_target = sched.schedule_report_target
        settings.schedule_send_email = sched.schedule_send_email
    except Exception as exc:
        _collect_errors(exc, errors, "Scheduler")

    # --- Life Context pre-prompt ---
    if life_context_pre_prompt.strip():
        try:
            lc = LifeContextSettingsUpdate(life_context_pre_prompt=life_context_pre_prompt)
            if lc.life_context_pre_prompt:
                settings.life_context_pre_prompt_enc = encrypt(lc.life_context_pre_prompt, master_key)
        except Exception as exc:
            _collect_errors(exc, errors, "Life Context")
    elif not life_context_pre_prompt.strip():
        # Explicit empty string → clear the override (use default pre-prompt)
        settings.life_context_pre_prompt_enc = None

    # --- Financial Projections ---
    try:
        proj = ProjectionSettingsUpdate(
            projection_expected_return_rate_pct=projection_expected_return_rate or None,
            projection_retirement_target_dollars=projection_retirement_target or None,
        )
        if proj.projection_expected_return_rate_pct is not None:
            settings.projection_expected_return_rate = proj.projection_expected_return_rate_pct / 100.0
        elif not projection_expected_return_rate.strip():
            settings.projection_expected_return_rate = None
        if proj.projection_retirement_target_dollars is not None:
            settings.projection_retirement_target = int(proj.projection_retirement_target_dollars * 1000)
        elif not projection_retirement_target.strip():
            settings.projection_retirement_target = None
    except Exception as exc:
        _collect_errors(exc, errors, "Financial Projections")

    # --- Appearance (Global Custom CSS) ---
    try:
        appearance = AppearanceSettingsUpdate(custom_css_global=custom_css_global or None)
        if appearance.custom_css_global:
            settings.custom_css_enc = encrypt(appearance.custom_css_global, master_key)
        else:
            # Empty string → clear the CSS
            settings.custom_css_enc = None
    except Exception as exc:
        _collect_errors(exc, errors, "Appearance")

    if errors:
        # Snapshot the boolean flags before rollback expires the ORM object.
        has_ynab_key = bool(settings.ynab_api_key_enc)
        has_ai_key = bool(settings.ai_api_key_enc)
        has_smtp_password = bool(settings.smtp_password_enc)
        has_notion_token = bool(settings.notion_token_enc)
        await db.rollback()
        # Re-fetch settings so the template has a fully-loaded, non-expired object.
        settings = await _get_or_create_settings(db)
        from app.services.life_context_service import DEFAULT_PRE_PROMPT
        lc_error_value = ""
        if settings.life_context_pre_prompt_enc:
            try:
                lc_error_value = decrypt(settings.life_context_pre_prompt_enc, master_key)
            except Exception:
                lc_error_value = ""
        context = {
            "settings": settings,
            "has_ynab_key": has_ynab_key,
            "has_ai_key": has_ai_key,
            "has_smtp_password": has_smtp_password,
            "has_notion_token": has_notion_token,
            "has_life_context_pre_prompt": bool(settings.life_context_pre_prompt_enc),
            "life_context_pre_prompt_value": lc_error_value,
            "life_context_pre_prompt_default": DEFAULT_PRE_PROMPT,
            "global_custom_css_value": custom_css_global,
            "global_custom_css": "",
            "errors": errors,
            "saved": False,
            "current_page": "settings",
        }
        return templates.TemplateResponse(request, "settings/settings.html", context, status_code=422)

    # Mark settings complete if minimum required fields are present
    if (settings.ynab_api_key_enc and settings.ynab_budget_id
            and settings.ai_provider and settings.ai_model):
        settings.settings_complete = True

    await db.commit()

    # Apply schedule changes immediately (no restart required)
    from app.scheduler import reschedule_job
    reschedule_job(settings, request.app)

    # If settings are still incomplete, show the page with a warning listing
    # exactly which required fields are missing (instead of a silent redirect loop).
    if not settings.settings_complete:
        missing = _missing_requirements(settings)
        css_value = await get_global_custom_css(db, master_key) or ""
        lc_value = ""
        if settings.life_context_pre_prompt_enc:
            try:
                lc_value = decrypt(settings.life_context_pre_prompt_enc, master_key)
            except Exception:
                lc_value = ""
        from app.services.life_context_service import DEFAULT_PRE_PROMPT
        context = {
            "settings": settings,
            "has_ynab_key": bool(settings.ynab_api_key_enc),
            "has_ai_key": bool(settings.ai_api_key_enc),
            "has_smtp_password": bool(settings.smtp_password_enc),
            "has_notion_token": bool(settings.notion_token_enc),
            "has_life_context_pre_prompt": bool(settings.life_context_pre_prompt_enc),
            "life_context_pre_prompt_value": lc_value,
            "life_context_pre_prompt_default": DEFAULT_PRE_PROMPT,
            "saved": True,
            "missing": missing,
            "current_page": "settings",
            "global_custom_css_value": css_value,
            "global_custom_css": "",
        }
        return templates.TemplateResponse(request, "settings/settings.html", context)

    return RedirectResponse("/settings?saved=1", status_code=302)


def _missing_requirements(settings: AppSettings) -> list[str]:
    """Return human-readable names of required settings that are still empty."""
    missing: list[str] = []
    if not settings.ynab_api_key_enc:
        missing.append("YNAB personal access token")
    if not settings.ynab_budget_id:
        missing.append("YNAB budget selection")
    if not settings.ai_provider:
        missing.append("AI provider")
    if not settings.ai_model:
        missing.append("AI model")
    return missing


def _collect_errors(exc: Exception, errors: list[str], section: str) -> None:
    if hasattr(exc, "errors"):
        for e in exc.errors():
            errors.append(f"{section}: {e['msg']}")
    else:
        errors.append(f"{section}: {exc}")
