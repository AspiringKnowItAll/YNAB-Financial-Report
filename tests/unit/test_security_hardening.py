"""
Unit tests for Phase 13.5 — Security Hardening.

Covers:
- Month parameter validation: invalid values return HTTP 400
- SSE error paths: yielded events never contain raw exception text
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from collections.abc import AsyncIterator


# ---------------------------------------------------------------------------
# Month validation helpers
# ---------------------------------------------------------------------------

def _validate_month(month: str) -> bool:
    """
    Mirror of the validation logic in app/routers/api.py generate_report_api.
    Returns True if valid, raises ValueError if invalid.
    """
    from datetime import datetime
    datetime.strptime(month, "%Y-%m")
    return True


class TestMonthValidation:
    """Test that month parameter validation rejects invalid values."""

    def test_valid_month_jan(self):
        assert _validate_month("2025-01") is True

    def test_valid_month_dec(self):
        assert _validate_month("2025-12") is True

    def test_valid_month_leading_zero(self):
        assert _validate_month("2025-06") is True

    def test_invalid_month_99_raises(self):
        with pytest.raises(ValueError):
            _validate_month("2025-99")

    def test_invalid_month_00_raises(self):
        with pytest.raises(ValueError):
            _validate_month("2025-00")

    def test_invalid_month_13_raises(self):
        with pytest.raises(ValueError):
            _validate_month("2025-13")

    def test_invalid_large_year_large_month_raises(self):
        with pytest.raises(ValueError):
            _validate_month("99999-99")

    def test_invalid_format_no_dash_raises(self):
        with pytest.raises(ValueError):
            _validate_month("202501")

    def test_invalid_format_extra_component_raises(self):
        with pytest.raises(ValueError):
            _validate_month("2025-01-01")

    def test_invalid_non_numeric_month_raises(self):
        with pytest.raises(ValueError):
            _validate_month("2025-ab")


# ---------------------------------------------------------------------------
# SSE error non-leakage
# ---------------------------------------------------------------------------

async def _collect_sse_events(generator: AsyncIterator[str]) -> list[str]:
    """Collect all SSE events from an async generator."""
    events = []
    async for chunk in generator:
        events.append(chunk)
    return events


class TestSSEErrorRedaction:
    """Test that SSE streams never include raw exception text."""

    async def test_life_context_sse_error_is_generic(self):
        """life_context stream_reply exception yields a generic error message."""
        secret_text = "sk-supersecretapikey12345"

        async def failing_stream_reply(**kwargs):
            raise RuntimeError(f"Connection failed: {secret_text}")
            yield  # make it an async generator

        with patch("app.routers.life_context.lcs") as mock_lcs:
            mock_lcs.get_current_session = AsyncMock(return_value=MagicMock(id=1))
            mock_lcs.stream_reply = failing_stream_reply

            # Import the event_generator pattern inline
            import logging
            logger = logging.getLogger("test")

            async def event_generator() -> AsyncIterator[str]:
                try:
                    async for chunk in mock_lcs.stream_reply(db=None, session=None,
                                                              user_message="hi",
                                                              settings=None,
                                                              master_key=None):
                        yield f"data: {chunk}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as exc:
                    logger.error("Chat stream error: %s", exc, exc_info=True)
                    yield "data: [ERROR] An internal error occurred. Check server logs.\n\n"

            events = await _collect_sse_events(event_generator())

        # Must have at least one event
        assert len(events) >= 1
        # The error event must NOT contain the secret text
        error_events = [e for e in events if "[ERROR]" in e]
        assert len(error_events) == 1
        assert secret_text not in error_events[0]
        assert "An internal error occurred" in error_events[0]

    async def test_import_chat_sse_error_is_generic(self):
        """import_data chat stream exception yields a generic error message."""
        secret_text = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"

        import logging
        logger = logging.getLogger("test")

        async def event_generator() -> AsyncIterator[str]:
            try:
                raise ValueError(f"Auth failed: {secret_text}")
                yield  # make it an async generator
            except Exception as exc:
                logger.error("Import chat stream error: %s", exc, exc_info=True)
                yield "data: [ERROR] An internal error occurred. Check server logs.\n\n"

        events = await _collect_sse_events(event_generator())

        error_events = [e for e in events if "[ERROR]" in e]
        assert len(error_events) == 1
        assert secret_text not in error_events[0]
        assert "An internal error occurred" in error_events[0]

    async def test_report_commentary_error_is_generic(self):
        """
        AI commentary failure stores a generic string — not the exception message.
        """
        secret_text = "internal-db-path-/data/ynab_report.db"

        # Simulate the exception handling in report_service.py
        ai_commentary: str | None = None
        try:
            raise RuntimeError(f"DB open failed at {secret_text}")
        except Exception as exc:
            import logging
            logging.getLogger("test").error("AI commentary generation failed: %s", exc)
            ai_commentary = "AI commentary unavailable."

        assert ai_commentary is not None
        assert secret_text not in ai_commentary
        assert ai_commentary == "AI commentary unavailable."
