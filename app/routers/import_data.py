"""Router for Phase 13 — External Data Import (Milestone 3: upload + review)."""

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.import_data import ExternalAccount, ImportSession, InstitutionProfile
from app.models.settings import AppSettings
from app.services import import_service
from app.services.encryption import decrypt, encrypt
from app.services.settings_service import get_global_custom_css
from app.templates_config import templates

logger = logging.getLogger("app.routers.import_data")

router = APIRouter(tags=["import"])

_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
_ACCEPTED_MIME_TYPES = {"application/pdf", "text/csv", "text/plain"}


# ---------------------------------------------------------------------------
# GET /import — render upload page
# ---------------------------------------------------------------------------

@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(InstitutionProfile).order_by(InstitutionProfile.id.desc())
    result = await db.execute(stmt)
    profiles = result.scalars().all()

    global_custom_css = await get_global_custom_css(db, request.app.state.master_key)
    return templates.TemplateResponse(
        request, "import/import.html", {
            "institution_profiles": profiles,
            "global_custom_css": global_custom_css,
            "current_page": "import",
        }
    )


# ---------------------------------------------------------------------------
# POST /api/import/upload — accept file, extract, normalize, save session
# ---------------------------------------------------------------------------

@router.post("/api/import/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    institution_profile_id: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    # --- Load settings -------------------------------------------------
    settings_result = await db.execute(
        select(AppSettings).where(AppSettings.id == 1)
    )
    settings = settings_result.scalar_one_or_none()
    if settings is None or not settings.settings_complete:
        raise HTTPException(status_code=503, detail="AI is not configured. Complete settings first.")

    # --- 1. Validate MIME type -----------------------------------------
    if file.content_type not in _ACCEPTED_MIME_TYPES:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": f"Unsupported file type: {file.content_type}. Accepted: PDF, CSV, TXT.",
            },
        )

    # --- 2. Read bytes and validate size --------------------------------
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_FILE_BYTES:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "File exceeds the 10 MB size limit.",
            },
        )

    # --- 3. Compute SHA-256 hash ----------------------------------------
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # --- 4. Check file duplicate ----------------------------------------
    duplicate_file_warning: dict | None = None
    dup_session = await import_service.check_file_duplicate(file_hash, db)
    if dup_session is not None:
        duplicate_file_warning = {
            "previous_session_id": dup_session.id,
            "confirmed_at": dup_session.confirmed_at or dup_session.created_at,
        }

    # --- 5. Save ImportSession (pending — no AI processing) ---------------
    now_iso = datetime.now(timezone.utc).isoformat()
    session = ImportSession(
        file_name=file.filename or "upload",
        file_hash=file_hash,
        status="pending",
        file_content_enc=encrypt(
            base64.b64encode(file_bytes).decode(), master_key
        ),
        created_at=now_iso,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # --- 6. Return response immediately --------------------------------
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "session_id": session.id,
            "file_name": session.file_name,
            "duplicate_file_warning": duplicate_file_warning,
        },
    )


# ---------------------------------------------------------------------------
# GET /api/import/session/{session_id} — reload session state
# ---------------------------------------------------------------------------

