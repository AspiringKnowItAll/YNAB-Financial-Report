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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.import_data import ImportSession, InstitutionProfile
from app.models.settings import AppSettings
from app.services import import_service
from app.services.encryption import decrypt, encrypt
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

    return templates.TemplateResponse(
        request, "import/import.html", {"institution_profiles": profiles}
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

    # --- 5. Load institution profile (optional) -------------------------
    profile: InstitutionProfile | None = None
    profile_id_stripped = institution_profile_id.strip()
    if profile_id_stripped:
        try:
            pid = int(profile_id_stripped)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Invalid institution profile ID."},
            )
        profile_result = await db.execute(
            select(InstitutionProfile).where(InstitutionProfile.id == pid)
        )
        profile = profile_result.scalar_one_or_none()

    # --- 6. Extract text ------------------------------------------------
    try:
        text, is_low_yield = await import_service.extract_text(
            file_bytes, file.filename or "upload"
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(exc)},
        )
    except Exception:
        logger.exception("Text extraction failed")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Failed to extract text from file."},
        )

    # --- 7. Vision fallback --------------------------------------------
    vision_needed = False
    if is_low_yield:
        try:
            vision_capable = await import_service.check_model_vision_capable(
                settings, master_key
            )
            if vision_capable:
                text = await import_service.extract_via_vision(
                    file_bytes, settings, master_key
                )
            else:
                vision_needed = True
        except Exception:
            logger.exception("Vision extraction failed, using sparse text")
            vision_needed = True

    # --- 8. Normalize with AI ------------------------------------------
    try:
        normalization_result = await import_service.normalize_with_ai(
            text, profile, settings, master_key
        )
    except Exception:
        logger.exception("AI normalization failed")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "AI normalization failed."},
        )

    # --- 9. Save ImportSession ------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    session = ImportSession(
        file_name=file.filename or "upload",
        file_hash=file_hash,
        status="reviewing",
        data_type=normalization_result.get("data_type"),
        institution_name=normalization_result.get("institution_name"),
        extracted_data_enc=encrypt(json.dumps(normalization_result), master_key),
        file_content_enc=encrypt(
            base64.b64encode(file_bytes).decode(), master_key
        ),
        created_at=now_iso,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # --- 10. Return response -------------------------------------------
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "session_id": session.id,
            "normalization": normalization_result,
            "duplicate_file_warning": duplicate_file_warning,
            "vision_needed": vision_needed,
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
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
