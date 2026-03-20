# GEMINI.md - YNAB Financial Report

## Project Overview
YNAB Financial Report is a self-hosted, security-first financial dashboard built with FastAPI and Python 3.12. It synchronizes data from the YNAB API, stores it in an encrypted SQLite database, and provides AI-powered insights through various LLM providers (Anthropic, OpenAI, OpenRouter, Ollama).

## Core Architecture
- **Web Framework:** FastAPI (Asynchronous)
- **Database:** SQLite with **SQLCipher** (AES-256 whole-database encryption).
- **ORM:** SQLAlchemy 2.0 (Async) using `aiosqlite`.
- **Security:** Argon2id for key derivation; Fernet for field-level encryption of secrets (API keys, etc.).
- **Frontend:** Jinja2 templates, Vanilla CSS, Plotly.js for interactive charts, Gridstack.js for dashboard management.
- **Task Scheduling:** APScheduler for automated sync and report generation.

## Mandatory Agent Rules (from AGENTS.md)
1. **Documentation Persistence:** Update `README.md`, `AGENTS.md`, and relevant `docs/*.md` in the SAME commit as the code change.
2. **Security First:** 
   - Never log or leak secrets (API keys, decrypted values).
   - All financial data must be encrypted at rest (SQLCipher).
   - All secrets must have a second layer of encryption (Fernet).
   - No raw SQL; use SQLAlchemy ORM exclusively.
3. **Workflow:**
   - Always read `AGENTS.md` at the start of a session.
   - All code writing should ideally be delegated to a specialized sub-agent (as per `CLAUDE.md`).
   - Confirm with the user before large structural changes.
   - Propose a git commit message at natural milestones.
4. **Monetary Values:** Always store as **milliunits** (integers, dollars × 1000). Conversion to display happens ONLY in Jinja2 templates via the `milliunit_to_dollars` filter.

## Key Development Conventions
- **Database Migrations:** No Alembic. Use `apply_migrations()` and `create_all()` in `app/database.py`. These run ONLY after the database is unlocked with the master key.
- **Shared Templates:** Always import `Jinja2Templates` from `app/templates_config.py` to ensure filters are correctly registered.
- **AI Abstraction:** All AI calls MUST go through the `AIProvider` protocol in `app/services/ai_service.py`. Do not import SDKs (Anthropic, OpenAI) elsewhere.
- **Analysis Logic:** `app/services/analysis_service.py` must remain pure (no I/O, no DB access).
- **Soft Deletes:** Use the `deleted` flag for YNAB entities; never hard-delete.

## Build and Test Commands
- **Run App:** `uvicorn app.main:app --reload --port 8080`
- **Docker:** `docker-compose up --build`
- **Tests:** `pytest` (use `ALLOW_PLAINTEXT_DB=1` for environments without native SQLCipher).
- **Lint/Format:** `ruff check app/ tests/`, `ruff format app/ tests/`, `mypy app/`.

## Important Files
- `AGENTS.md`: Authoritative project specification (Read First).
- `CLAUDE.md`: Supplement for agent workflow and command reference.
- `docs/ynab_api_reference.md`: Single source of truth for YNAB API schemas and endpoints.
- `app/main.py`: App entry point, lifespan management, and the 3-step auth gate middleware.
- `app/database.py`: SQLCipher integration and schema migration logic.
- `app/services/encryption.py`: Centralized Fernet encrypt/decrypt logic.
