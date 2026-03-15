"""
Settings routes — manage YNAB, AI, email, and Notion configuration.

GET  /settings   → Render settings page (secrets shown as ●●●●●●●● placeholders)
POST /settings   → Save and encrypt updated settings

All inputs validated through Pydantic schemas in app/schemas/settings.py.
Secret fields are NEVER pre-populated with decrypted values in the form.

Implemented in Phase 2.
"""

from fastapi import APIRouter

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings():
    raise NotImplementedError


@router.post("/settings")
async def post_settings():
    raise NotImplementedError
