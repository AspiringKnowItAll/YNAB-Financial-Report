# AGENTS.md — Project Specification for AI Coding Agents

This file is the authoritative reference for any AI agent working on this codebase. Read it fully before making any changes. It covers the project's purpose, architecture, conventions, security requirements, and rules that must be followed at all times.

---

## Project Overview

**YNAB Financial Report** is a self-hosted Docker web application that:

1. Connects to the [YNAB API](https://api.ynab.com/) to pull budget and transaction data
2. Stores financial history in a local SQLite database
3. Generates monthly reports with interactive charts and AI-written analysis
4. Serves everything via a browser-accessible web dashboard
5. Optionally delivers reports via email and syncs summaries to Notion

**Intended users:** Non-technical individuals who want insight into their personal finances. The app must be easy to deploy (one `.env` file + `docker-compose up`) and safe to use with sensitive financial data.

**Repo:** https://github.com/AspiringKnowItAll/YNAB-Financial-Report
**License:** MIT

---

## Non-Negotiable Agent Rules

These rules apply to every change made to this codebase, no matter how small. Violating them is not acceptable.

### Rule 1: Documentation Is Always Current
- `README.md` and `AGENTS.md` must be updated **in the same commit** that modifies relevant code.
- Do not defer documentation updates to a later "cleanup pass."
- If you change an API, a configuration option, a data model, or a behavior that is documented anywhere in `docs/`, update that doc file too.
- `docs/configuration.md` must always reflect the exact set of supported `.env` variables and Settings UI options.

### Rule 2: Security and Safety Are the Highest Priority
This app handles personal financial data. These requirements are mandatory:

- **No secrets in code.** API keys, passwords, and tokens must never appear in source files, logs, or error messages. Use `APP_SECRET_KEY` and the `encryption.py` service for all stored secrets.
- **Encrypt all secrets at rest.** Any value stored in the database that is a credential, token, or password must be encrypted with `services/encryption.py` before writing and decrypted only in memory when needed.
- **Validate and sanitize all inputs.** Every user-submitted value must pass through a Pydantic schema at the router boundary before reaching any service layer. See the Input Sanitization section below.
- **No raw SQL.** All database access must use the SQLAlchemy ORM. Parameterized queries are the only acceptable fallback if raw SQL is ever truly required (it shouldn't be).
- **Principle of least privilege.** Services should only have access to the data and capabilities they need. Don't pass full settings objects to services that only need one field.
- **Secure defaults.** TLS should default to enabled for SMTP. Sensitive fields should be masked in the UI (show `••••••••` not the plaintext value). Never log decrypted secret values.
- **Follow established IT security standards.** If there is a well-known, established standard or best practice for something security-related, use it. Do not invent custom cryptography or security patterns.

### Rule 3: Never Assume — Ask First
- If the correct direction is unclear, **stop and ask** before writing code.
- "I don't know" is a valid answer, as long as you then find the correct answer before proceeding.
- Do not guess at the user's intent when it could affect significant amounts of code.
- If a decision the user needs to make would change the direction of a large section of code, surface that decision before writing the code.

### Rule 4: Confirm Before Large Changes
- Small, targeted edits (fixing a bug, updating a field, adding a validation rule) may be made directly.
- Before starting a prolonged coding session or making large structural changes, ask for confirmation.
- If you realize mid-implementation that a user decision would invalidate substantial work already done, stop and ask rather than guessing and continuing.

### Rule 5: Stop at Milestones — Prompt for Git Commit
- When a discrete phase or self-contained unit of work is complete, stop and report what was done.
- Tell the user to commit to the current branch before continuing. Provide a suggested commit message describing what was accomplished.
- Do not continue into the next phase until the user acknowledges the milestone.
- The project is kept in sync on GitHub; clean, descriptive commits at natural breakpoints are required.

### Rule 6: Monitor Context Length — Suggest Compacting or New Chat
- This project is built incrementally across multiple sessions. As a conversation grows long, token usage increases significantly and response quality can degrade.
- When a phase is complete or the conversation has been running for an extended period, note that it is a good time to either use `/compact` (to summarize the current context) or start a fresh chat.
- A new chat session should always begin by reading `AGENTS.md` in full before doing anything else. AGENTS.md is the authoritative source of project state for a new agent session.
- Prefer suggesting a new chat at phase boundaries, not mid-task.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.12 | Strong data/analysis ecosystem, memory-safe, widely understood |
| Web framework | FastAPI (async) | Modern, async-first, automatic validation via Pydantic, great performance |
| Database ORM | SQLAlchemy (async) + aiosqlite | Type-safe DB access, prevents SQL injection, async-compatible |
| Database | SQLite | Zero-config, file-based, ships inside the Docker volume — no external DB needed |
| Key derivation | `argon2-cffi` (Argon2id) | Industry-standard password hashing / KDF; derives encryption key from master password |
| Encryption | `cryptography` (Fernet) | AES-128-CBC + HMAC-SHA256; encrypts secrets at rest; key held in memory only |
| Charts | Plotly | Interactive browser charts; JSON specs generated server-side, rendered client-side |
| Templates | Jinja2 | Server-side HTML rendering; auto-escapes output to prevent XSS |
| PDF export | WeasyPrint | HTML-to-PDF conversion via CSS layout engine |
| Scheduling | APScheduler | In-process async scheduler, integrates cleanly with FastAPI lifespan |
| Email | aiosmtplib | Async SMTP; user-configured server, no hosted infrastructure |
| YNAB sync | httpx (AsyncClient) | Direct YNAB v1 REST API; delta sync via `last_knowledge_of_server` |
| Notion sync | httpx (AsyncClient) | Direct Notion REST API; optional feature |
| Container | Docker + docker-compose | Portable, self-contained deployment |

---

## Architecture

### Request Flow

```
Browser → FastAPI Router
              │
              │ (Pydantic validation + sanitization at boundary)
              ▼
         Service Layer
         ├── ynab_client.py      → YNAB API
         ├── auth_service.py     → master password setup, unlock, recovery codes
         ├── sync_service.py     → SQLite (via ORM)
         ├── analysis_service.py → pure functions, no I/O
         ├── ai_service.py       → AI provider (Anthropic/OpenAI/OpenRouter/Ollama)
         ├── report_service.py   → SQLite (via ORM)
         ├── export_service.py   → WeasyPrint / Jinja2
         ├── email_service.py    → User SMTP server
         └── notion_service.py   → Notion API
              │
              ▼
         SQLite (encrypted secrets, plaintext financial data)
         /data/ volume files (master.salt, master.verify, recovery_keys.json)
```

### First-Run & Auth Flow

On every request, middleware checks this sequence:

1. `/data/master.salt` does not exist → redirect to `/first-run` (master password creation)
2. `app.state.master_key is None` → redirect to `/unlock` (app is locked)
3. `app_settings.settings_complete = False` → redirect to `/settings`
4. `user_profile.setup_complete = False` → redirect to `/setup`
5. Otherwise → pass through to the requested route

### App State

`app.state.master_key: bytes | None` holds the Fernet key in memory. It is `None` when locked and set when the user successfully enters their master password or a recovery code.

### Key Files in Docker Volume (`/data/`)

| File | Contents | Secret? |
|---|---|---|
| `ynab_report.db` | SQLite database with all app data and encrypted secrets | Encrypted |
| `master.salt` | Argon2id salt used to derive the master key | Not secret on its own |
| `master.verify` | Fernet-encrypted known string for password verification | Not secret on its own |
| `recovery_keys.json` | Array of `{salt, wrapped_key, used}` per recovery code | Not secret on its own |

None of these files expose secrets without the master password or a valid recovery code.

### Middleware-Exempt Routes

These routes must always be accessible regardless of auth/setup state:
- `/health`
- `/first-run` and all sub-paths
- `/unlock`
- `/static/`

---

## Directory Structure

```
YNAB-Financial-Report/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md                     ← Keep current
├── AGENTS.md                     ← This file — keep current
├── LICENSE
├── docs/
│   ├── setup.md
│   ├── configuration.md
│   └── development.md
├── requirements.txt
├── app/
│   ├── main.py                   # App factory, lifespan, routers, middleware, app.state.master_key
│   ├── config.py                 # pydantic-settings: PORT, SYNC_DAY_OF_MONTH (no secrets)
│   ├── database.py               # Async engine, session factory, create_all
│   ├── scheduler.py              # APScheduler monthly CronTrigger
│   ├── models/
│   │   ├── settings.py           # AppSettings ORM (encrypted secrets)
│   │   ├── user_profile.py       # UserProfile ORM (wizard answers)
│   │   ├── budget.py             # Budget, CategoryGroup, Category ORM
│   │   ├── transaction.py        # Transaction ORM (core fact table)
│   │   ├── account.py            # Account ORM
│   │   └── report.py             # ReportSnapshot, SyncLog ORM
│   ├── schemas/
│   │   ├── auth.py               # Pydantic input validation for master password + recovery code forms
│   │   ├── settings.py           # Pydantic input validation for settings forms
│   │   ├── ynab.py               # Pydantic models for YNAB API responses
│   │   └── report.py             # Pydantic models for report data
│   ├── services/
│   │   ├── auth_service.py       # Master password setup, Argon2id KDF, unlock, recovery code key-wrapping
│   │   ├── encryption.py         # Fernet encrypt/decrypt using app.state.master_key — never logs plaintext
│   │   ├── ynab_client.py        # YNAB REST client
│   │   ├── sync_service.py       # YNAB → SQLite pipeline
│   │   ├── analysis_service.py   # Pure statistical functions
│   │   ├── ai_service.py         # AIProvider protocol + all implementations
│   │   ├── report_service.py     # Assembles report snapshots
│   │   ├── export_service.py     # HTML + PDF rendering
│   │   ├── email_service.py      # SMTP delivery
│   │   └── notion_service.py     # Notion sync (optional)
│   ├── routers/
│   │   ├── auth.py               # GET/POST /first-run, /unlock, /recovery
│   │   ├── dashboard.py          # GET /
│   │   ├── settings.py           # GET/POST /settings
│   │   ├── setup.py              # GET/POST /setup
│   │   ├── reports.py            # GET /reports, /reports/{id}
│   │   ├── api.py                # POST /api/sync/trigger, test endpoints
│   │   └── export.py             # GET /export/{id}/pdf|html
│   ├── templates/
│   └── static/
├── data/
│   └── .gitkeep                  # Volume mount point; runtime files (*.db, master.salt, etc.) are gitignored
└── tests/
```

---

## Database Conventions

- **All monetary values are stored as YNAB milliunits** (integer, dollars × 1000). Example: $42.50 = `42500`. Conversion to display currency happens only in Jinja2 templates via a custom `milliunit_to_dollars` filter. Never store floating-point dollars.
- **Encrypted fields** use `LargeBinary` column type in SQLAlchemy. The `encryption.py` service handles all encrypt/decrypt operations. Column names for encrypted fields end in `_enc` to make their encrypted status explicit (e.g., `ynab_api_key_enc`).
- **Singleton tables** (`app_settings`, `user_profile`) always use `id = 1`. Upsert on that ID; never insert a second row.
- **Soft deletes via `deleted` flag** on YNAB entities (transactions, categories, accounts) — mirror YNAB's own deletion model. Never hard-delete YNAB data rows.
- **`sync_log`** must always have a row written at the start of a sync (status = "running") and updated at the end (status = "success" or "failed"). Never leave a sync_log row in "running" state permanently.

---

## Security Requirements (Detailed)

### Master Password & Key Derivation

- **No secrets in `.env`**. The `.env` file only contains optional server config (`PORT`, `SYNC_DAY_OF_MONTH`).
- The master password is set by the user in the browser on first run. It is **never stored**. Only a derivation salt and verification token are persisted.
- Key derivation uses **Argon2id** (`argon2-cffi`) with a randomly generated 16-byte salt. The derived 32-byte key is stored in `app.state.master_key` (in memory only) and cleared when the container stops.
- The Argon2id parameters must meet current security recommendations (minimum: `time_cost=3`, `memory_cost=65536`, `parallelism=1`).
- A "verification token" (`/data/master.verify`) is a Fernet-encrypted known string used to verify the password without storing it.
- `auth_service.py` owns all master password logic: setup, unlock verification, recovery code generation, and recovery code use.

### Recovery Codes

- 8 recovery codes are generated after master password setup, each consisting of 4 groups of 5 uppercase alphanumeric characters (e.g., `A3K7B-X9PLQ-2NM4C-WZ8RT`).
- Implementation: **key-wrapping** (LUKS-style). For each recovery code:
  1. Derive a code key from the recovery code + a per-code Argon2id salt
  2. Wrap (Fernet-encrypt) `app.state.master_key` with the code key
  3. Store `{salt, wrapped_key, used: false}` in `/data/recovery_keys.json`
- Using a recovery code: derive code key → unwrap master key → set `app.state.master_key` → mark slot `used: true` → prompt to set a new master password + generate fresh codes
- Used codes must be permanently invalidated (mark `used: true`; never re-activate)
- Recovery codes are shown to the user **exactly once** (at generation time). They are not stored in plaintext anywhere.

### Secrets & Encryption

- All API keys and passwords (YNAB, AI provider, SMTP, Notion) are entered via Settings UI and stored encrypted in `app_settings` using Fernet with `app.state.master_key`.
- `encryption.py` exposes exactly two public functions: `encrypt(plaintext: str) -> bytes` and `decrypt(ciphertext: bytes) -> str`. Both use `app.state.master_key` from `request.app.state`.
- If `app.state.master_key is None` (app is locked), `encrypt()`/`decrypt()` must raise a clear error — never silently fail or return garbage.
- Decrypted values must never be: logged, stored in session state, included in error messages, or returned in API responses.
- In the Settings UI, secret fields must render as password inputs (`type="password"`) and never be pre-populated with their decrypted values. Use a placeholder like `••••••••` to indicate a value is saved.

### Input Sanitization Rules (by field type)

| Field type | Validation rule |
|---|---|
| API keys | Strip whitespace; validate non-empty; max length 512 chars |
| URLs (Ollama base URL, etc.) | Must be a valid HTTP/HTTPS URL via `pydantic.AnyHttpUrl` |
| SMTP hostname | Valid hostname or IP; no path components |
| SMTP port | Integer 1–65535 |
| Email addresses | Valid email format via `pydantic.EmailStr` |
| Free text (notes, goals) | Max 2000 chars; Jinja2 auto-escapes on render (do not manually escape — trust the template engine) |
| Numeric inputs (household size) | Positive integer; reasonable range (e.g., 1–20 for household size) |
| Boolean fields | Use Pydantic `bool` — do not accept arbitrary truthy strings |

### Template Security

- All Jinja2 templates use auto-escaping (enabled globally in `main.py`). Do not use `| safe` filter unless the content is guaranteed to be sanitized server-side HTML.
- AI-generated commentary (markdown from the AI provider) must be rendered via a markdown-to-HTML library with sanitization (e.g., `bleach` after `markdown` conversion), not injected raw.

---

## AI Provider Abstraction

All AI functionality goes through the `AIProvider` protocol defined in `services/ai_service.py`. No service outside `ai_service.py` may import or reference any provider SDK directly.

```python
class AIProvider(Protocol):
    async def generate(self, system: str, user: str, max_tokens: int) -> str: ...
    async def health_check(self) -> bool: ...
```

Supported providers and their `ai_provider` setting values:

| Setting value | Provider | Notes |
|---|---|---|
| `"anthropic"` | Anthropic SDK | Requires `ai_api_key`; model e.g. `claude-sonnet-4-6` |
| `"openai"` | OpenAI SDK | Requires `ai_api_key`; model e.g. `gpt-4o` |
| `"openrouter"` | OpenAI-compatible | Requires `ai_api_key` + `ai_base_url = https://openrouter.ai/api/v1` |
| `"ollama"` | OpenAI-compatible | No API key; requires `ai_base_url` e.g. `http://localhost:11434/v1` |

The `get_ai_provider(settings: AppSettings) -> AIProvider` factory in `ai_service.py` reads the active provider from `app_settings` and returns the correct implementation.

---

## Outlier Detection

Used in `services/analysis_service.py` to prevent one-time large transactions from skewing trend averages.

**Algorithm:** Tukey's IQR fence
- Minimum 5 data points required; fewer → no outliers removed
- `Q1 = 25th percentile`, `Q3 = 75th percentile`, `IQR = Q3 - Q1`
- Upper fence = `Q3 + 1.5 × IQR`, lower fence = `Q1 - 1.5 × IQR`
- **Spending categories:** only upper outliers excluded
- **Income:** only lower outliers excluded

Outlier exclusions must be stored in `report_snapshots.outliers_excluded` (JSON array) and surfaced in the UI with a clear note.

---

## Implementation Status

| Phase | Status | Description |
|---|---|---|
| 1 — Skeleton + Docs | Complete | Project scaffolding, documentation, all stub files |
| 2 — Auth + Settings UI | Complete | Master password setup, unlock, recovery codes, Settings page, encryption, middleware |
| 3 — YNAB Sync | Complete | YNAB API client, sync pipeline, /api/sync/trigger, /api/test/ynab |
| 4 — Profile Wizard | Complete | Personal context wizard (household size, income type, goals, housing, notes) |
| 5 — Dashboard | Complete | 12-month trend chart, category breakdown with IQR-adjusted averages, sync status bar, net worth |
| 6 — AI Reports | Complete | AI provider abstraction (Anthropic/OpenAI/OpenRouter/Ollama), report snapshots, /reports list + detail, /api/report/generate, /api/test/ai |
| 7 — Export | Pending | PDF/HTML export |
| 8 — Email | Pending | SMTP delivery |
| 9 — Scheduler + Notion | Pending | Automated runs, Notion sync |
| 10 — Tests + Hardening | Pending | Test suite, error handling, full docs |

---

## Deferred Features (Post-v1)

Do not implement these until v1 is complete and they are explicitly requested:

- Conversational AI chat interface (ask questions about finances in real-time)
- Per-month user annotations on reports
- Mobile-optimized layout
- Per-category outlier threshold configuration (user-defined IQR multiplier or fixed dollar threshold per category; currently the global Tukey 1.5×IQR fence is applied uniformly)

---

## Updating This File

Update `AGENTS.md` whenever:
- A new service, model, router, or schema is added
- A security requirement is added or changed
- A tech stack decision is made or changed
- A new agent rule is established by the project owner
- The implementation status table changes
- A deferred feature is promoted to active development
