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
│   ├── scheduler.py              # APScheduler; configurable CronTrigger; auto sync→report→email pipeline
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
│   │   ├── api.py                # POST /api/sync/trigger, /api/report/generate, /api/report/email/{id}, test endpoints
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
    async def health_check(self) -> bool: ...
    async def list_models(self) -> list[str]: ...
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
| 4 — Profile Wizard | Superseded | Personal context wizard (household size, income type, goals, housing, notes) — replaced by Phase 12 Life Context Chat |
| 5 — Dashboard | Complete (v1 scaffold) | 12-month trend chart, category breakdown with IQR-adjusted averages, sync status bar, net worth. Full redesign deferred to Phase 14 after v2 data sources are available. |
| 6 — AI Reports | Complete | AI provider abstraction (Anthropic/OpenAI/OpenRouter/Ollama), report snapshots, /reports list + detail, /api/report/generate, /api/test/ai |
| 7 — Export | Complete | PDF/HTML export via WeasyPrint; standalone HTML with interactive Plotly charts |
| 8 — Email | Complete | SMTP delivery via aiosmtplib; email_service.py, /api/report/email/{id}, /api/test/smtp, Email Report button on report detail |
| 9 — Scheduler | Complete | Configurable automated schedule (daily/weekly/biweekly/monthly/yearly); auto sync → report → email; previous or current month target; locked-app skip with error log; DB migration for new columns |
| 10 — Tests + Hardening | Complete | pytest suite (unit + integration), TemplateResponse deprecation fix, full docs |
| 11 — First-Run Bug Fixes | Complete | Docker build fixes, runtime issues, UX improvements found during first real deployment |
| 12 — Life Context Chat | Planned | Replace profile wizard with AI-driven chat; user tells their financial life story; AI compresses to an encrypted context block injected into reports; versioned, updateable at any time |
| 13 — External Data Import | Planned | Upload PDF/CSV financial documents; AI normalizes to transaction records or balance snapshots; user confirms before saving; included in AI report prompt; optional YNAB account association |
| 14 — Dashboard Redesign | Deferred | Full dashboard redesign after Phase 12 + 13 data sources are in place; will include external accounts, net worth, richer dynamic charts |

---

## Known Issues / Active Work (Phase 11)

These bugs and UX gaps were discovered during the first real end-to-end run of the app and are actively being addressed:

### Bugs Fixed This Phase
- **Dockerfile**: `libgdk-pixbuf2.0-0` renamed to `libgdk-pixbuf-xlib-2.0-0` in Debian Trixie (python:3.12-slim base image)
- **Dockerfile**: Internal container port was driven by `$PORT`, causing a mismatch with docker-compose port mapping. Internal port is now hardcoded to `8080`; `PORT` env var only controls the host-side mapping.
- **docker-compose.yml**: `env_file` now marked `required: false` so the app starts without a `.env` file
- **Middleware**: `/api/*` routes were being redirected to `/settings` or `/setup` with HTML 302s instead of passing through to return JSON errors. API routes are now exempt from Steps 3 and 4 of the auth gate.
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
- `list_models() -> list[str]` added to `AIProvider` protocol and both implementations (`AnthropicProvider`, `OpenAIProvider`). Returns available model IDs sorted alphabetically. Used by the settings page test button.
- `get_ai_provider_from_params(provider_name, api_key, base_url)` factory added to `ai_service.py`. Builds an `AIProvider` from plaintext form values without requiring a DB record or encryption. Used by `/api/test/ai`.

### Known Issues Still To Address

None. All Phase 11 bugs are resolved. Dashboard visual review is deferred to Phase 14 (intentional — see implementation status).

---

## V2 Roadmap (Phases 12–14)

These phases are planned and approved. Implementation begins after a clean v1 commit. See the plan file for full architectural detail.

### Phase 12 — Life Context Chat

**Goal:** Replace the profile wizard with an AI-driven conversational system that lets users build and maintain a "financial life story" — personal context the AI uses to produce more personalized, actionable reports.

**How it works:**
- User opens a chat session and talks freely with the AI about their life situation (employment, family, assets, upcoming events, goals, life changes)
- AI uses a hidden pre-prompt at the start of every session to orient itself (what the conversation is for, what the existing context block contains)
- At the end of the session (or on demand), the AI compresses the conversation into a structured "context block" — an efficient summary stored encrypted in the DB
- Future sessions receive the existing context block so the AI can merge updates, retire stale items, and maintain a coherent picture over time
- Context block is versioned; previous versions archived, current version injected into every AI report prompt
- The pre-prompt is configurable as an advanced setting

**Architectural changes:**
- Remove `/setup` router, setup wizard templates, and `user_profile.py` ORM model
- New DB models: `life_context_sessions` (encrypted chat history), `life_context_block` (encrypted compressed context, versioned)
- New router + template: life context chat page (accessible from nav as "My Financial Profile" or similar)
- Update `main.py` middleware: auth gate Step 4 (wizard check) → replaced with check for whether a context block exists
- Update `report_service.py` to inject context block into AI prompt at report generation time
- Context block hard limit: 5000 characters (AI compresses to fit; limit is on stored block, not on chat messages)

### Phase 13 — External Data Import

**Goal:** Allow users to upload PDF or CSV financial documents from any institution (bank statements, 401k statements, brokerage reports, etc.). The AI normalizes the data into a structured form that feeds into reports.

**How it works:**
- User uploads a file and optionally tells the AI which YNAB account it corresponds to
- File content is sent to the AI with a normalization prompt
- AI identifies the data type and normalizes:
  - **Transaction data** → date, amount (milliunits), description, account name, optional category
  - **Balance/snapshot data** → account name, account type, balance (milliunits), as-of date, optional fields (contribution amount, return %)
- User reviews a confirmation preview of what was extracted before anything is saved
- Normalized data stored in DB; included in AI report prompt at generation time
- File size limits enforced (e.g., 10MB PDF); large files chunked and summarized
- For Ollama users: all processing stays local — highlighted in the UI

**Architectural changes:**
- New DB models: `external_accounts`, `external_transactions`, `external_balances`
- New router: `import_router.py` with `GET /import`, `POST /api/import/upload`, `POST /api/import/confirm`
- New service: `import_service.py` — AI normalization logic, chunking, type detection
- Update `report_service.py` to include external account data and transactions in the AI prompt
- All external data stored in milliunits (same convention as YNAB data)

---

## Deferred Features

Do not implement these until explicitly requested:

- **Dashboard redesign** (Phase 14) — deferred until Phase 12 + 13 data sources are available; dashboard needs to show net worth, external accounts, and richer cross-source charts
- **Notion sync** — `notion_service.py` stub exists; integration deferred
- **Rolling report windows** — "last 30 days" or arbitrary date-range reports; requires pipeline redesign (currently month-based YYYY-MM only)
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
