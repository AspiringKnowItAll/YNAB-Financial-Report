"""
Authentication routes: first-run setup, unlock, and recovery code flow.

GET  /first-run       → Render master password creation form
POST /first-run       → Process form, derive key, generate recovery codes
GET  /unlock          → Render unlock form
POST /unlock          → Verify password, set app.state.master_key
GET  /recovery        → Render recovery code form
POST /recovery        → Use recovery code, unlock, redirect to new-password flow

Implemented in Phase 2.
"""

from fastapi import APIRouter

router = APIRouter(tags=["auth"])


@router.get("/first-run")
async def get_first_run():
    raise NotImplementedError


@router.post("/first-run")
async def post_first_run():
    raise NotImplementedError


@router.get("/unlock")
async def get_unlock():
    raise NotImplementedError


@router.post("/unlock")
async def post_unlock():
    raise NotImplementedError


@router.get("/recovery")
async def get_recovery():
    raise NotImplementedError


@router.post("/recovery")
async def post_recovery():
    raise NotImplementedError
