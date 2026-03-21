"""
Import service for Phase 13 — External Data Import.

Handles text extraction from uploaded documents (PDF, CSV, TXT),
AI-powered normalization of financial data, vision-based OCR fallback,
duplicate detection, and persistence of confirmed import rows.
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import date as date_type
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

import httpx
from sqlalchemy import func, select

from app.models.import_data import (
    ExternalBalance,
    ExternalTransaction,
    ImportSession,
    InstitutionProfile,
)
from app.models.settings import AppSettings
from app.services.ai_service import get_ai_provider
from app.services.encryption import decrypt, encrypt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.import_service")


# ---------------------------------------------------------------------------
# Pydantic validation models for AI-returned row data
# ---------------------------------------------------------------------------

class TransactionRow(BaseModel):
    """Validates a transaction row from AI-extracted data before DB insert."""
    date: date_type
    amount_milliunits: int
    description: str = Field(min_length=1, max_length=512)
    category: str | None = Field(default=None, max_length=256)

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> date_type:
        if isinstance(v, date_type):
            return v
        if isinstance(v, str):
            return date_type.fromisoformat(v)
        raise ValueError(f"Invalid date value: {v!r}")

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, v: object) -> str:
        if v is None:
            raise ValueError("description must not be null")
        return str(v)


class BalanceRow(BaseModel):
    """Validates a balance row from AI-extracted data before DB insert."""
    date: date_type
    amount_milliunits: int
    notes: str | None = Field(default=None, max_length=512)
    contribution_milliunits: int | None = None
    return_bps: int | None = Field(default=None, ge=-100_000, le=100_000)

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> date_type:
        if isinstance(v, date_type):
            return v
        if isinstance(v, str):
            return date_type.fromisoformat(v)
        raise ValueError(f"Invalid date value: {v!r}")


# ---------------------------------------------------------------------------
# 1. extract_text
# ---------------------------------------------------------------------------

async def extract_text(file_bytes: bytes, filename: str) -> tuple[str, bool]:
    """
    Extract text from a PDF or CSV/plain-text file.

    Returns (text, is_low_yield) where is_low_yield=True means the text
    contains fewer than 50 words (likely a scanned PDF requiring OCR).
    """
    ext = filename.rsplit(".", maxsplit=1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        import pdfplumber

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        text = "\n\n".join(text_parts)

    elif ext in ("csv", "txt", "tsv"):
        text = file_bytes.decode("utf-8", errors="replace")

    else:
        raise ValueError(
            f"Unsupported file type: .{ext}. Supported types: .pdf, .csv, .txt, .tsv"
        )

    is_low_yield = len(text.split()) < 50
    return text, is_low_yield


# ---------------------------------------------------------------------------
# 2. check_model_vision_capable
# ---------------------------------------------------------------------------

async def check_model_vision_capable(
    settings: AppSettings, master_key: bytes
) -> bool:
    """
    Return True if the configured AI model supports vision (image) input.

    - anthropic / openai / openrouter: assume capable.
    - ollama: query the model show endpoint and check capabilities.
    """
    provider = settings.ai_provider

    if provider in ("anthropic", "openai", "openrouter"):
        return True

    if provider == "ollama":
        base_url = settings.ai_base_url
        model_name = settings.ai_model
        if not base_url or not model_name:
            return False

        # Ollama's /api/show endpoint is on the base host, not the /v1 path
        # Strip trailing /v1 or /v1/ if present
        show_url = base_url.rstrip("/")
        if show_url.endswith("/v1"):
            show_url = show_url[:-3]
        show_url = show_url.rstrip("/") + "/api/show"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    show_url,
                    json={"name": model_name},
                )
                resp.raise_for_status()
                data = resp.json()
                capabilities = data.get("capabilities", [])
                return "vision" in capabilities
        except Exception:
            logger.debug("Failed to query Ollama model capabilities", exc_info=True)
            return False

    return False


# ---------------------------------------------------------------------------
# 3. normalize_with_ai
# ---------------------------------------------------------------------------

_NORMALIZATION_SYSTEM_PROMPT = """You are a financial document parser. Your task is to extract structured financial data from the document text provided.

Return ONLY valid JSON (no markdown fences, no preamble, no explanation). The JSON must match this exact schema:

