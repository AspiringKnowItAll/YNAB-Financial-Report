"""
Authentication routes: first-run setup, unlock, and recovery code flow.

GET  /first-run       → Render master password creation form
POST /first-run       → Process form, derive key, generate recovery codes
GET  /unlock          → Render unlock form
POST /unlock          → Verify password, set app.state.master_key
GET  /recovery        → Render recovery code form
POST /recovery        → Use recovery code, unlock, redirect to new-password flow
"""

import logging
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.database import (
    AsyncSessionLocal,
    apply_migrations,
    create_all,
    migrate_plaintext_to_encrypted,
    set_database_key,
)
from app.models.settings import AppSettings
from app.scheduler import reschedule_job
from app.schemas.auth import MasterPasswordCreate, MasterPasswordUnlock, RecoveryCodeSubmit
from app.services import auth_service
from app.templates_config import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# First-run
# ---------------------------------------------------------------------------

@router.get("/first-run", response_class=HTMLResponse)
async def get_first_run(request: Request):
    if auth_service.is_setup_complete():
        return RedirectResponse("/unlock", status_code=302)
    return templates.TemplateResponse(request, "auth/first_run.html")


@router.post("/first-run", response_class=HTMLResponse)
async def post_first_run(
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if auth_service.is_setup_complete():
        return RedirectResponse("/unlock", status_code=302)

    # Validate via Pydantic schema
    try:
        validated = MasterPasswordCreate(password=password, password_confirm=password_confirm)
    except Exception as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if hasattr(exc, "errors") else [str(exc)]
        return templates.TemplateResponse(
            request,
            "auth/first_run.html",
            {"errors": errors},
            status_code=422,
        )

    recovery_codes = await auth_service.setup_master_password(validated.password)
    request.app.state.master_key = await auth_service.unlock(validated.password)

    # Initialize the encrypted database for the first time
    set_database_key(request.app.state.master_key)
    await create_all()
    await apply_migrations()

    return templates.TemplateResponse(
        request,
        "auth/recovery_codes.html",
        {"codes": recovery_codes},
    )


# ---------------------------------------------------------------------------
# Unlock
# ---------------------------------------------------------------------------

@router.get("/unlock", response_class=HTMLResponse)
async def get_unlock(request: Request):
    if not auth_service.is_setup_complete():
        return RedirectResponse("/first-run", status_code=302)
    if request.app.state.master_key is not None:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "auth/unlock.html")


@router.post("/unlock", response_class=HTMLResponse)
async def post_unlock(
    request: Request,
    password: str = Form(...),
):
    try:
        validated = MasterPasswordUnlock(password=password)
    except Exception as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if hasattr(exc, "errors") else [str(exc)]
        return templates.TemplateResponse(
            request,
            "auth/unlock.html",
            {"errors": errors},
            status_code=422,
        )

    try:
        request.app.state.master_key = await auth_service.unlock(validated.password)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "auth/unlock.html",
            {"errors": ["Incorrect password. Please try again."]},
            status_code=401,
        )

    # Open the encrypted database and run migrations
    set_database_key(request.app.state.master_key)
    try:
        await migrate_plaintext_to_encrypted(request.app.state.master_key)
    except Exception:
        logger.exception("Database migration to encrypted format failed")
        request.app.state.master_key = None
        return templates.TemplateResponse(
            request,
            "auth/unlock.html",
            {
                "errors": [
                    "Database migration failed. Your data may be intact but could "
                    "not be converted to encrypted format. Please contact support."
                ]
            },
            status_code=500,
        )
    await apply_migrations()
    await create_all()

    # Reschedule automated jobs now that the DB is accessible
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        settings = result.scalar_one_or_none()
    if settings and settings.schedule_enabled:
        reschedule_job(settings, request.app)

    return RedirectResponse("/", status_code=302)


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

@router.get("/recovery", response_class=HTMLResponse)
async def get_recovery(request: Request):
    if not auth_service.is_setup_complete():
        return RedirectResponse("/first-run", status_code=302)
    return templates.TemplateResponse(request, "auth/recovery.html")


@router.post("/recovery", response_class=HTMLResponse)
async def post_recovery(
    request: Request,
    code: str = Form(...),
):
    try:
        validated = RecoveryCodeSubmit(code=code)
    except Exception as exc:
        errors = [str(e["msg"]) for e in exc.errors()] if hasattr(exc, "errors") else [str(exc)]
        return templates.TemplateResponse(
            request,
            "auth/recovery.html",
            {"errors": errors},
            status_code=422,
        )

    try:
        request.app.state.master_key = await auth_service.use_recovery_code(validated.code)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "auth/recovery.html",
            {"errors": ["Invalid or already-used recovery code."]},
            status_code=401,
        )

    # Open the encrypted database and run migrations
    set_database_key(request.app.state.master_key)
    try:
        await migrate_plaintext_to_encrypted(request.app.state.master_key)
    except Exception:
        logger.exception("Database migration to encrypted format failed during recovery")
        request.app.state.master_key = None
        return templates.TemplateResponse(
            request,
            "auth/recovery.html",
            {
                "errors": [
                    "Database migration failed. Your data may be intact but could "
                    "not be converted to encrypted format. Please contact support."
                ]
            },
            status_code=500,
        )
    await apply_migrations()
    await create_all()

    # Recovery succeeded — force new master password setup.
    # Clear the salt so is_setup_complete() returns False, triggering /first-run.
    os.remove(auth_service.SALT_PATH)
    os.remove(auth_service.VERIFY_PATH)
    os.remove(auth_service.RECOVERY_PATH)

    return templates.TemplateResponse(request, "auth/recovery_success.html")
