"""
Settings service — provides decrypted settings values for use by routers.

Routers that need decrypted setting values should call functions in this
module rather than importing encryption.decrypt() directly.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSettings
from app.services.encryption import decrypt

logger = logging.getLogger(__name__)


async def get_global_custom_css(
    db: AsyncSession, master_key: bytes | None
) -> str | None:
    """Decrypt global custom CSS from AppSettings, or return None.

    Args:
        db: Async SQLAlchemy session.
        master_key: The Fernet key from ``app.state.master_key``.
            If ``None`` (app locked), returns ``None`` without raising.

    Returns:
        The decrypted CSS string, or ``None`` if not configured / not
        decryptable.
    """
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings and settings.custom_css_enc and master_key:
        try:
            return decrypt(settings.custom_css_enc, master_key)
        except Exception:
            logger.warning("Failed to decrypt global custom CSS — skipping", exc_info=True)
    return None
