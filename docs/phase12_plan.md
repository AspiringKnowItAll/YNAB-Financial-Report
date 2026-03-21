# Phase 12 — Life Context Chat: Detailed Implementation Plan

_Last updated: 2026-03-16. This document is the authoritative design reference for Phase 12. Update it as decisions change. Refer to AGENTS.md for overall project rules and conventions._

---

## Goal

Replace the Phase 4 profile wizard with an AI-driven conversational system that builds and maintains a "financial life story" — personal context the AI injects into every report to produce more personalized, actionable analysis.

---

## Confirmed Design Decisions

### Auth Gate
- **Step 4 (wizard check) is removed entirely.** No forced redirect based on context block existence.
- The existing **Step 3 (`settings_complete` check)** already gates on YNAB + AI provider being configured. That remains — the app is unusable without them.
- Once past Step 3, the user reaches the dashboard freely, even if no context block has ever been created.

### Soft Nudge
- An **amber banner** at the top of the dashboard appears when no current (non-archived) `LifeContextBlock` exists.
- Banner text (approximate): "Your AI reports don't have any personal context yet. [Start your financial profile →]" — clicking opens the floating chat widget.
- Banner disappears once a context block has been created at least once.

### Chat Interface
- **Built from scratch** — custom HTML/CSS/JS chat widget. No third-party chat app or iframe.
- **SSE streaming** — responses stream token-by-token using a `fetch()` POST that reads a `StreamingResponse` body. Feels like ChatGPT/Claude.ai.

### Session Lifecycle
1. User opens the floating widget (or the full profile page).
2. App checks for an **unended session** (`ended_at IS NULL`) in the DB.
   - If found: resume it — reload all existing messages, show a banner inside the chat: "You have an unfinished session. End it when you're done to save your context."
   - If not found: create a new session. AI sends an intro message (see below).
3. Every message (user and AI) is **saved to the DB in real time** as it arrives — the session is never lost on refresh or navigation.
4. User clicks **"End Chat Session"** → compression fires → `LifeContextBlock` is updated → session marked `ended_at = now, compressed_at = now`.
5. If user navigates away mid-session: session persists with `ended_at = NULL` — reloaded next time widget opens.

### Compression
- Triggered **only** when the user explicitly clicks "End Chat Session." Not on page close or navigation.
- `beforeunload` shows a browser warning if the session has uncompressed messages (standard `event.preventDefault()` pattern).
- Sessions have a `compressed_at` timestamp (null = not yet compressed). UI shows a visual indicator if a session exists but has not been compressed.
- Compression calls the AI with the full chat history + existing context block, asking it to merge into a new ≤5000-char block. New block is saved, previous block is archived (not deleted).

### First-Time Intro
- **First session ever (no context block):** A static, hardcoded intro message is displayed as the first AI bubble. It explains what the chat is for, how the context will be used, and offers **3 starter prompts** as clickable chips below the message. No API call needed for the intro.
- **Returning sessions (context block exists):** The AI generates a short personalized opener (streamed, brief — 1–2 sentences + 3 follow-up question chips based on existing context). This costs a small API call but feels alive.

### Floating Widget vs. Full Page
- **Floating widget**: Fixed-position button (bottom-right corner), dashboard page only. Click opens a right-side sliding panel (~420px wide). The panel contains: message list, text input, Send button, "End Chat Session" button.
- **Full page** (`/profile`): Accessible from the nav bar as "My Financial Profile". Shows: current context block text, version history (archived blocks with dates), and a button to open/continue a chat session. This is also where advanced users can edit the pre-prompt.
- The two share the same backend — the full page opens the same chat session as the widget.

### Pre-Prompt
- A default pre-prompt is defined as a constant in `life_context_service.py`.
- An optional `life_context_pre_prompt_enc` field on `AppSettings` allows overriding it.
- Shown in an "Advanced" collapsible section on the Settings page. Not required.