{
  "institution_name": <string or null — the financial institution name if identifiable>,
  "account_name": <string or null — the specific account name if identifiable>,
  "data_type": <"transactions" | "balances" | "both" | "unknown">,
  "rows": [
    For transaction rows:
    {"type": "transaction", "date": "YYYY-MM-DD", "amount_milliunits": <integer>, "description": <string>, "category": <string or null>}

    For balance rows:
    {"type": "balance", "date": "YYYY-MM-DD", "amount_milliunits": <integer>, "notes": <string or null>, "contribution_milliunits": <integer or null>, "return_bps": <integer or null>}
  ],
  "questions": [<list of clarifying questions as strings, if any>],
  "summary": <one-sentence human-readable summary of what was extracted>
}

CRITICAL RULES:
- Convert ALL dollar amounts to milliunits: multiply by 1000, round to the nearest integer. Example: $42.50 → 42500, -$100.00 → -100000.
- Preserve sign: outflows/debits/withdrawals/payments are NEGATIVE. Inflows/credits/deposits are POSITIVE.
- Normalize ALL dates to ISO format YYYY-MM-DD.
- For balance rows: return_bps is basis points (percentage × 100). Example: 7.5% → 750.
- If you cannot determine a field, use null.
- Do NOT include any text outside the JSON object."""


async def normalize_with_ai(
    text: str,
    profile: InstitutionProfile | None,
    settings: AppSettings,
    master_key: bytes,
) -> dict:
    """
    Send extracted text to the AI and return a structured normalization dict.
    """
    ai = get_ai_provider(settings, master_key)

    user_prompt_parts: list[str] = []

    if profile:
        if profile.format_hints:
            user_prompt_parts.append(
                f"Known format hints for this institution:\n{profile.format_hints}"
            )
        if profile.notes:
            user_prompt_parts.append(
                f"Additional notes about this institution:\n{profile.notes}"
            )
        if user_prompt_parts:
            user_prompt_parts.append("---")

    user_prompt_parts.append("Document text to parse:\n\n" + text)
    user_prompt = "\n\n".join(user_prompt_parts)

    _fallback: dict = {
        "institution_name": None,
        "account_name": None,
        "data_type": "unknown",
        "rows": [],
        "questions": [],
        "summary": "Could not parse AI response.",
    }

    try:
        response_text = await ai.generate(
            system=_NORMALIZATION_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=8192,
        )
    except Exception:
        logger.error("AI normalization call failed", exc_info=True)
        return _fallback

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        logger.warning("AI returned invalid JSON for normalization")
        return _fallback

    if not isinstance(result, dict):
        return _fallback

    # Ensure required keys exist with correct types
    result.setdefault("institution_name", None)
    result.setdefault("account_name", None)
    result.setdefault("data_type", "unknown")
    result.setdefault("rows", [])
    result.setdefault("questions", [])
    result.setdefault("summary", "")

    return result


# ---------------------------------------------------------------------------
# 4. extract_via_vision
# ---------------------------------------------------------------------------

async def extract_via_vision(
    file_bytes: bytes,
    settings: AppSettings,
    master_key: bytes,
) -> str:
    """
    Render each PDF page to a PNG image and send to the AI vision API.

    Uses the AIProvider protocol's vision() method so that all AI SDK
    imports remain confined to ai_service.py.
    """
    import fitz  # pymupdf

    provider = get_ai_provider(settings, master_key)

    # Render PDF pages to PNG images
    page_images: list[bytes] = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        for page in doc:
            # 150 DPI: default is 72, so scale factor = 150/72 ≈ 2.083
            mat = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat)
            page_images.append(pix.tobytes("png"))
    finally:
        doc.close()

    if not page_images:
        raise RuntimeError("PDF has no pages to render.")

    vision_prompt = (
        "Extract ALL financial data from this document page image. "
        "Include every transaction, balance, account name, date, and amount you can find. "
        "Return the data as plain text, preserving the tabular structure where possible."
    )

    # Call vision() once per page and concatenate results
    page_results: list[str] = []
    for png_bytes in page_images:
        result = await provider.vision(png_bytes, vision_prompt)
        page_results.append(result)

    return "\n\n".join(page_results)


# ---------------------------------------------------------------------------
# 5. check_file_duplicate
# ---------------------------------------------------------------------------

async def check_file_duplicate(
    file_hash: str, db: AsyncSession
) -> ImportSession | None:
    """
    Return the most recent confirmed ImportSession with the same file_hash,
    or None if no prior confirmed import exists for this hash.
    """
    stmt = (
        select(ImportSession)
        .where(ImportSession.file_hash == file_hash)
        .where(ImportSession.status == "confirmed")
        .order_by(ImportSession.confirmed_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 6. check_row_duplicates
# ---------------------------------------------------------------------------

async def check_row_duplicates(
    rows: list[dict],
    external_account_id: int,
    db: AsyncSession,
) -> list[dict]:
    """
    Check for duplicate/near-duplicate transactions before confirmation.
    Balance rows are not checked. Returns rows with duplicate flags added.
    """
    for row in rows:
        if row.get("type") != "transaction":
            continue

        row_date = row.get("date")
        row_amount = row.get("amount_milliunits")
        row_desc = row.get("description")

        if row_date is None or row_amount is None:
            continue

        # Query for matching transactions on same account, date, and amount
        stmt = select(ExternalTransaction).where(
            ExternalTransaction.external_account_id == external_account_id,
            ExternalTransaction.date == row_date,
            ExternalTransaction.amount_milliunits == row_amount,
        )
        result = await db.execute(stmt)
        existing = result.scalars().all()

        for existing_txn in existing:
            if existing_txn.description == row_desc:
                row["duplicate"] = "exact"
                break
            else:
                row["duplicate"] = "near"
                row["existing_description"] = existing_txn.description
                # Don't break — an exact match would override a near match
        # If we found an exact match, it was set via break above

    return rows


# ---------------------------------------------------------------------------
# 7. save_confirmed_import
# ---------------------------------------------------------------------------

async def save_confirmed_import(
    session_id: int,
    external_account_id: int,
    db: AsyncSession,
    master_key: bytes,
) -> None:
    """
    Write confirmed rows from ImportSession.extracted_data_enc into
    external_transactions and/or external_balances.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Load the import session
    stmt = select(ImportSession).where(ImportSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise ValueError(f"ImportSession with id={session_id} not found.")
    if session.status != "reviewing":
        raise ValueError(
            f"ImportSession {session_id} has status '{session.status}', "
            "expected 'reviewing'."
        )

    # 2. Decrypt and parse extracted data
    if not session.extracted_data_enc:
        raise ValueError(f"ImportSession {session_id} has no extracted data.")

    extracted_json = decrypt(session.extracted_data_enc, master_key)
    extracted_data = json.loads(extracted_json)
    rows: list[dict] = extracted_data.get("rows", [])

    # 3. Check for duplicates and insert rows
    rows = await check_row_duplicates(rows, external_account_id, db)

    for row in rows:
        row_type = row.get("type")

        if row_type == "transaction":
            # Skip exact duplicates silently
            if row.get("duplicate") == "exact":
                continue

            try:
                validated = TransactionRow.model_validate(row)
            except Exception as exc:
                logger.warning("Skipping invalid transaction row: %s — %s", row, exc)
                continue

            txn = ExternalTransaction(
                external_account_id=external_account_id,
                date=validated.date.isoformat(),
                amount_milliunits=validated.amount_milliunits,
                description=validated.description,
                category=validated.category,
                import_session_id=session_id,
                created_at=now_iso,
            )
            db.add(txn)

        elif row_type == "balance":
            try:
                validated_bal = BalanceRow.model_validate(row)
            except Exception as exc:
                logger.warning("Skipping invalid balance row: %s — %s", row, exc)
                continue

            bal = ExternalBalance(
                external_account_id=external_account_id,
                balance_milliunits=validated_bal.amount_milliunits,
                as_of_date=validated_bal.date.isoformat(),
                notes=validated_bal.notes,
                contribution_milliunits=validated_bal.contribution_milliunits,
                return_bps=validated_bal.return_bps,
                import_session_id=session_id,
                created_at=now_iso,
            )
            db.add(bal)

    # 4. Update session status and clear raw file content
    session.status = "confirmed"
    session.confirmed_at = now_iso
    session.file_content_enc = None

    # 5. Commit
    await db.commit()


# ---------------------------------------------------------------------------
# 8. get_institution_profile
# ---------------------------------------------------------------------------

async def get_institution_profile(
    name: str, db: AsyncSession
) -> InstitutionProfile | None:
    """
    Return the InstitutionProfile whose name matches (case-insensitive),
    or None if not found.
    """
    stmt = select(InstitutionProfile).where(
        func.lower(InstitutionProfile.name) == name.lower()
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 9. save_institution_profile
# ---------------------------------------------------------------------------

async def save_institution_profile(
    institution_name: str,
    format_hints: str | None,
    notes: str | None,
    db: AsyncSession,
) -> InstitutionProfile:
    """
    Create or update the InstitutionProfile for the given institution_name.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    existing = await get_institution_profile(institution_name, db)

    if existing:
        existing.format_hints = format_hints
        existing.notes = notes
        existing.updated_at = now_iso
        await db.commit()
        await db.refresh(existing)
        return existing

    profile = InstitutionProfile(
        name=institution_name,
        format_hints=format_hints,
        notes=notes,
        created_at=now_iso,
        updated_at=now_iso,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# 10. stream_import_chat
# ---------------------------------------------------------------------------

_IMPORT_CHAT_SYSTEM_PROMPT = """You are an AI assistant helping a user review financial data extracted from a document.

CURRENT EXTRACTED DATA:
{current_data}

CHAT HISTORY (previous messages):
{chat_history}

Your job:
- Answer the user's questions about the extracted data.
- Correct mistakes the user points out (wrong amounts, wrong dates, missing rows, etc.).
- If the user tells you about corrections, respond conversationally AND include an updated \
data block using EXACTLY this format at the END of your response (after your conversational reply):
  [DATA_UPDATE]{{valid JSON matching the normalization schema}}[/DATA_UPDATE]

  The JSON schema is:
  {{"institution_name": str|null, "account_name": str|null, "data_type": "transactions"|"balances"|"both"|"unknown",
   "rows": [{{"type": "transaction"|"balance", ...all fields...}}], "questions": [str], "summary": str}}

  ALL amounts must be in milliunits (dollars × 1000, integer, signed).

- Only include [DATA_UPDATE] when the user has explicitly asked for a correction or update.
  For purely informational questions, just answer conversationally without [DATA_UPDATE].
- Keep responses concise and focused on the financial data."""

_DATA_UPDATE_RE = re.compile(r"\[DATA_UPDATE\](.*?)\[/DATA_UPDATE\]", re.DOTALL)

_DATA_UPDATE_SENTINEL = "\x00DATA_UPDATE\x00"


async def stream_import_chat(
    db: AsyncSession,
    session: ImportSession,
    user_message: str,
    settings: AppSettings,
    master_key: bytes,
) -> AsyncIterator[str]:
    """Stream an AI chat response for the import review, yielding text chunks."""
    # 1. Decode existing messages
    messages: list[dict[str, str]] = []
    if session.messages_enc:
        messages = json.loads(decrypt(session.messages_enc, master_key))

    # 2. Append user message
    messages.append({"role": "user", "content": user_message})

    # 3. Build current normalization context
    current_data = "(none)"
    if session.extracted_data_enc:
        current_data = decrypt(session.extracted_data_enc, master_key)

    # 4. Build chat history string (all messages before the current one)
    history_parts: list[str] = []
    for msg in messages[:-1]:
        prefix = "User" if msg["role"] == "user" else "Assistant"
        history_parts.append(f"{prefix}: {msg['content']}")
    chat_history = "\n".join(history_parts) if history_parts else "(no previous messages)"

    # 5. Build prompts
    system_prompt = _IMPORT_CHAT_SYSTEM_PROMPT.format(
        current_data=current_data,
        chat_history=chat_history,
    )

    # 6. Stream from AI
    ai = get_ai_provider(settings, master_key)
    full_response = ""

    try:
        async for chunk in ai.stream(
            system=system_prompt,
            user=user_message,
            max_tokens=2048,
        ):
            full_response += chunk
            yield chunk
    except Exception as exc:
        logger.error("Import chat AI stream failed: %s", exc, exc_info=True)
        raise

    # 7. Inspect for DATA_UPDATE block
    data_update_match = _DATA_UPDATE_RE.search(full_response)
    if data_update_match:
        raw_json = data_update_match.group(1)
        try:
            parsed_update = json.loads(raw_json)
            # Save updated extracted data
            session.extracted_data_enc = encrypt(json.dumps(parsed_update), master_key)
            # Yield sentinel for the router to detect
            yield _DATA_UPDATE_SENTINEL + json.dumps(parsed_update)
        except json.JSONDecodeError:
            logger.warning("Import chat: AI returned invalid JSON in DATA_UPDATE block")

        # Strip DATA_UPDATE block from the visible response
        visible_response = _DATA_UPDATE_RE.sub("", full_response).strip()
    else:
        visible_response = full_response

    # 8. Save assistant message
    messages.append({"role": "assistant", "content": visible_response})
    session.messages_enc = encrypt(json.dumps(messages), master_key)

    # 9. Commit
    await db.commit()
