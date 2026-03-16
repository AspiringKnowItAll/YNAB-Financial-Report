"""
Life Context Chat service.

Manages the AI-driven financial life-story system:
  - Chat sessions (create, resume, append messages, end)
  - Context block versioning (compress → archive previous → save new)
  - Intro message logic (static first-time vs AI-generated returning opener)
  - Streaming AI replies via ai_service.stream()

All chat messages and context blocks are encrypted at rest.
Decrypted values are held only in memory during a request.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.life_context import LifeContextBlock, LifeContextSession
from app.models.settings import AppSettings
from app.services.ai_service import get_ai_provider
from app.services.encryption import decrypt, encrypt


# ---------------------------------------------------------------------------
# Default pre-prompt (used when no override is set in AppSettings)
# ---------------------------------------------------------------------------

DEFAULT_PRE_PROMPT = """\
You are a personal finance profile assistant. Your only purpose is to collect
financially relevant facts about the user so that their monthly AI-generated
financial reports are more accurate and actionable.

You already have the following context from previous conversations:
{existing_context_block}

STRICT SCOPE — only ask about these topics:
  - Household size and composition (number of adults, dependents)
  - Income: sources, amounts, frequency, stability (salary, hourly, freelance, etc.)
  - Fixed recurring expenses: rent/mortgage, insurance premiums, loan payments, subscriptions
  - Debts: types, approximate balances, interest rates (student loans, car, credit cards, etc.)
  - Savings and investments: retirement accounts, emergency fund, brokerage accounts
  - Financial goals: saving targets, debt payoff plans, major upcoming purchases
  - Upcoming life events with financial impact: job change, move, new child, large expense

DO NOT ask about:
  - Opinions, feelings, or satisfaction with work or lifestyle
  - Hobbies, interests, or personal preferences unrelated to finances
  - Anything that would not appear in a financial report

Ask one focused question at a time. When the user volunteers information outside
your scope, acknowledge it briefly and redirect to financially relevant details.
After gathering enough facts, you will be asked to compress the conversation into
a concise summary.\
"""

# ---------------------------------------------------------------------------
# Static first-time intro (shown with no API call for brand-new sessions)
# ---------------------------------------------------------------------------

FIRST_TIME_INTRO = (
    "Hi! I'm here to build your financial profile — the personal context that "
    "makes your monthly AI reports more accurate and actionable.\n\n"
    "I'll ask you focused questions about your finances: income, fixed expenses, "
    "debts, savings, and financial goals. I won't ask about anything outside that "
    "scope — just the facts that matter for your reports.\n\n"
    "Everything you share is encrypted and stored only on your own server. "
    "When you're done, click **\"End Chat Session\"** and I'll compress our "
    "conversation into a private context block included in every future report.\n\n"
    "To get started, pick a topic or just start talking:"
)

STARTER_CHIPS = [
    "Tell me about my household and living situation",
    "What are my main financial goals right now?",
    "Walk me through my income and employment situation",
]

# ---------------------------------------------------------------------------
# Compression prompt template
# ---------------------------------------------------------------------------

_COMPRESSION_PROMPT = """\
You are updating a personal financial context block used to improve monthly financial reports.

EXISTING CONTEXT BLOCK (may be empty for a first session):
{existing_block}

NEW CONVERSATION:
{chat_history_as_text}

Your task: Produce a single, compressed context block of no more than 5000 characters.
Merge new information with existing context. Retire any facts that have been superseded.

ONLY include financially relevant facts:
  - Household composition (number of adults, dependents)
  - Income sources, amounts, frequency, and stability
  - Fixed recurring expenses (rent/mortgage, insurance, loan payments)
  - Debts (types, balances, interest rates)
  - Savings and investment accounts
  - Financial goals and savings targets
  - Upcoming life events with financial impact

DO NOT include opinions, feelings, job satisfaction, hobbies, or anything that
would not appear in a financial report. If the conversation contains off-topic
content, ignore it entirely.

