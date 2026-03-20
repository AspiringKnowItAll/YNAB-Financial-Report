"""
Life Context Chat routes.

GET  /profile                  → Full-page "My Financial Profile"
GET  /api/chat/session         → Active session ID + messages (widget init / reload)
POST /api/chat/message         → Accept {session_id, content} → stream SSE reply
POST /api/chat/end             → Accept {session_id} → compress → {ok: true}
"""

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.life_context import LifeContextSession
from app.models.settings import AppSettings
from app.services import life_context_service as lcs
from app.templates_config import templates

router = APIRouter(tags=["life_context"])
logger = logging.getLogger("app.routers.life_context")


# ---------------------------------------------------------------------------
# Pydantic schemas (router boundary validation)
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    session_id: int
    content: str = Field(min_length=1, max_length=10000)


class EndSessionRequest(BaseModel):
    session_id: int


# ---------------------------------------------------------------------------
# GET /profile
# ---------------------------------------------------------------------------

@router.get("/profile", response_class=HTMLResponse)
async def get_profile(request: Request, db: AsyncSession = Depends(get_db)):
    master_key: bytes = request.app.state.master_key

    current_block_text = await lcs.get_current_block(db, master_key)
    block_history = await lcs.get_block_history(db)
    active_session = await lcs.get_active_session(db)

    return templates.TemplateResponse(request, "life_context/profile.html", {
        "current_block_text": current_block_text,
        "block_history": block_history,
        "has_active_session": active_session is not None,
        "active_session_id": active_session.id if active_session else None,
        "current_page": "profile",
    })


# ---------------------------------------------------------------------------
# GET /api/chat/session
# ---------------------------------------------------------------------------

@router.get("/api/chat/session")
async def get_or_create_session(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Return active session state for widget initialization.

    If an unended session exists: return its ID + decrypted messages.
    If none: create a new session and return intro data.
    """
    master_key: bytes = request.app.state.master_key

    active = await lcs.get_active_session(db)

    if active:
        messages = await lcs.get_messages(active, master_key)
        if messages:
            return {
                "session_id": active.id,
                "is_resumed": True,
                "messages": messages,
                "intro": None,
            }
        # Zombie session (opened but no messages sent) — abandon and start fresh
        await lcs.abandon_session(db, active)

    # No active session — create one and return intro data
    session = await lcs.create_session(db)
    intro = await lcs.get_intro_data(db, master_key)
    return {
        "session_id": session.id,
        "is_resumed": False,
        "messages": [],
        "intro": intro,
    }


# ---------------------------------------------------------------------------
# POST /api/chat/message  (SSE streaming)
# ---------------------------------------------------------------------------

@router.post("/api/chat/message")
async def send_message(
    body: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a user message and stream the AI reply as SSE.

    SSE format:
        data: <token text>\\n\\n
        ...
        data: [DONE]\\n\\n

    On error:
        data: [ERROR] <message>\\n\\n
    """
    master_key: bytes = request.app.state.master_key

    # Fetch the session
    result = await db.execute(
        select(LifeContextSession).where(LifeContextSession.id == body.session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.ended_at is not None:
        raise HTTPException(status_code=400, detail="Session has already ended.")

    # Load settings
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None or not settings.ai_provider:
        raise HTTPException(status_code=503, detail="AI provider is not configured.")

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for chunk in lcs.stream_reply(
                db=db,
                session=session,
                user_message=body.content,
                settings=settings,
                master_key=master_key,
            ):
                # Escape newlines within a chunk so each SSE message stays on one line
                safe_chunk = chunk.replace("\n", "\\n")
                yield f"data: {safe_chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error("Chat stream error: %s", exc, exc_info=True)
            yield "data: [ERROR] An internal error occurred. Check server logs.\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# POST /api/chat/message/opener  (SSE streaming — returning-user opener)
# ---------------------------------------------------------------------------

@router.post("/api/chat/opener")
async def stream_opener(
    body: EndSessionRequest,  # just needs session_id to confirm session exists
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Stream a short personalized AI opener for a returning user.
    Called by the widget when intro.type == "ai_opener".
    """
    master_key: bytes = request.app.state.master_key

    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None or not settings.ai_provider:
        raise HTTPException(status_code=503, detail="AI provider is not configured.")

    existing_context = await lcs.get_current_block(db, master_key) or ""

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for chunk in lcs.stream_opener(
                existing_context=existing_context,
                settings=settings,
                master_key=master_key,
            ):
                safe_chunk = chunk.replace("\n", "\\n")
                yield f"data: {safe_chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error("Chat opener stream error: %s", exc, exc_info=True)
            yield "data: [ERROR] An internal error occurred. Check server logs.\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# POST /api/chat/end
# ---------------------------------------------------------------------------

@router.post("/api/chat/end")
async def end_session(
    body: EndSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Compress the session into a new LifeContextBlock and mark it ended."""
    master_key: bytes = request.app.state.master_key

    result = await db.execute(
        select(LifeContextSession).where(LifeContextSession.id == body.session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.ended_at is not None:
        raise HTTPException(status_code=400, detail="Session has already ended.")

    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None or not settings.ai_provider:
        raise HTTPException(status_code=503, detail="AI provider is not configured.")

    new_block = await lcs.end_session(
        db=db,
        session=session,
        settings=settings,
        master_key=master_key,
    )

    if new_block is None:
        # Session ended but had no user messages — no context block was created.
        return {"ok": True, "version": None, "empty": True}

    return {"ok": True, "version": new_block.version, "empty": False}
