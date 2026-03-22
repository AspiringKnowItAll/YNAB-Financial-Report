# AGENTS.md — Project Specification for AI Coding Agents

This file is the authoritative reference for any AI agent working on this codebase. Read it fully before making any changes. It covers the project's purpose, architecture, conventions, security requirements, and rules that must be followed at all times.

---

## Project Overview

**YNAB Financial Report** is a self-hosted Docker web application that:

1. Connects to the [YNAB API](https://api.ynab.com/) to pull budget and transaction data (see [`docs/ynab_api_reference.md`](docs/ynab_api_reference.md) for the complete endpoint and schema reference)
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
- **Encrypt all financial data at rest.** The SQLite database is encrypted at the file level using SQLCipher (AES-256). The encryption key is derived from the user's master password and held in memory only. The database is completely inaccessible without the master password — there is no plaintext financial data on disk at any time during normal operation. This is non-negotiable.
- **Encrypt all secrets at rest (defense in depth).** In addition to whole-database encryption, API keys, passwords, and tokens stored in `app_settings` receive a second layer of field-level Fernet encryption via `services/encryption.py`. This ensures credentials remain protected even if the database encryption layer is somehow bypassed.
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
| Database | SQLite + SQLCipher | Zero-config, file-based, ships inside Docker volume; entire DB file encrypted with AES-256 via SQLCipher |
| DB encryption | `sqlcipher3-binary` (SQLCipher) | AES-256-CBC whole-database encryption; transparent to queries; key derived from master password |
| Key derivation | `argon2-cffi` (Argon2id) | Industry-standard password hashing / KDF; derives encryption key from master password |
| Secret encryption | `cryptography` (Fernet) | AES-128-CBC + HMAC-SHA256; defense-in-depth layer for API keys/passwords in `app_settings` |
| Charts | Plotly | Interactive browser charts; JSON specs generated server-side, rendered client-side |
| Templates | Jinja2 | Server-side HTML rendering; auto-escapes output to prevent XSS |
| PDF export | WeasyPrint | HTML-to-PDF conversion via CSS layout engine |
| Scheduling | APScheduler | In-process async scheduler, integrates cleanly with FastAPI lifespan |
| Email | aiosmtplib | Async SMTP; user-configured server, no hosted infrastructure |
| YNAB sync | httpx (AsyncClient) | Direct YNAB v1 REST API; delta sync via `last_knowledge_of_server`. See `docs/ynab_api_reference.md` for the full API reference. |
| Notion sync | httpx (AsyncClient) | Direct Notion REST API; optional feature |
| Container | Docker + docker-compose | Portable, self-contained deployment |

---

## Development Commands

Use these as the default local commands when verifying or exploring the app:

### Run the app locally

```bash
uvicorn app.main:app --reload --port 8080
```

### Run with Docker

```bash
docker-compose up --build
```

Use the secondary compose file when you need a clean first-run environment without touching the main `/data` volume:

```bash
docker-compose -f docker-compose.test.yml up --build
```

### Tests

```bash
pytest
pytest tests/unit/
pytest tests/integration/
pytest tests/unit/test_analysis_service.py -v
pytest --cov=app --cov-report=term-missing
```

### Lint, Format, and Type Check

```bash
ruff check app/ tests/
ruff check --fix app/ tests/
ruff format app/ tests/
mypy app/
```

`ruff check` is expected to pass. `mypy app/` is useful, but note that repo-wide pre-existing type-check issues are currently tracked in the Technical Debt section below.

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
         SQLite/SQLCipher (AES-256 encrypted database; field-encrypted secrets in app_settings)
         /data/ volume files (master.salt, master.verify, recovery_keys.json)
```

### First-Run & Auth Flow

On every request, middleware checks this sequence:

1. `/data/master.salt` does not exist → redirect to `/first-run` (master password creation)
2. `app.state.master_key is None` → redirect to `/unlock` (app is locked)
3. `app_settings.settings_complete = False` → redirect to `/settings`
4. Otherwise → pass through to the requested route

> **Note:** Step 4 (wizard check / `user_profile.setup_complete`) was removed in Phase 12. The profile wizard no longer exists. Users reach the dashboard freely once YNAB + AI provider are configured.

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
- `/recovery`
- `/static/`

`/api/*` routes are **not** fully exempt from the auth gate. They still require first-run completion and unlock, but they are exempt from the `settings_complete` redirect so they can return JSON errors instead of HTML 302 responses.

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
│   ├── development.md
│   ├── phase12_plan.md
│   ├── phase13_plan.md
│   ├── phase14_plan.md
│   ├── phase15_plan.md
│   ├── ynab_api_reference.md     ← Authoritative YNAB API reference (endpoints, schemas, enums, auth)
│   ├── YNAB-api-1.json           ← Downloaded OpenAPI source
│   └── YNAB-api-1.yaml           ← Downloaded OpenAPI source
├── requirements.txt
├── app/
│   ├── templates_config.py       # Shared Jinja2Templates instance; filters + autoescape live here
│   ├── main.py                   # App factory, lifespan, routers, middleware, app.state.master_key
│   ├── config.py                 # pydantic-settings: PORT, SYNC_DAY_OF_MONTH (no secrets)
│   ├── database.py               # Async engine, session factory, create_all
│   ├── scheduler.py              # APScheduler; configurable CronTrigger; auto sync→report→email pipeline
│   ├── models/
│   │   ├── settings.py           # AppSettings ORM (encrypted secrets)
│   │   ├── life_context.py       # LifeContextSession, LifeContextBlock ORM (Phase 12)
│   │   ├── import_data.py        # ImportSession, external accounts, external transactions/balances
│   │   ├── dashboard.py          # Dashboard, DashboardWidget, NetWorthSnapshot
│   │   ├── budget.py             # Budget, CategoryGroup, Category ORM
│   │   ├── transaction.py        # Transaction ORM (core fact table)
│   │   ├── account.py            # Account ORM
│   │   └── report.py             # ReportSnapshot, SyncLog ORM
│   ├── schemas/
│   │   ├── auth.py               # Pydantic input validation for master password + recovery code forms
│   │   ├── settings.py           # Pydantic input validation for settings forms
│   │   ├── dashboard.py          # Pydantic input validation for dashboard builder APIs
│   │   ├── ynab.py               # Pydantic models for YNAB API responses
│   │   └── report.py             # Pydantic models for report data
│   ├── services/
│   │   ├── auth_service.py       # Master password setup, Argon2id KDF, unlock, recovery code key-wrapping
│   │   ├── encryption.py         # Fernet encrypt/decrypt using app.state.master_key — never logs plaintext
│   │   ├── settings_service.py   # Decrypted settings helpers for routers (e.g. get_global_custom_css)
│   │   ├── ynab_client.py        # YNAB REST client
│   │   ├── sync_service.py       # YNAB → SQLite pipeline
│   │   ├── analysis_service.py   # Pure statistical functions
│   │   ├── ai_service.py         # AIProvider protocol + all implementations (generate + stream)
│   │   ├── import_service.py     # External data import: extraction, vision OCR, AI normalize, queue processing (SSE), persistence, history
│   │   ├── life_context_service.py  # Life context chat: sessions, streaming, compression (Phase 12)
│   │   ├── report_service.py     # Assembles report snapshots
│   │   ├── widget_service.py     # Dashboard widget data dispatch; DB-only, no HTTP
│   │   ├── export_service.py     # HTML + PDF rendering
│   │   ├── email_service.py      # SMTP delivery
│   │   └── notion_service.py     # Notion sync (optional)
│   ├── routers/
│   │   ├── auth.py               # GET/POST /first-run, /unlock, /recovery
│   │   ├── dashboards.py         # Dashboard HTML routes
│   │   ├── api_dashboards.py     # Dashboard JSON APIs
│   │   ├── settings.py           # GET/POST /settings
│   │   ├── reports.py            # GET /reports, /reports/{id}
│   │   ├── life_context.py       # GET /profile; /api/chat/* endpoints (Phase 12)
│   │   ├── import_data.py        # Import UI + queue endpoints (upload, process SSE, sessions/active, history, cancel, confirm, delete rows, account toggle)
│   │   ├── api.py                # POST /api/sync/trigger, /api/report/generate, /api/report/email/{id}, test endpoints
│   │   └── export.py             # GET /export/{id}/pdf|html
│   ├── templates/
│   │   ├── auth/
│   │   ├── dashboards/
│   │   ├── import/
│   │   ├── life_context/
│   │   ├── partials/
│   │   ├── reports/
│   │   └── settings/
│   └── static/
│       ├── css/
│       └── js/
├── data/
│   └── .gitkeep                  # Volume mount point; runtime files (*.db, master.salt, etc.) are gitignored
└── tests/
```

---

## Database Conventions

- **All monetary values are stored as YNAB milliunits** (integer, dollars × 1000). Example: $42.50 = `42500`. Conversion to display currency happens only in Jinja2 templates via a custom `milliunit_to_dollars` filter. Never store floating-point dollars.
- **Encrypted fields** use `LargeBinary` column type in SQLAlchemy. The `encryption.py` service handles all encrypt/decrypt operations. Column names for encrypted fields end in `_enc` to make their encrypted status explicit (e.g., `ynab_api_key_enc`).
- **Singleton tables** (`app_settings`) always use `id = 1`. Upsert on that ID; never insert a second row.
- **Soft deletes via `deleted` flag** on YNAB entities (transactions, categories, accounts) — mirror YNAB's own deletion model. Never hard-delete YNAB data rows.
- **`sync_log`** must always have a row written at the start of a sync (status = "running") and updated at the end (status = "success" or "failed"). Never leave a sync_log row in "running" state permanently.
- **`ImportSession` lifecycle**: `pending` → `processing` (set atomically before AI work begins) → `reviewing` → `confirmed`. Terminal states: `cancelled`, `failed`. Never leave a session permanently in `pending` or `processing`; the queue restore endpoint maps `processing` back to `pending` to handle server-restart recovery.

---

## Service and Template Conventions

- **Shared Jinja2 instance only.** All routers must import the `Jinja2Templates` instance from `app/templates_config.py`. Never create a per-router template instance; that breaks shared filters and autoescape configuration.
- **`analysis_service.py` is pure.** No DB access, no HTTP calls, no framework objects. Inputs and outputs should stay as plain Python data structures.
- **Secrets are decrypted in the service layer.** Routers should pass opaque settings objects or validated form data. Decrypt only at the point where a service is about to call an external system.
- **Logging uses the `logging` module only.** Do not use `print()`. Never log decrypted secret values at any log level.
- **No Alembic.** New tables belong in `create_all()`. Additive column changes require explicit handling in `apply_migrations()`. Both run only after unlock because the SQLCipher database cannot be opened earlier.

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

### Database Encryption (SQLCipher)

- The SQLite database (`/data/ynab_report.db`) is encrypted at the file level using **SQLCipher** (AES-256-CBC). The encryption key is derived from the user's master password.
- The database is completely inaccessible without the master password. Opening it with a standard `sqlite3` tool returns "file is not a database."
- `database.py` substitutes `sqlcipher3` for Python's `sqlite3` in `aiosqlite` and sets `PRAGMA key` on every new connection via a SQLAlchemy connection event.
- **Lazy initialization:** `apply_migrations()` and `create_all()` run after unlock (not at startup), because the DB cannot be opened without the key. The three entry points are `POST /unlock`, `POST /first-run`, and `POST /recovery`.
- **One-time migration:** On the first unlock after upgrading from a plaintext DB, the app detects the unencrypted file and converts it using SQLCipher's `sqlcipher_export`. This is automatic and transparent to the user.

### Secrets & Encryption (Defense in Depth)

- All API keys and passwords (YNAB, AI provider, SMTP, Notion) are entered via Settings UI and stored with an additional layer of field-level Fernet encryption in `app_settings`, on top of the whole-database SQLCipher encryption. This provides defense in depth.
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

### UI Copy Conventions

- **Button labels must always use Title Case** — capitalize the first letter of every word except short conjunctions (and, or, but) and short prepositions (to, in, of). Examples: "Save Settings", "Test Connection", "Send Test Email", "Save and Continue", "Continue to Settings".
- This rule applies to every button in every template, across all pages and future additions.

### Template Security

- All Jinja2 templates use auto-escaping (enabled globally in `main.py`). Do not use `| safe` filter unless the content is guaranteed to be sanitized server-side HTML.
- AI-generated commentary (markdown from the AI provider) must be rendered via a markdown-to-HTML library with sanitization (e.g., `bleach` after `markdown` conversion), not injected raw.

---

## AI Provider Abstraction

All AI functionality goes through the `AIProvider` protocol defined in `services/ai_service.py`. No service outside `ai_service.py` may import or reference any provider SDK directly.

```python
class AIProvider(Protocol):
    async def generate(self, system: str, user: str, max_tokens: int) -> str: ...
    async def stream(self, system: str, user: str, max_tokens: int) -> AsyncIterator[str]: ...
    async def health_check(self) -> bool: ...
    async def list_models(self) -> list[ModelInfo]: ...
    async def vision(self, image_bytes: bytes, prompt: str) -> str: ...
```

`stream()` yields tokens one at a time as they arrive from the provider. Used by the Life Context Chat SSE endpoints. `generate()` is used for batch report generation. `vision()` accepts raw PNG image bytes and a text prompt; used by `import_service.extract_via_vision()` for PDF page OCR. All AI SDK imports are confined to `ai_service.py`; no other file may import provider SDKs directly.

`get_ai_provider(settings: AppSettings) -> AIProvider` builds a provider from encrypted persisted settings. `get_ai_provider_from_params(provider_name, api_key, base_url)` builds a provider from plaintext form values and is used by connection-test endpoints that should work before a settings save.

Supported providers and their `ai_provider` setting values:

| Setting value | Provider | Notes |
|---|---|---|
| `"anthropic"` | Anthropic SDK | Requires `ai_api_key`; model e.g. `claude-sonnet-4-6` |
| `"openai"` | OpenAI SDK | Requires `ai_api_key`; model e.g. `gpt-4o` |
| `"openrouter"` | OpenAI-compatible | Requires `ai_api_key` + `ai_base_url = https://openrouter.ai/api/v1` |
| `"ollama"` | OpenAI-compatible | No API key; requires `ai_base_url` e.g. `http://localhost:11434/v1` |

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
| 4 — Profile Wizard | Superseded | Personal context wizard (household size, income type, goals, housing, notes) — replaced by Phase 12 Life Context Chat |
| 5 — Dashboard | Complete (v1 scaffold) | 12-month trend chart, category breakdown with IQR-adjusted averages, sync status bar, net worth. Full redesign deferred to Phase 14 after v2 data sources are available. |
| 6 — AI Reports | Complete | AI provider abstraction (Anthropic/OpenAI/OpenRouter/Ollama), report snapshots, /reports list + detail, /api/report/generate, /api/test/ai |
| 7 — Export | Complete | PDF/HTML export via WeasyPrint; standalone HTML with interactive Plotly charts |
| 8 — Email | Complete | SMTP delivery via aiosmtplib; email_service.py, /api/report/email/{id}, /api/test/smtp, Email Report button on report detail |
| 9 — Scheduler | Complete | Configurable automated schedule (daily/weekly/biweekly/monthly/yearly); auto sync → report → email; previous or current month target; locked-app skip with error log; DB migration for new columns |
| 10 — Tests + Hardening | Complete | pytest suite (unit + integration), TemplateResponse deprecation fix, full docs |
| 11 — First-Run Bug Fixes | Complete | Docker build fixes, runtime issues, UX improvements found during first real deployment |
| 12 — Life Context Chat | Complete | Replace profile wizard with AI-driven chat; user tells their financial life story; AI compresses to an encrypted context block injected into reports; versioned, updateable at any time |
| 12.5 — Database Encryption | Complete | SQLCipher whole-database encryption (AES-256); one-time plaintext→encrypted migration; lazy DB init after unlock |
| 13 — External Data Import | Complete | Upload PDF/CSV financial documents; AI normalizes to transaction records or balance snapshots; user reviews + corrects via chat; confirms before saving; external accounts and transactions included in AI report prompt |
| 13.5 — Security Hardening | Complete | All critical/high/medium findings from the 2026-03-17 code audit addressed: vision AIProvider abstraction, TOCTOU lock, Pydantic row validation, get_running_loop fix, SSE error redaction, month validation, non-root Docker user, SQLCipher fail-fast, atomic recovery key write, boolean form parsing. |
| 14 — Dashboard Redesign | M1–M6 Complete; M7 Deferred | Multi-dashboard builder: named dashboards, left dock, WYSIWYG gridstack.js editor, configurable column grid, per-widget filters (time period, accounts, categories), 17 widget types, per-dashboard + global custom CSS, net worth snapshots, projection widgets. M7 (reports integration) scope TBD. Spec: docs/phase14_plan.md |
| 15 — Import Queue Overhaul | Complete | Persistent server-side queue with SSE progress, multi-file upload, per-session review, stop/cancel controls, page-refresh persistence, and a history & account management section. Spec: docs/phase15_plan.md |

---

## Known Issues / Active Work (Phase 12)

These bugs and UX gaps were discovered during the first real end-to-end run of the app and are actively being addressed:

### Bugs Fixed This Phase
- **Dockerfile**: `libgdk-pixbuf2.0-0` renamed to `libgdk-pixbuf-xlib-2.0-0` in Debian Trixie (python:3.12-slim base image)
- **Dockerfile**: Internal container port was driven by `$PORT`, causing a mismatch with docker-compose port mapping. Internal port is now hardcoded to `8080`; `PORT` env var only controls the host-side mapping.
- **docker-compose.yml**: `env_file` now marked `required: false` so the app starts without a `.env` file
- **Middleware**: `/api/*` routes were being redirected to `/settings` or `/setup` with HTML 302s instead of passing through to return JSON errors. API routes now bypass the settings-complete redirect so they can return JSON errors instead.
- **Settings page**: Budget ID was a manual text input requiring the user to copy a UUID from the YNAB URL. Replaced with a dynamic dropdown populated by clicking "Test connection". Budget name is stored in `app_settings.ynab_budget_name` (new column, migration included).
- **Settings router**: Saving settings failed when the YNAB API key field was blank (user not re-entering existing key) because the Pydantic schema required it. API key and budget ID/name are now saved independently.
- **Settings router**: `MissingGreenlet` error after a form validation failure — ORM object was expired after `db.rollback()` and lazily loaded in a sync Jinja2 context. Fixed by re-fetching settings after rollback.
- **Jinja2 filter**: `milliunit_to_dollars` filter was registered only on the `main.py` templates instance, not on the per-router instances. Introduced `app/templates_config.py` as a single shared `Jinja2Templates` instance with all filters registered. All routers now import from it instead of creating their own instances.
- **Budget name not persisting**: For accounts with multiple budgets, the JS `change` event on the budget dropdown was not fired on programmatic selection, so the `ynab_budget_name` hidden field was never populated. Fixed by syncing hidden fields from the current selection after rebuilding the dropdown.
- **Settings page — missing requirements**: No indication that AI provider/model were required. User could save settings without them and get silently looped back. Fixed with: red asterisks on required fields, red-on-blur validation for empty required fields, and a warning banner listing missing requirements shown only after saving incomplete settings.
- **Settings page — AI model selector**: Model name was a free-text field with no guidance. Replaced with a combobox (type-to-filter dropdown) that populates available models from the provider when "Test connection" is clicked. Users can still type any model name manually.
- **Settings page — AI test connectivity**: Test button read from DB, requiring a save before testing. Now reads provider/key/base URL directly from the form fields. Falls back to the saved encrypted API key if the field is blank.
- **Settings page — YNAB test connectivity**: Same fix as AI — test button now reads the API key from the form field, falling back to the saved encrypted key if blank. No save required before testing.
- **Settings page — SMTP test connectivity**: Same fix as AI/YNAB — test button reads all SMTP fields (host, port, username, password, TLS) from the form, falling back to saved values per field.
- **Recovery codes page**: "Continue to settings" button was clickable before the user confirmed saving codes. Now starts disabled/greyed out and only activates when the checkbox is checked.
- **SMTP TLS handling**: `aiosmtplib` always used STARTTLS, which fails on port 465 (implicit TLS) with "Connection already using TLS". Now auto-detects: port 465 → implicit TLS (`use_tls=True`), port 587/other → STARTTLS. Fixed in `email_service.py` (both `send_report_email` and `test_smtp_connection`) and the inline SMTP test in `api.py`.
- **SMTP TLS checkbox fallback**: When the TLS checkbox was unchecked, the form sent an empty string which the server treated as "field absent" and fell back to the saved DB value. Fixed with `is not None` check: an explicit empty string is now correctly read as `False`.
- **SMTP test send**: Added `POST /api/test/smtp/send` endpoint that connects and sends a real test email to `report_to_email`. Added "Send test email" button to the Email Settings section alongside the existing "Test connection" button. Both buttons read from current form fields without requiring a save first.
- **Multiple report recipients**: `report_to_email` now accepts comma-separated email addresses (e.g. `alice@example.com, bob@example.com`). The column was widened to `String(2048)`. The Pydantic schema validates each address individually. `email_service.py` and the test send endpoint split by comma and pass an explicit `recipients` list to aiosmtplib. Live per-address validation added to the settings form.
- **Email settings UX**: Host, port, From address, and Send reports to show red asterisks and are required only when Enable email is checked. Port field has clickable chips for 587 (STARTTLS), 465 (SSL/TLS), and 25 (Unencrypted). Email address fields validate format on blur and clear errors dynamically as the user types valid addresses. All validation clears automatically when email is disabled.

### Settings Page UX Improvements
- **Layout reorder**: YNAB section: token → test button → budget dropdown. AI section: provider → key → base URL → test button → model combobox.
- **Consistent test buttons**: All test buttons now say "Test connection" consistently. YNAB sync button removed from settings (lives on dashboard).
- **Secret field indicators**: Replaced "Current value: ●●●●●●●●" badges with subtle green "✓ Key configured." hints.
- **Email section**: Renamed "Email Delivery" → "Email Settings (optional)" with checkbox text "Enable email" and a description line.
- **Custom dropdown styling**: All `<select>` elements and the model combobox use a consistent custom SVG chevron arrow. Native browser arrows suppressed via `appearance: none`.
- **AI provider conditional fields**: API key field hidden for Ollama (not needed); Base URL field hidden for Anthropic/OpenAI (not needed). Both hidden when no provider is selected. Fields reveal dynamically on provider change.
- **AI provider auto-fill**: Selecting OpenRouter auto-fills Base URL with `https://openrouter.ai/api/v1`; selecting Ollama auto-fills `http://localhost:11434/v1`. Switching providers clears API key, Base URL, model, and status.
- **`docker-compose.test.yml`**: Added for spinning up a clean second container (fresh `/data` volume, port 8083) to test the first-run flow without affecting the primary instance.

### New/Changed Files
- `app/templates_config.py` — Shared Jinja2Templates instance with `milliunit_to_dollars` filter and autoescape enabled. All routers must import from here.

### AI Provider Protocol Change
- `list_models() -> list[ModelInfo]` added to `AIProvider` protocol and both implementations (`AnthropicProvider`, `OpenAIProvider`). Returns `{"id": str, "vision": bool}` dicts sorted by model ID. Used by the settings page test button to populate the model combobox with vision capability indicators.
- `get_ai_provider_from_params(provider_name, api_key, base_url)` factory added to `ai_service.py`. Builds an `AIProvider` from plaintext form values without requiring a DB record or encryption. Used by `/api/test/ai`.

### Phase 12 Changes

- **`app/models/life_context.py`** — New. `LifeContextSession` (encrypted chat history) and `LifeContextBlock` (encrypted compressed context, versioned).
- **`app/services/life_context_service.py`** — New. All chat/context business logic: session management, streaming reply, end-session compression, block versioning.
- **`app/routers/life_context.py`** — New. `GET /profile`, `GET /api/chat/session`, `POST /api/chat/message` (SSE), `POST /api/chat/opener` (SSE), `POST /api/chat/end`.
- **`app/templates/life_context/profile.html`** — New. Full-page "My Financial Profile" view.
- **`app/static/js/chat_widget.js`** — New. Floating chat button + sliding panel. Handles session init/resume, SSE streaming, starter chips, end-session, beforeunload warning.
- **`app/services/ai_service.py`** — Added `stream()` method to `AIProvider` protocol, `AnthropicProvider`, and `OpenAIProvider`.
- **`app/services/report_service.py`** — `_build_ai_prompt()` and `generate_report()` now use `LifeContextBlock` (decrypted context text) instead of `UserProfile`. `profile` param removed from `generate_report()`.
- **`app/routers/dashboard.py`** — Queries `LifeContextBlock` to determine `show_context_nudge`; passes flag to template.
- **`app/templates/dashboard/dashboard.html`** — Added amber nudge banner (conditional on no context block), nav link updated to "My Financial Profile", chat widget script loaded.
- **`app/models/settings.py`** — Added `life_context_pre_prompt_enc: LargeBinary | None`.
- **`app/schemas/settings.py`** — Added `LifeContextSettingsUpdate` schema.
- **`app/routers/settings.py`** — Handles `life_context_pre_prompt` form field; imports `LifeContextSettingsUpdate`.
- **`app/templates/settings/settings.html`** — Added Advanced collapsible section with pre-prompt textarea.
- **`app/database.py`** — `apply_migrations()` adds `life_context_pre_prompt_enc` column to `app_settings` and drops `user_profile` table. `create_all()` registers new models.
- **`app/main.py`** — Removed `setup` router import, removed Step 4 (wizard check) from middleware, added `life_context` router.
- **`app/scheduler.py`** — Removed `UserProfile` dependency; `generate_report()` called without `profile` param.
- **`app/routers/api.py`** — Removed `UserProfile` import and `_get_profile` helper; `generate_report()` called without `profile` param.
- **Deleted**: `app/models/user_profile.py`, `app/routers/setup.py`, `app/schemas/setup.py`, `app/templates/setup/setup.html`.

### Known Issues Still To Address

None. All Phase 12 items are complete. Dashboard visual review is deferred to Phase 14 (intentional — see implementation status).

---

## Phase 12.5 — Database Encryption ✓ Complete

### What Changed

- **`app/database.py`** — Major rewrite. Monkey-patches `aiosqlite.core.sqlite3 = sqlcipher3` at module load. Adds `set_database_key(key)`, `migrate_plaintext_to_encrypted(key)`, and `_on_connect` SQLAlchemy event handler that issues `PRAGMA key` on every connection. `apply_migrations()` and `create_all()` remain exported but are no longer called at startup.
- **`app/main.py`** — Lifespan stripped to `master_key = None` + `start_scheduler(app)`. No DB calls at startup (DB is inaccessible without the key).
- **`app/routers/auth.py`** — All three auth entry points (`POST /first-run`, `POST /unlock`, `POST /recovery`) now call `set_database_key()` → `migrate_plaintext_to_encrypted()` → `apply_migrations()` → `create_all()` after deriving the master key. `post_unlock` also reschedules the APScheduler job once the DB is accessible.
- **`requirements.txt`** — Added `sqlcipher3-binary>=0.5.0`.
- **`tests/unit/test_database_sqlcipher.py`** — New. 10 unit tests covering key storage, idempotent event registration, migration path (sentinel skip, fresh install, already-encrypted detection, plaintext→encrypted with data integrity, failure re-raise), and `_on_connect` PRAGMA behavior.

### Vision Capability Detection

`list_models()` returns `list[ModelInfo]` (TypedDict: `{"id": str, "vision": bool}`). Detection is provider-specific:

- **Anthropic**: all models `vision=True` — all current Anthropic models support vision; no capability metadata in the API.
- **OpenRouter**: `_list_models_openrouter()` calls `{base_url}/models` via httpx and reads `architecture.modality`; `"image"` in the modality string means vision-capable. This is authoritative metadata, not a heuristic.
- **Ollama**: `_list_models_ollama()` calls native `/api/tags` to list models, then fires parallel `/api/show` requests (capped at 10 concurrent via `asyncio.Semaphore`) and checks the `capabilities` array for `"vision"`. This is the same authoritative check used by `check_model_vision_capable()`.
- **OpenAI**: substring heuristic against OpenAI-specific names (`gpt-4o`, `gpt-4-turbo`, `gpt-4-vision`, `o1`, `o3`, `o4-mini`) — OpenAI provides no capability metadata in its models API.

The settings combobox displays a "vision" badge next to capable models.

---

## Phase 13 — External Data Import ✓ Complete

### What Changed

- **`app/models/import_data.py`** — New. Four ORM models: `InstitutionProfile`, `ImportSession`, `ExternalAccount`, `ExternalTransaction`, `ExternalBalance`. All monetary values stored as milliunits. Import session fields (`messages_enc`, `extracted_data_enc`, `file_content_enc`) use Fernet encryption as defense in depth.
- **`app/services/import_service.py`** — New. Key functions: `extract_text()` (PDF via pdfplumber, CSV/TXT direct), `check_model_vision_capable()` (Ollama `/api/show` query; Anthropic/OpenAI assumed capable), `extract_via_vision()` (PDF→PNG→AI vision OCR via pymupdf), `normalize_with_ai()` (structured JSON via AI), `check_file_duplicate()`, `check_row_duplicates()`, `save_confirmed_import()`, `get_institution_profile()`, `save_institution_profile()`, `stream_import_chat()` (SSE streaming with `[DATA_UPDATE]` sentinel pattern). *(Phase 15 added: `process_session_sse()`, `list_active_sessions()`, `list_confirmed_sessions()`, `delete_import_session_rows()`.)*
- **`app/routers/import_data.py`** — New. `GET /import`, `POST /api/import/upload`, `GET /api/import/session/{id}`, `POST /api/import/chat/{id}` (SSE), `POST /api/import/confirm/{id}`, `POST /api/import/cancel/{id}`, `DELETE /api/import/institution/{id}`. *(Phase 15 added: `GET /api/import/process/{id}` SSE, `GET /api/import/sessions/active`, `GET /api/import/history`, `DELETE /api/import/session/{id}/rows`, `PATCH /api/import/account/{id}`.)*
- **`app/templates/import/import.html`** — New. Three-state UI (upload → review → confirmed). Drop zone, institution profile selector, extracted rows table, chat panel with `[DATA_UPDATE]` table refresh, confirm panel with account name/type and institution memory checkbox.
- **`app/static/js/import.js`** — New. File drop zone, upload via `fetch()`+`FormData`, SSE chat handling, `[DATA_UPDATE]` table refresh, duplicate warning display.
- **`app/services/report_service.py`** — Queries active `ExternalAccount` rows with latest `ExternalBalance` + `ExternalTransaction` rows for the report month; formats as structured text block injected into AI prompt via `_build_external_data_text()`.
- **`app/main.py`** — Registered `import_data` router.
- **`app/database.py`** — Registered new models in `create_all()`.
- **`app/templates/dashboard/dashboard.html`** — Added Import button next to Sync Now.
- **`requirements.txt`** — Added `pdfplumber>=0.11.0`, `pymupdf>=1.24.0`.

### Known Issues / Limitations

**Post-completion bug fix (2026-03-21):** `extract_text()` called `pdfplumber.open(stream=file_bytes)` with raw `bytes`; pdfplumber requires a file-like object. Fixed by wrapping with `io.BytesIO(file_bytes)`. This caused all PDF uploads to fail immediately before the vision fallback was ever reached.

A two-reviewer code audit (Codex, Claude) was completed on 2026-03-17. Findings are catalogued in `code-review-summary.md`. All critical, high, and medium findings are addressed in Phase 13.5. Low/informational findings are tracked in the Deferred Features section.

---

## V2 Roadmap (Phases 12–15)

Phases 12, 12.5, 13, 13.5, and 15 are complete. Phase 14 (Dashboard Redesign) Milestones 1–6 are complete; M7 (reports integration) is deferred pending scope definition. See the implementation status table and [`docs/phase14_plan.md`](docs/phase14_plan.md).

### Phase 12 — Life Context Chat ✓ Complete

> **Implemented. Full specification in [`docs/phase12_plan.md`](docs/phase12_plan.md).**

**Goal:** Replace the profile wizard with an AI-driven conversational system that lets users build and maintain a "financial life story" — personal context the AI uses to produce more personalized, actionable reports.

**Confirmed design decisions (summary — see plan doc for full detail):**

- **Auth gate:** Step 4 (wizard check) is removed entirely. No forced redirect based on context block. App is reachable at the dashboard once YNAB + AI provider are configured (Step 3 unchanged).
- **Soft nudge:** Amber banner at top of dashboard when no context block exists yet.
- **Streaming:** SSE via `fetch()` + `StreamingResponse`. `stream()` method added to `AIProvider` protocol (alongside existing `generate()`).
- **Chat UI:** Built from scratch — custom HTML/CSS/JS floating widget. No third-party app or iframe.
- **Session persistence:** Messages saved to DB in real time. Unended sessions reload when the widget is reopened (survive navigation/refresh). `beforeunload` warns if an uncompressed session exists.
- **Compression trigger:** Explicit "End Chat Session" button only — not on page close.
- **First-time intro:** Static hardcoded message + 3 clickable starter prompt chips (no API call). Returning sessions get a short AI-generated personalized opener.
- **Widget placement:** Floating button bottom-right, dashboard page only. Slides open a right-side panel (~420px).
- **Full profile page:** `/profile` — accessible from nav ("My Financial Profile"). Shows current context block, version history, and opens/continues chat.
- **Pre-prompt:** Default constant in `life_context_service.py`; optional override via `life_context_pre_prompt_enc` on `AppSettings`.
- **UserProfile removal:** `user_profile.py`, `routers/setup.py`, `schemas/setup.py`, `templates/setup/setup.html` deleted. DB table dropped via migration.

**Architectural changes:**
- Delete `app/models/user_profile.py`, `app/routers/setup.py`, `app/schemas/setup.py`, `app/templates/setup/`
- New DB models: `LifeContextSession` (encrypted chat history), `LifeContextBlock` (encrypted compressed context, versioned) in `app/models/life_context.py`
- New service: `app/services/life_context_service.py`
- New router: `app/routers/life_context.py` — `/profile`, `/api/chat/session`, `/api/chat/message` (SSE), `/api/chat/end`
- New templates: `app/templates/life_context/profile.html`
- New JS: `app/static/js/chat_widget.js`
- Update `app/services/ai_service.py`: add `stream()` to `AIProvider` protocol and all 4 implementations
- Update `app/services/report_service.py`: replace `UserProfile` with `LifeContextBlock` in `_build_ai_prompt()`
- Update `app/main.py`: remove setup router, remove Step 4 from middleware, add life_context router
- Update `app/models/settings.py`: add `life_context_pre_prompt_enc` field
- Context block hard limit: 5000 characters

### Phase 13 — External Data Import ✓ Complete

> **Implemented. Full specification in [`docs/phase13_plan.md`](docs/phase13_plan.md).**

**Goal:** Allow users to upload PDF or CSV financial documents from any institution (bank statements, 401k statements, brokerage reports, etc.). The AI normalizes the data into a structured form that feeds into reports.

See the Phase 13 section above for a full list of changed files.

---

### Phase 13.5 — Security Hardening (Complete)

**Goal:** Address all critical, high, and medium findings from the 2026-03-17 code audit (`code-review-summary.md`). One item is an **architectural fix** (vision AIProvider abstraction) that must be resolved before Phase 14 to prevent the violation from propagating into new AI-facing features.

#### Milestone 1 — Architectural Fix (prerequisite for Phase 14)

- **`app/services/import_service.py` + `app/services/ai_service.py`** — Add a `vision(image_bytes: bytes, prompt: str) -> str` method to the `AIProvider` protocol and all provider implementations (`AnthropicProvider`, `OpenAIProvider`). Refactor `extract_via_vision()` in `import_service.py` to call `provider.vision()` instead of importing provider SDKs directly. This resolves the architecture rule violation identified by Claude.

#### Milestone 2 — Critical & High Security Fixes

- **`app/services/auth_service.py`** — Wrap the `use_recovery_code()` read-check-write sequence with a `threading.Lock` to eliminate the TOCTOU race condition (CRIT-1).
- **`app/services/import_service.py`** — Add Pydantic schema validation (`TransactionRow`, `BalanceRow`) for all AI-returned row data before any ORM insert in `save_confirmed_import()`. Validate: date is a valid ISO date string, `amount_milliunits` is an integer, description is a non-null string ≤512 chars, `return_bps` is in a plausible range (HIGH-1).
- **`app/services/export_service.py`** — Replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()` (HIGH-3, Python 3.12 correctness).
- **`app/routers/life_context.py`, `app/routers/import_data.py`, `app/routers/api.py`, `app/services/report_service.py`** — Replace all `str(exc)` in user-facing SSE yields, JSON responses, and stored AI commentary with a generic error message. Log full exceptions server-side only (HIGH-5 / Codex HIGH-1).

#### Milestone 3 — Medium Security & Correctness Fixes

- **`app/routers/api.py`** — Strengthen month parameter validation: use `datetime.strptime(month, "%Y-%m")` and return HTTP 400 on `ValueError` (MED-2 / Codex Medium). Fixes downstream `_last_n_months` edge case in `report_service.py` (MED-3).
- **`Dockerfile`** — Add a non-root user and `USER` instruction. Set `/data` volume permissions appropriately (MED-8).
- **`app/templates/reports/report_detail.html`** — Fix dead `/setup` nav link — update to `/profile` (Codex Medium).
- **`app/database.py`** — Fail fast (raise + clear error) if `sqlcipher3-binary` is unavailable in a non-test environment. Gate any plaintext fallback behind an explicit env flag (`ALLOW_PLAINTEXT_DB=1`) for tests only (Codex Medium).
- **`app/services/auth_service.py`** — Use atomic write for `recovery_keys.json`: write to a temp file and call `os.replace()` (LOW-2).
- **`app/routers/settings.py`** — Standardize boolean form field parsing to explicit `== "1"` comparison for all checkbox/boolean fields (Codex Low).

#### Milestone 4 — Test Fixes

- **`tests/unit/test_auth_service.py`** — Replace `asyncio.get_event_loop().run_until_complete()` with `async`/`pytest-asyncio` pattern (LOW-3).
- Add tests for: invalid month values returning HTTP 400; SSE error paths not including raw exception text in the yielded event.

---

### Phase 14 — Dashboard Redesign (M1–M6 Complete; M7 Deferred)

> **Full specification in [`docs/phase14_plan.md`](docs/phase14_plan.md).**

**Goal:** Replace the static single-page dashboard with a multi-dashboard builder system. Users create multiple named dashboards, each with independently configurable widgets laid out on a drag-resize-snap grid (gridstack.js, MIT license). All widget filters — time period, included accounts (YNAB + external), excluded categories — are per-widget for maximum flexibility.

**Key features:**
- Named dashboards with a persistent left dock for quick switching; user-selectable default
- WYSIWYG edit mode: drag/resize/snap to configurable column grid (6/8/12/16/24 columns)
- Dashboard-level default time period (convenience; each widget overrides freely)
- 17 widget types: summary cards, trend charts, breakdowns, stats tables, projection charts — all user-selectable
- Per-widget configuration: time period, account scope, category exclusions
- Per-dashboard custom CSS (unencrypted, stored in `Dashboard.custom_css`)
- Global custom CSS (Fernet-encrypted, stored in `AppSettings.custom_css_enc`)
- Net worth history via `NetWorthSnapshot` table — one row written per sync
- Savings/investment projection widgets (uses `AppSettings.projection_expected_return_rate`)

**New files:**
- `app/models/dashboard.py` — Dashboard, DashboardWidget, NetWorthSnapshot
- `app/routers/dashboards.py` — HTML routes
- `app/routers/api_dashboards.py` — API routes (CRUD + widget data endpoint)
- `app/schemas/dashboard.py`
- `app/services/widget_service.py` — widget data dispatch (DB only, no HTTP)
- `app/templates/dashboards/` — dashboard_list, dashboard_view, dashboard_edit, dashboard_new, partials/
- `app/static/css/dashboard.css`
- `app/static/js/dashboard_view.js`
- `app/static/js/dashboard_builder.js`
- `app/static/js/vendor/gridstack/` (MIT license — copyright notice MUST be preserved in file header)

**Modified files:**
- `app/models/settings.py` — `custom_css_enc`, `projection_expected_return_rate`, `projection_retirement_target`
- `app/database.py` — new models in `create_all()`; migrations for new tables + new AppSettings columns
- `app/main.py` — register new routers; remove old `dashboard.py` router; update `/` redirect
- `app/routers/dashboard.py` — **DELETED** (replaced by `dashboards.py`)
- `app/services/sync_service.py` — write `NetWorthSnapshot` on each successful sync
- `app/templates/base.html` — global CSS injection
- `app/templates/settings/settings.html` — Appearance section (M6) + Financial Projections section (M5)
- `app/routers/settings.py` — handle new AppSettings fields

**Milestones:** M1 Foundation ✓ → M2 Builder (gridstack) ✓ → M3 Existing Widgets ✓ → M4 New Widgets ✓ → M5 Projections ✓ → M6 Global CSS ✓ → M7 Reports Integration (Deferred — scope TBD)

### Milestone 3 — Widget Library: Existing Widgets ✓ Complete

**What Changed:**

- **`app/services/widget_service.py`** — Full implementation (was a stub). Implements `get_widget_data()` which dispatches on `widget_type`, parses `config_json` (time period, account filter, category exclusions), loads transactions/categories/accounts from the DB, runs `analysis_service` functions, and returns widget-type-specific JSON. Plotly figure dicts returned directly (not HTML-escaped strings) so the JS layer calls `Plotly.newPlot()` directly. Includes time-period resolution helpers supporting all 8 period types (last_month through all_time plus custom date ranges).
- **`app/static/js/dashboard_view.js`** — Full replacement. Dispatches to `renderCardWidget` (formatted dollar value + period label, color-coded by type) or `renderPlotlyWidget` (Plotly chart in responsive container). Updates widget header title from server response (honouring `title_override` in config). Includes `escapeHtml` for XSS-safe innerHTML and `formatMilliunits` for client-side currency formatting.
- **`app/static/css/dashboard.css`** — Added M3 styles: `.widget-body--card` / `.widget-card-content` / `.widget-card-value` / `.widget-card-period` for card layout; `.widget-value--income/spending/positive/negative` colour variants; `.widget-body--chart` / `.widget-plot` for responsive Plotly containers.
- **`app/templates/dashboards/dashboard_view.html`** — Added Plotly CDN script tag (`plotly-2.35.2.min.js`) to `extra_head` block.

**Implemented widget types (M3):**

| Type | Kind | Description |
|---|---|---|
| `income_card` | Card | Total income (categorised inflows) for the configured period |
| `spending_card` | Card | Total spending (categorised outflows) for the configured period |
| `net_savings_card` | Card | Net = income − spending; green when positive, red when negative |
| `net_worth_card` | Card | Current sum of on-budget YNAB account balances; not time-period filtered |
| `income_spending_trend` | Chart (Plotly) | Grouped bar chart: income vs. spending per calendar month |
| `category_breakdown` | Chart (Plotly) | Horizontal bar overlay: this-month spending vs. IQR-adjusted monthly average |

**gridstack.js attribution:** MIT license. Copyright (c) 2021-present Alain Dumesny, Dylan Weiss, Lyor Goldstein. Copyright notice must be preserved in `app/static/js/vendor/gridstack/gridstack.all.js` header. No UI attribution required.

---

### Milestone 4 — Widget Library: New Widgets ✓ Complete

**What Changed:**

- **`app/services/widget_service.py`** — Added 9 new widget type builders and updated the main dispatcher. Also added new DB loaders (`_load_accounts`, `_load_account_name_map`, `_load_net_worth_snapshots`, `_load_external_accounts_with_balances`, `_load_external_balances_in_range`) and helper functions (`_parse_account_ids`, `_parse_excluded_category_ids`). Added `payee_name` to the dict returned by `_load_transactions`. Key correctness fixes: `ytd` time period now handles January correctly (falls back to `today` as end date when no complete month exists); `_load_external_balances_in_range` deliberately omits a lower-bound date filter so external balances recorded before the widget period are available for the "latest on or before" net worth trend lookup.
- **`app/static/js/dashboard_view.js`** — Added renderers for all 9 new widget types: `renderSavingsRateCard` (% formatting), `renderCategoryStatsTable`, `renderAccountBalancesList`, `renderRecentTransactions`. Updated `renderWidget` dispatch to route all 15 widget types.
- **`app/static/css/dashboard.css`** — Appended M4 styles: `.widget-body--table`, `.widget-stats-table` + wrap (category stats), `.widget-accounts-list` (account balances), `.widget-transactions-list` + wrap (recent transactions), `.txn-amount--positive/negative`, `.txn-col-amount`.

**Implemented widget types (M4):**

| Type | Kind | Description |
|---|---|---|
| `savings_rate_card` | Card | Savings rate % (income − spending) / income for the period |
| `net_worth_trend` | Chart (Plotly) | Net worth over time: YNAB `NetWorthSnapshot` + `ExternalBalance` history combined |
| `savings_rate_trend` | Chart (Plotly) | Savings rate % per calendar month line chart |
| `group_rollup` | Chart (Plotly) | Spending by category group; bar (default) or donut via `chart_type` config |
| `payee_breakdown` | Chart (Plotly) | Top N spending payees horizontal bar chart; N configurable via `top_n` (1–30) |
| `month_over_month` | Chart (Plotly) | Grouped bar chart: income + spending per month, with net savings dotted line overlay |
| `category_stats_table` | Table (HTML) | Per-category avg / min / max / peak month / months-with-data |
| `account_balances_list` | List (HTML) | YNAB accounts + external accounts with current balances; grand total row |
| `recent_transactions` | Table (HTML) | Most recent N transactions (date-desc); N configurable via `limit` (5–100) |

---

## Phase 15 — Import Queue Overhaul ✓ Complete

> **Full specification in [`docs/phase15_plan.md`](docs/phase15_plan.md).**

**Goal:** Redesign the `/import` page around a persistent server-side queue. Upload stores the file immediately (no blocking AI call); processing happens separately via SSE with per-stage progress events. Multiple files can be queued and processed sequentially. A history section shows confirmed imports with per-session delete-rows and per-account deactivate controls.

### New / Updated Endpoints

| Method | Path | Change | Purpose |
|---|---|---|---|
| `POST` | `/api/import/upload` | Updated | File storage only; no AI; returns `{session_id}` immediately |
| `GET` | `/api/import/process/{id}` | New | SSE stream: extract text + AI normalize, yield stage events |
| `GET` | `/api/import/sessions/active` | New | Returns all `pending`+`reviewing`+`failed` sessions for queue restore |
| `GET` | `/api/import/history` | New | Returns confirmed sessions + ExternalAccount list with row counts |
| `DELETE` | `/api/import/session/{id}/rows` | New | Hard-deletes ExternalTransaction + ExternalBalance rows for that session |
| `PATCH` | `/api/import/account/{id}` | New | Toggle `is_active` on ExternalAccount |
| `POST` | `/api/import/cancel/{id}` | Unchanged | Cancel pending/processing session |

### New Service Functions (`import_service.py`)

- `process_session_sse(session_id, db, settings, master_key)` — async generator; yields JSON SSE progress events; does extraction + vision (per-page) + normalization; updates session to `"reviewing"` on success or `"failed"` on error
- `list_active_sessions(db)` — returns pending/reviewing/failed sessions for queue restore
- `list_confirmed_sessions(db, master_key)` — returns confirmed sessions with row counts and account info
- `delete_import_session_rows(session_id, db)` — hard-deletes ExternalTransaction + ExternalBalance rows; preserves ImportSession as audit trail

### No Schema Migrations

Existing `ImportSession.status`, `ImportSession.file_content_enc`, and `ExternalAccount.is_active` columns are sufficient — no new columns or tables required.

---

## Deferred Features

Do not implement these until explicitly requested:
- **Notion sync** — `notion_service.py` stub exists; integration deferred
- **Rolling report windows** — "last 30 days" or arbitrary date-range reports; requires pipeline redesign (currently month-based YYYY-MM only)
- Per-month user annotations on reports
- Mobile-optimized layout
- Per-category outlier threshold configuration (user-defined IQR multiplier or fixed dollar threshold per category; currently the global Tukey 1.5×IQR fence is applied uniformly)

### Technical Debt (from 2026-03-17 code audit — low/informational findings)

These are correctness, performance, and hygiene items that carry no architectural risk if deferred. Address opportunistically or in a future maintenance pass:

- **N+1 query optimization** — `check_row_duplicates` in `import_service.py` issues one DB query per row; `generate_report` in `report_service.py` issues one query per external account for latest balance. Batch-load instead. (`code-review-summary.md` HIGH-2/LOW N+1)
- **`[DATA_UPDATE]` prompt injection sentinel** — Replace bracket-form `[DATA_UPDATE]...[/DATA_UPDATE]` with null-byte or GUID-based delimiter to prevent crafted document content from triggering the data-update parser. (`code-review-summary.md` MED-5)
- **Auth gate DB query caching** — Once the app is unlocked and settings are confirmed, cache `settings_complete` in `app.state` to avoid a DB round-trip on every request. (`code-review-summary.md` LOW-8)
- **Pin dependency versions** — Generate a `requirements-frozen.txt` with exact pins for reproducible Docker production builds. (`code-review-summary.md` LOW-5)
- **`_milliunit_to_dollars` duplication** — Three identical copies exist in `templates_config.py`, `export_service.py`, and `report_service.py`. Consider extracting to a shared utility to eliminate drift risk. Sign formatting is now consistent across all three.
- **`check_row_duplicates` UTF-8 validation scope** — Magic-byte upload check validates only the first 512 bytes; `extract_text()` uses `errors="replace"` on the full payload. Validate the full file or document as a heuristic.
- **`Content-Disposition` RFC 6266 fallback** — `export.py` uses `filename*=UTF-8''...` without a legacy `filename=` fallback. In practice `snapshot.month` is always a safe `YYYY-MM` string, making this theoretical.
- **Repo-wide `mypy` errors** — `mypy app` reports pre-existing errors (sqlcipher3 stub, bleach/markdown/weasyprint stubs, api_dashboards grid attrs, ai_service union-attr). These pre-date Phase 14 but should be addressed in a hardening pass.
- **~~Missing sync button on main dashboard~~** — Fixed.
- **~~Inconsistent nav bar across pages~~** — Fixed.
- **~~`milliunit_to_dollars` sign placement~~** — Fixed in `templates_config.py`, `export_service.py`, and `report_service.py`. Negatives now render as `-$1,234.56`.
- **~~Dashboard transaction memory bound~~** — Fixed: widget queries capped at 24 months; `all_time` period now floors at 24 months.
- **~~`check_row_duplicates` near-match bug~~** — Fixed: first near-match is kept; loop exits early on exact match.
- **~~MIME magic-byte validation~~** — Fixed: `%PDF` prefix check for PDFs; UTF-8 decode check for CSV/TXT in upload handler.
- **~~`apply_migrations` comment~~** — Fixed: security comment added to `_new_columns` in `database.py`.
- **~~`Content-Disposition` filename sanitization~~** — Fixed: `urllib.parse.quote()` with RFC 5987 `filename*=` in `export.py`.
- **~~SMTP logic deduplication~~** — Fixed: `/api/test/smtp` and `/api/test/smtp/send` delegate to `email_service.test_smtp_connection_from_params()` and `email_service.test_smtp_send_from_params()`.
- **~~Double `AppSettings` fetch on dashboard view~~** — Fixed: single query in `dashboard_view`; `get_global_custom_css_from_settings()` helper added to `settings_service.py`.
- **~~`nav.html` missing `aria-current="page"`~~** — Fixed.

---

## Updating This File

Update `AGENTS.md` whenever:
- A new service, model, router, or schema is added
- A security requirement is added or changed
- A tech stack decision is made or changed
- A new agent rule is established by the project owner
- The implementation status table changes
- A deferred feature is promoted to active development
