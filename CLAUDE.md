# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## First Step for Every Session

Read `AGENTS.md` in full before making any changes. It is the authoritative specification: architecture, security rules, data conventions, and implementation status. This file is a supplement, not a replacement.

---

## Commands

### Run the app locally
```bash
uvicorn app.main:app --reload --port 8080
```

### Run with Docker (recommended for full-stack testing)
```bash
docker-compose up --build
```

A second Docker instance for testing first-run flow (fresh `/data` volume, port 8083):
```bash
docker-compose -f docker-compose.test.yml up --build
```

### Tests
```bash
pytest                                          # full suite
pytest tests/unit/                              # unit tests only
pytest tests/integration/                       # integration tests only
pytest tests/unit/test_analysis_service.py -v  # single file
pytest --cov=app --cov-report=term-missing      # with coverage
```

No live YNAB API key or running Docker container is required to run any test.

### Lint & format
```bash
ruff check app/ tests/        # lint
ruff check --fix app/ tests/  # auto-fix
ruff format app/ tests/       # format
mypy app/                     # type check
```

All PRs must pass `ruff check` and `mypy` with zero errors.

---

## Agent Workflow Rules

These apply to every coding session — not optional:

- **All code writing → `secure-code-writer` agent.** Never write production code inline in the main conversation. Delegate all implementation work (features, bug fixes, refactors) to the `secure-code-writer` agent.
- **After every code-writing session → `multi-reviewer-synthesis` agent.** Run it before committing. Fix any issues it raises and resubmit until approved, then auto-commit with a detailed message.

---

## Architecture

### Request flow
Every request passes through middleware in `main.py` that enforces a 3-step auth gate before reaching any router:
1. `/data/master.salt` absent → redirect `/first-run`
2. `app.state.master_key is None` → redirect `/unlock`
3. `app_settings.settings_complete = False` → redirect `/settings`

Routes exempt from this gate: `/health`, `/first-run/**`, `/unlock`, `/static/**`. API routes (`/api/**`) are also exempt from steps 2 and 3 so they return JSON errors instead of HTML 302 redirects.

### Jinja2 templates — shared instance required
All routers **must** import the `Jinja2Templates` instance from `app/templates_config.py`. Never create a new instance in a router. The shared instance has `milliunit_to_dollars` filter and autoescape registered. Creating a per-router instance will silently break template filters.

### Database encryption
The entire SQLite database is encrypted at rest using SQLCipher (AES-256). `database.py` substitutes `sqlcipher3` for `sqlite3` in `aiosqlite` and sets `PRAGMA key` via a SQLAlchemy connection event. The DB is completely inaccessible without the master password. `apply_migrations()` and `create_all()` run after unlock (not at startup), because the DB cannot be opened without the key.

### Secret encryption (defense in depth)
`app.state.master_key` (bytes) is the Fernet key, held in memory only. `services/encryption.py` exposes only `encrypt(plaintext: str) -> bytes` and `decrypt(ciphertext: bytes) -> str`. If `master_key` is `None`, both raise — they never silently fail. API keys and passwords in `app_settings` use `LargeBinary` type and an `_enc` name suffix (e.g., `ynab_api_key_enc`) for an additional Fernet encryption layer on top of SQLCipher.

### AI provider abstraction
All AI calls go through the `AIProvider` protocol in `services/ai_service.py`. No router or service outside `ai_service.py` may import Anthropic, OpenAI, or any AI SDK directly. The protocol has five methods:

- `generate()` — batch text generation, used for reports
- `stream()` — SSE token streaming, used for Life Context Chat
- `health_check()` — provider connectivity test
- `list_models()` — enumerate available models
- `vision(image_bytes, prompt)` — PDF page OCR, used by `import_service.extract_via_vision()`

`get_ai_provider()` builds from DB settings; `get_ai_provider_from_params()` builds from plaintext form values (used by the Settings test button without requiring a save first).

### Life Context Chat
The floating chat widget (`static/js/chat_widget.js`) streams AI replies via SSE using `fetch()` + `StreamingResponse`. Sessions are persisted to DB in real time so unfinished sessions survive page navigation. Compression to a `LifeContextBlock` is triggered only by the explicit "End Chat Session" button — never on page close. The decrypted context block text is injected into the AI prompt at report generation time in `report_service.py`.

### External Data Import (Phase 13)
Users upload PDF or CSV financial documents. `import_service.py` extracts data via AI (PDFs use `vision()`, CSVs use `generate()`). The extracted rows go through Pydantic validation (`TransactionRow`/`BalanceRow` schemas) before any ORM insert. Users review and correct results via a chat-style interface before confirming. Confirmed data lands in `ExternalTransaction`/`ExternalBalance` rows (`models/import_data.py`) and is included in AI report prompts. Key constraint: `ImportSession` rows track state through `pending → confirmed/rejected`; never leave a session in `pending` permanently.

### Dashboard Redesign (Phase 14)
Multi-dashboard builder with named dashboards, a left dock, a WYSIWYG `gridstack.js` editor, and 17 widget types. Each dashboard has a configurable column grid; each widget has per-widget filters (time period, accounts, categories). Dashboards and their widget configs are stored in `models/dashboard.py`. Two new routers: `routers/dashboards.py` (page routes) and `routers/api_dashboards.py` (JSON API for the editor). Widget data is served as JSON from `/api/dashboards/widget-data/{type}`.

### Monetary values
All monetary amounts are stored as YNAB milliunits (integer, dollars × 1000). Conversion to display currency happens **only** in Jinja2 templates via the `milliunit_to_dollars` filter. Never store floating-point dollars; never convert in service or router code.

### Schema management
No Alembic. `database.py` provides `create_all()` for new tables and `apply_migrations()` for additive column changes on existing tables. Both run after unlock (not at startup) since the DB requires the master key. Adding a new column to an existing table requires an explicit migration step in `apply_migrations()`.

---

## Key Conventions

- **Button labels use Title Case** on every page (e.g., "Save Settings", "Test Connection").
- **Singleton tables** (`app_settings`) always use `id = 1`. Upsert on that ID; never insert a second row.
- **YNAB entity deletes are soft** — set `deleted = True`, never hard-delete rows.
- **`sync_log`** must always have a "running" row written at sync start and updated to "success" or "failed" at the end. No row may be left permanently in "running" state.
- **`analysis_service.py` is pure** — no DB access, no HTTP calls. All inputs are plain Python objects. Keep it that way.
- **Secrets are decrypted in the service layer**, not in routers. Routers pass opaque settings objects; services call `encryption.decrypt()` only when making an actual external call.
- **Logging** uses Python's `logging` module only — no `print()`. Never log decrypted secret values at any log level.

---

## Documentation Rules (non-negotiable)

Update docs **in the same commit** as the code change — never deferred:

| Change | Required update |
|---|---|
| New `.env` variable | `docs/configuration.md` + `.env.example` |
| New Settings UI field | `docs/configuration.md` |
| New service / router / model | `AGENTS.md` directory structure + description |
| New AI provider | `AGENTS.md` provider table + `docs/configuration.md` |
| Any feature change | `README.md` feature table + `AGENTS.md` implementation status |
| New feature (phase start) | Ask for confirmation before starting — see Agent Rules in `AGENTS.md` |

After completing any phase or self-contained unit of work, stop and tell the user what was done and suggest a git commit with a descriptive message before proceeding.
