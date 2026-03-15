"""
Optional Notion sync service.

Pushes a monthly report summary to a user-configured Notion database
via the Notion REST API (httpx.AsyncClient).

Only active when notion_enabled=True in AppSettings.

Implemented in Phase 9.
"""

from app.models.report import ReportSnapshot
from app.models.settings import AppSettings


async def sync_report_to_notion(
    settings: AppSettings,
    master_key: bytes,
    snapshot: ReportSnapshot,
) -> None:
    """
    Create or update a Notion database page for the given report snapshot.

    Args:
        settings: AppSettings singleton (id=1); Notion token decrypted here.
        master_key: From app.state.master_key — used to decrypt notion_token_enc.
        snapshot: The ReportSnapshot to sync.

    Raises:
        RuntimeError: If notion_enabled is False or Notion config is incomplete.
        httpx.HTTPStatusError: On Notion API errors.
    """
    raise NotImplementedError