### UserProfile Removal
- `app/models/user_profile.py`, `app/routers/setup.py`, `app/schemas/setup.py`, and `app/templates/setup/setup.html` are **deleted**.
- The `user_profile` DB table is dropped via a migration step in `database.py`.
- `report_service.py` is updated to use `LifeContextBlock` instead of `UserProfile`.

---

## Data Models (`app/models/life_context.py`)

```python
class LifeContextSession(Base):
    __tablename__ = "life_context_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[str] = mapped_column(String(32))          # ISO datetime
    ended_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compressed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    messages_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # messages decrypts to: JSON array of {role: "user"|"assistant", content: str}
```

```python
class LifeContextBlock(Base):
    __tablename__ = "life_context_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)                # Increments per compression
    created_at: Mapped[str] = mapped_column(String(32))          # ISO datetime
    context_enc: Mapped[bytes] = mapped_column(LargeBinary)      # Encrypted text ≤5000 chars
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Current block: archived=False (there is always at most one)
```

---

## AIProvider Protocol Extension (`app/services/ai_service.py`)

Add `stream()` alongside the existing `generate()`:

```python
class AIProvider(Protocol):
    async def generate(self, system: str, user: str, max_tokens: int) -> str: ...
    async def health_check(self) -> bool: ...
    async def list_models(self) -> list[ModelInfo]: ...
    async def stream(self, system: str, user: str, max_tokens: int) -> AsyncIterator[str]: ...
```

- `generate()` is retained for report generation (needs full response before persisting).
- `stream()` is used only by the chat widget.
- All four providers (Anthropic, OpenAI, OpenRouter, Ollama) implement `stream()`.

---

## New Service (`app/services/life_context_service.py`)

Key functions:

| Function | Purpose |
|---|---|
| `get_active_session(db, master_key)` | Return unended session if one exists, else None |
| `create_session(db)` | Create new session row with `created_at` set |
| `get_messages(session, master_key)` | Decrypt and return message list |
| `append_message(db, session, role, content, master_key)` | Add message and re-encrypt |
| `get_intro_messages(db, master_key)` | Return hardcoded first-time intro OR generate AI opener for returning users |
| `stream_reply(session, user_message, settings, master_key)` | Stream AI reply; save assistant message when stream completes |
| `end_session(db, session, settings, master_key)` | Compress → save new `LifeContextBlock` version → archive previous → mark session ended |
| `get_current_block(db, master_key)` | Return decrypted current context block text (or None) |
| `get_block_history(db)` | Return list of all `LifeContextBlock` rows (for profile page) |

---

## New Router (`app/routers/life_context.py`)

| Route | Method | Purpose |
|---|---|---|
| `/profile` | GET | Full-page "My Financial Profile" — current context block + version history |
| `/api/chat/session` | GET | Returns active session ID + messages (for widget init / reload) |
| `/api/chat/message` | POST | Accept `{session_id, content}` → stream AI reply via SSE |
| `/api/chat/end` | POST | Accept `{session_id}` → compress → return `{ok: true}` |

---

## Streaming Protocol

The client sends a POST to `/api/chat/message` with JSON body `{session_id: int, content: str}`.

The server responds with `Content-Type: text/event-stream`. Each chunk is:
```
data: <token text>\n\n
```
Stream ends with:
```
data: [DONE]\n\n
```
On error:
```
data: [ERROR] <message>\n\n
```

Client JS reads the stream using `fetch()` + `ReadableStream` + `TextDecoder`. Tokens are appended to the current AI message bubble. When `[DONE]` is received, the send button is re-enabled.

---

## Modified Files Summary

