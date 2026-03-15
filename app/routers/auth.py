"""
Authentication routes: first-run setup, unlock, and recovery code flow.

GET  /first-run       → Render master password creation form
POST /first-run       → Process form, derive key, generate recovery codes
GET  /unlock          → Render unlock form
POST /unlock          → Verify password, set app.state.master_key
GET  /recovery        → Render recovery code form
POST /recovery        → Use recovery code, unlock, redirect to new-password flow
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.schemas.auth import MasterPasswordCreate, MasterPasswordUnlock, RecoveryCodeSubmit
from app.services import auth_service

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


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

    # Recovery succeeded — force new master password setup.
    # Clear the salt so is_setup_complete() returns False, triggering /first-run.
    import os
    os.remove(auth_service.SALT_PATH)
    os.remove(auth_service.VERIFY_PATH)
    os.remove(auth_service.RECOVERY_PATH)

    return templates.TemplateResponse(request, "auth/recovery_success.html")