Write in third person ("The user..."). Do not include the conversation itself — only distilled facts.
Output only the context block text — no preamble, no headers, no explanation.\
"""

# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_messages(messages_enc: bytes | None, master_key: bytes) -> list[dict]:
    """Decrypt and JSON-decode message list. Returns [] if None."""
    if not messages_enc:
        return []
    return json.loads(decrypt(messages_enc, master_key))


def _encode_messages(messages: list[dict], master_key: bytes) -> bytes:
    """JSON-encode and encrypt message list."""
    return encrypt(json.dumps(messages), master_key)


def _messages_to_text(messages: list[dict]) -> str:
    """Format messages as plain text for the compression prompt."""
    lines = []
    for m in messages:
        role = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"{role}: {m['content']}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

async def get_active_session(db: AsyncSession) -> LifeContextSession | None:
    """Return the unended session if one exists, else None."""
    result = await db.execute(
        select(LifeContextSession)
        .where(LifeContextSession.ended_at.is_(None))
        .order_by(LifeContextSession.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_session(db: AsyncSession) -> LifeContextSession:
    """Create and persist a new empty session row."""
    session = LifeContextSession(created_at=_now_iso())
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_messages(session: LifeContextSession, master_key: bytes) -> list[dict]:
    """Decrypt and return the message list for a session."""
    return _decode_messages(session.messages_enc, master_key)


async def append_message(
    db: AsyncSession,
    session: LifeContextSession,
    role: str,
    content: str,
    master_key: bytes,
) -> None:
    """Add one message to the session and re-encrypt."""
    messages = _decode_messages(session.messages_enc, master_key)
    messages.append({"role": role, "content": content})
    session.messages_enc = _encode_messages(messages, master_key)
    await db.commit()


# ---------------------------------------------------------------------------
# Intro / opener logic
# ---------------------------------------------------------------------------

async def get_intro_data(
    db: AsyncSession,
    master_key: bytes,
) -> dict:
    """
    Return intro data for a brand-new session.

    If no context block has ever been created:
        → return the static hardcoded first-time intro + 3 starter chips.
    If a context block exists:
        → return a marker indicating the caller should stream an AI opener.

    Returns a dict:
        {
          "type": "static" | "ai_opener",
          "content": str,           # present for "static" only
          "chips": list[str],       # present for "static" only
        }
    """
    current_block = await get_current_block(db, master_key)
    if current_block is None:
        return {
            "type": "static",
            "content": FIRST_TIME_INTRO,
            "chips": STARTER_CHIPS,
        }
    return {"type": "ai_opener"}


async def stream_opener(
    existing_context: str,
    settings: AppSettings,
    master_key: bytes,
) -> AsyncIterator[str]:
    """
    Stream a short personalized opener for a returning user.
    Called only when a context block already exists.
    """
    ai = get_ai_provider(settings, master_key)
    system = (
        "You are a warm personal finance companion. "
        "The user is returning to update their financial profile. "
        "Write a short greeting (1–2 sentences) that references something "
        "specific from their existing context, then suggest 3 brief follow-up "
        "questions as a numbered list. Be friendly and concise."
    )
    user = f"Existing context:\n{existing_context}"
    async for chunk in ai.stream(system=system, user=user, max_tokens=256):
        yield chunk


# ---------------------------------------------------------------------------
# Streaming reply
# ---------------------------------------------------------------------------

async def stream_reply(
    db: AsyncSession,
    session: LifeContextSession,
    user_message: str,
    settings: AppSettings,
    master_key: bytes,
) -> AsyncIterator[str]:
    """
    Append the user message, stream the AI reply, then append the full
    assistant message once streaming is complete.

    Yields text chunks (str) as they arrive. When the generator is exhausted
    the assistant message has been persisted to the DB.
    """
    # Save the user message first
    await append_message(db, session, "user", user_message, master_key)

    # Build the conversation history as the AI context
    messages = _decode_messages(session.messages_enc, master_key)

    # Determine system prompt (use override if configured)
    existing_context = ""
    current_block = await get_current_block(db, master_key)
    if current_block:
        existing_context = current_block

    if settings.life_context_pre_prompt_enc:
        system_prompt = decrypt(settings.life_context_pre_prompt_enc, master_key)
    else:
        system_prompt = DEFAULT_PRE_PROMPT.format(
            existing_context_block=existing_context or "(none yet)"
        )

    # Format prior messages for the AI (exclude the just-added user message,
    # which we'll pass as the user turn)
    history = messages[:-1]  # everything before the current user message
    history_text = _messages_to_text(history) if history else ""

    user_prompt = (
        f"{history_text}\n\nUser: {user_message}" if history_text
        else user_message
    )

    ai = get_ai_provider(settings, master_key)

    # Stream and collect
    full_response: list[str] = []
    async for chunk in ai.stream(system=system_prompt, user=user_prompt, max_tokens=1024):
        full_response.append(chunk)
        yield chunk

    # Persist the complete assistant message
    await append_message(db, session, "assistant", "".join(full_response), master_key)


# ---------------------------------------------------------------------------
# End session (compress → save new block → archive previous → mark ended)
# ---------------------------------------------------------------------------

async def end_session(
    db: AsyncSession,
    session: LifeContextSession,
    settings: AppSettings,
    master_key: bytes,
) -> LifeContextBlock | None:
    """
    Compress the session into a new LifeContextBlock.

    Steps:
    1. Fetch existing (current) block text for the compression prompt.
    2. Call AI with compression prompt → new block text.
    3. Archive the current block (if any).
    4. Persist new LifeContextBlock (version = previous + 1).
    5. Mark session ended_at + compressed_at.

    Returns the new LifeContextBlock, or None if the session had no user
    messages (in which case the session is simply marked ended with no
    context block update — the AI is NOT called).
    """
    messages = _decode_messages(session.messages_enc, master_key)

    # Guard: never call the AI if the user never actually sent a message.
    # An empty or assistant-only session cannot produce a meaningful context
    # block, and asking the AI to compress nothing causes hallucination.
    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        session.ended_at = _now_iso()
        await db.commit()
        return None

    chat_history_text = _messages_to_text(messages)

    # Fetch existing context block
    existing_block_text = ""
    result = await db.execute(
        select(LifeContextBlock)
        .where(LifeContextBlock.archived.is_(False))
        .order_by(LifeContextBlock.version.desc())
        .limit(1)
    )
    current_block_row = result.scalar_one_or_none()
    if current_block_row:
        existing_block_text = decrypt(current_block_row.context_enc, master_key)

    # Build compression prompt
    compression_user_prompt = _COMPRESSION_PROMPT.format(
        existing_block=existing_block_text or "(empty — this is the first session)",
        chat_history_as_text=chat_history_text,
    )
    compression_system = (
        "You are a precise summarizer. Follow the instructions exactly. "
        "Output only the context block text."
    )

    ai = get_ai_provider(settings, master_key)
    new_context_text = await ai.generate(
        system=compression_system,
        user=compression_user_prompt,
        max_tokens=1500,
    )

    # Enforce 5000-char hard limit
    if len(new_context_text) > 5000:
        new_context_text = new_context_text[:5000]

    # Determine next version number
    next_version = (current_block_row.version + 1) if current_block_row else 1

    # Archive the current block
    if current_block_row:
        current_block_row.archived = True

    # Save new block
    new_block = LifeContextBlock(
        version=next_version,
        created_at=_now_iso(),
        context_enc=encrypt(new_context_text, master_key),
        archived=False,
    )
    db.add(new_block)

    # Mark session ended
    now = _now_iso()
    session.ended_at = now
    session.compressed_at = now

    await db.commit()
    await db.refresh(new_block)
    return new_block


# ---------------------------------------------------------------------------
# Context block queries
# ---------------------------------------------------------------------------

async def get_current_block(db: AsyncSession, master_key: bytes) -> str | None:
    """
    Return the decrypted text of the current (non-archived) context block,
    or None if no block exists yet.
    """
    result = await db.execute(
        select(LifeContextBlock)
        .where(LifeContextBlock.archived.is_(False))
        .order_by(LifeContextBlock.version.desc())
        .limit(1)
    )
    block = result.scalar_one_or_none()
    if block is None:
        return None
    return decrypt(block.context_enc, master_key)


async def get_block_history(db: AsyncSession) -> list[LifeContextBlock]:
    """Return all context blocks (current + archived), newest first."""
    result = await db.execute(
        select(LifeContextBlock).order_by(LifeContextBlock.version.desc())
    )
    return list(result.scalars().all())