@router.get("/api/import/session/{session_id}")
async def get_session(
    request: Request,
    session_id: int,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    result = await db.execute(
        select(ImportSession).where(ImportSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found.")

    normalization: dict | None = None
    if session.extracted_data_enc:
        try:
            normalization = json.loads(
                decrypt(session.extracted_data_enc, master_key)
            )
        except Exception:
            logger.exception("Failed to decrypt session extracted data")

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "session_id": session.id,
            "session_status": session.status,
            "normalization": normalization,
            "file_name": session.file_name,
            "institution_name": session.institution_name,
            "data_type": session.data_type,
        },
    )


# ---------------------------------------------------------------------------
# POST /api/import/chat/{session_id} — SSE streaming chat
# ---------------------------------------------------------------------------

class ImportChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


@router.post("/api/import/chat/{session_id}")
async def import_chat(
    request: Request,
    session_id: int,
    body: ImportChatRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    result = await db.execute(
        select(ImportSession).where(ImportSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found.")
    if session.status != "reviewing":
        raise HTTPException(status_code=400, detail="Session is not in reviewing state.")

    settings_result = await db.execute(
        select(AppSettings).where(AppSettings.id == 1)
    )
    settings = settings_result.scalar_one_or_none()
    if settings is None or not settings.settings_complete:
        raise HTTPException(status_code=503, detail="AI is not configured.")

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for chunk in import_service.stream_import_chat(
                db, session, body.content, settings, master_key
            ):
                if chunk.startswith(import_service._DATA_UPDATE_SENTINEL):
                    data_json = chunk[len(import_service._DATA_UPDATE_SENTINEL) :]
                    yield f"data: [DATA_UPDATE]{data_json}\n\n"
                else:
                    safe_chunk = chunk.replace("\n", "\\n")
                    yield f"data: {safe_chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error("Import chat stream error: %s", exc, exc_info=True)
            yield "data: [ERROR] An internal error occurred. Check server logs.\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# POST /api/import/confirm/{session_id} — confirm import and save rows
# ---------------------------------------------------------------------------

class ImportConfirmRequest(BaseModel):
    account_name: str = Field(min_length=1, max_length=256)
    account_type: str = Field(min_length=1, max_length=32)
    save_institution_profile: bool = False


@router.post("/api/import/confirm/{session_id}")
async def confirm_import(
    request: Request,
    session_id: int,
    body: ImportConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    result = await db.execute(
        select(ImportSession).where(ImportSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found.")
    if session.status != "reviewing":
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Session is not in reviewing state."},
        )

    # Find or create ExternalAccount
    acct_result = await db.execute(
        select(ExternalAccount).where(
            func.lower(ExternalAccount.name) == body.account_name.lower(),
            ExternalAccount.is_active.is_(True),
        )
    )
    account = acct_result.scalar_one_or_none()
    if account is None:
        now_iso = datetime.now(timezone.utc).isoformat()
        account = ExternalAccount(
            name=body.account_name,
            institution=session.institution_name,
            account_type=body.account_type,
            is_active=True,
            created_at=now_iso,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)

    # Save confirmed import rows
    try:
        await import_service.save_confirmed_import(
            session.id, account.id, db, master_key
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(exc)},
        )
    except Exception:
        logger.exception("Unexpected error during import confirmation")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal error during import confirmation."},
        )

    # Count rows for the response message
    row_count = "some"
    try:
        extracted = json.loads(decrypt(session.extracted_data_enc, master_key))
        rows = extracted.get("rows", [])
        row_count = str(len(rows))
    except Exception:
        pass  # Use fallback "some"

    # Optionally save institution profile
    if body.save_institution_profile and session.institution_name:
        try:
            extracted_data = json.loads(decrypt(session.extracted_data_enc, master_key))
            rows_list = extracted_data.get("rows", [])
            format_hints_dict = {
                "data_type": extracted_data.get("data_type"),
                "rows_schema_sample": rows_list[0] if rows_list else None,
            }
            await import_service.save_institution_profile(
                session.institution_name,
                json.dumps(format_hints_dict),
                f"Learned from {session.file_name}",
                db,
            )
        except Exception:
            logger.warning("Failed to save institution profile during confirm")

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "account_id": account.id,
            "message": f"Import confirmed. {row_count} rows saved.",
            "return_to_queue": True,
        },
    )


# ---------------------------------------------------------------------------
# POST /api/import/cancel/{session_id} — cancel an import session
# ---------------------------------------------------------------------------

@router.post("/api/import/cancel/{session_id}")
async def cancel_import(
    request: Request,
    session_id: int,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    result = await db.execute(
        select(ImportSession).where(ImportSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found.")
    if session.status == "confirmed":
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Cannot cancel a confirmed import."},
        )

    session.status = "cancelled"
    session.file_content_enc = None
    await db.commit()

    return JSONResponse(status_code=200, content={"status": "success"})


# ---------------------------------------------------------------------------
# GET /api/import/process/{session_id} — SSE processing stream
# ---------------------------------------------------------------------------

@router.get("/api/import/process/{session_id}")
async def process_session(
    request: Request,
    session_id: int,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    settings_result = await db.execute(
        select(AppSettings).where(AppSettings.id == 1)
    )
    settings = settings_result.scalar_one_or_none()
    if settings is None or not settings.settings_complete:
        raise HTTPException(status_code=503, detail="AI is not configured.")

    return StreamingResponse(
        import_service.process_session_sse(session_id, db, settings, master_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# GET /api/import/sessions/active — queue restore
# ---------------------------------------------------------------------------

@router.get("/api/import/sessions/active")
async def get_active_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    sessions = await import_service.list_active_sessions(db)
    return JSONResponse({"status": "success", "sessions": sessions})


# ---------------------------------------------------------------------------
# GET /api/import/history — confirmed import history
# ---------------------------------------------------------------------------

@router.get("/api/import/history")
async def get_history(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    data = await import_service.list_confirmed_sessions(db)
    return JSONResponse({"status": "success", **data})


# ---------------------------------------------------------------------------
# DELETE /api/import/session/{session_id}/rows — delete imported rows
# ---------------------------------------------------------------------------

@router.delete("/api/import/session/{session_id}/rows")
async def delete_session_rows(
    request: Request,
    session_id: int,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    # Verify session exists and is confirmed
    result = await db.execute(
        select(ImportSession).where(ImportSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found.")
    if session.status != "confirmed":
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Can only delete rows from confirmed sessions."},
        )

    delete_result = await import_service.delete_import_session_rows(session_id, db)
    return JSONResponse({"status": "success", **delete_result})


# ---------------------------------------------------------------------------
# PATCH /api/import/account/{account_id} — toggle account active status
# ---------------------------------------------------------------------------

class AccountUpdateRequest(BaseModel):
    is_active: bool


@router.patch("/api/import/account/{account_id}")
async def update_account(
    request: Request,
    account_id: int,
    body: AccountUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    result = await db.execute(
        select(ExternalAccount).where(ExternalAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    account.is_active = body.is_active
    await db.commit()
    return JSONResponse({"status": "success", "is_active": account.is_active})


# ---------------------------------------------------------------------------
# DELETE /api/import/institution/{profile_id} — delete institution profile
# ---------------------------------------------------------------------------

@router.delete("/api/import/institution/{profile_id}")
async def delete_institution_profile(
    request: Request,
    profile_id: int,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    master_key: bytes | None = request.app.state.master_key
    if master_key is None:
        raise HTTPException(status_code=503, detail="App is locked.")

    result = await db.execute(
        select(InstitutionProfile).where(InstitutionProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Institution profile not found.")

    await db.delete(profile)
    await db.commit()

    return JSONResponse(status_code=200, content={"status": "success"})