| File | Change |
|---|---|
| `app/models/life_context.py` | **New** — `LifeContextSession`, `LifeContextBlock` ORM models |
| `app/services/life_context_service.py` | **New** — all chat/context business logic |
| `app/routers/life_context.py` | **New** — chat and profile routes |
| `app/templates/life_context/profile.html` | **New** — full-page profile view |
| `app/static/js/chat_widget.js` | **New** — floating widget JS (open/close, SSE stream, session reload) |
| `app/services/ai_service.py` | Add `stream()` to protocol + all 4 provider implementations |
| `app/services/report_service.py` | Replace `UserProfile` param with `LifeContextBlock`; update `_build_ai_prompt()` |
| `app/main.py` | Remove setup router import; remove Step 4 from middleware; add life_context router |
| `app/database.py` | Migration: drop `user_profile` table; `create_all` handles new tables |
| `app/models/settings.py` | Add `life_context_pre_prompt_enc: LargeBinary \| None` |
| `app/schemas/settings.py` | Add optional `life_context_pre_prompt` field |
| `app/templates/settings.html` | Add pre-prompt textarea in Advanced collapsible section |
| `app/templates/dashboard.html` | Add amber banner (conditional on no context block) + floating chat button |
| `app/templates/base.html` (or nav partial) | Add "My Financial Profile" nav link |
| `app/models/user_profile.py` | **Deleted** |
| `app/routers/setup.py` | **Deleted** |
| `app/schemas/setup.py` | **Deleted** |
| `app/templates/setup/setup.html` | **Deleted** |

---

## Implementation Order

Build the new system before removing the old one so the app stays runnable throughout.

1. **DB models** — `life_context.py`, wire into `database.py`
2. **AIProvider streaming** — `stream()` on protocol + all providers
3. **Life context service** — all business logic
4. **Router + templates** — profile page + chat API endpoints
5. **Floating widget** — `chat_widget.js` + dashboard integration (button + amber banner)
6. **Report service** — swap `UserProfile` → `LifeContextBlock`
7. **Main.py** — remove setup, update middleware, add life_context router
8. **Remove old files** — `user_profile.py`, setup router/schema/template
9. **Settings** — add pre-prompt field
10. **AGENTS.md + docs** — update to reflect Phase 12 complete

---

## Default Pre-Prompt

```
You are a compassionate and knowledgeable personal finance companion.
Your role is to help the user build a "financial life story" — a rich,
personal summary of their financial situation, goals, and life context
that will help generate more personalized and actionable monthly financial reports.

You already have the following context from previous conversations:
{existing_context_block}

Ask open-ended questions about their employment, family situation, major assets
and debts, upcoming life changes, and financial goals. Be warm, curious, and
non-judgmental. After gathering enough context, you will be asked to compress
the conversation into a concise summary.
```

---

## First-Time Intro Message (Static)

Displayed as the first AI message in a brand-new session (no previous context block):

> Hi! I'm here to help build your financial profile — personal context that makes your monthly AI reports much more useful and personalized.
>
> I'll ask you a few questions about your life situation: things like your household, employment, financial goals, and anything else you think is relevant. The more context you share, the better the reports.
>
> Everything you share is encrypted and stored only on your own server. When you're done, click **"End Chat Session"** and I'll compress our conversation into a private context block that gets included in every future report.
>
> To get started, here are a few questions — pick one or just start talking:

Followed by 3 clickable starter chips:
- "Tell me about my household and living situation"
- "What are my main financial goals right now?"
- "Walk me through my income and employment situation"

---

## Context Block Compression Prompt

Sent to the AI when `end_session()` fires:

```
You are updating a personal financial context block.

EXISTING CONTEXT BLOCK (may be empty for a first session):
{existing_block}

NEW CONVERSATION:
{chat_history_as_text}

Your task: Produce a single, compressed context block of no more than 5000 characters.
Merge new information with existing context. Retire any facts that have been superseded.
Preserve concrete facts (household size, income type, employer, debt levels, goals).
Write in third person ("The user..."). Do not include the conversation itself, only the distilled facts.
Output only the context block text — no preamble, no headers, no explanation.
```
