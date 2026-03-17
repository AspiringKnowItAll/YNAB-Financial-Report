# YNAB Financial Report - Project Context

> **Note:** `AGENTS.md` is the primary authoritative source of truth for this project's architecture, security rules, and implementation status. This document (`GEMINI.md`) and `CLAUDE.md` are secondary references and must always be kept in sync with the core specifications in `AGENTS.md`.

## Project Overview

**YNAB Financial Report** is a self-hosted financial dashboard that syncs with YNAB, tracks spending trends, and generates AI-powered insights.

- **Type:** Python 3.12 / FastAPI (Async)
- **Database:** SQLite (via `aiosqlite` and `SQLAlchemy` asyncio).
- **Security:** Master-password-derived encryption (Argon2id + Fernet/AES).
- **Core Goal:** Provide deep financial insights while keeping sensitive data under the user's control.

---

## Non-Negotiable Agent Rules

1.  **Documentation is Live:** `README.md`, `AGENTS.md`, and `docs/` must be updated in the **same commit** as the code changes.
2.  **Security First:** No secrets in code/logs. Encrypt all credentials at rest using `app.services.encryption`.
3.  **Validation:** Every user input must pass through a Pydantic schema at the router boundary.
4.  **No Raw SQL:** Use SQLAlchemy ORM for all database access.
5.  **Milestones:** Stop and report at discrete phases. Prompt the user for a git commit before proceeding.
6.  **UI Consistency:** Button labels must use **Title Case** (e.g., "Save Settings").

---

## Tech Stack & Architecture

| Layer | Technology |
|---|---|
| **Web** | FastAPI (Async), Jinja2 (Auto-escaping), Vanilla CSS/JS |
| **ORM** | SQLAlchemy 2.0 (Async) + aiosqlite |
| **Security** | Argon2id (KDF), Fernet/AES (Encryption) |
| **Analysis** | Plotly (Charts), WeasyPrint (PDF Export) |
| **AI** | Anthropic, OpenAI, OpenRouter, Ollama (via unified `AIProvider` protocol) |

### Request Flow & Middleware
`Browser → FastAPI Router → Service Layer → SQLite`

**Auth Gate Sequence:**
1. Check `/data/master.salt` (if missing, redirect to `/first-run`).
2. Check `app.state.master_key` (if `None`, redirect to `/unlock`).
3. Check `app_settings.settings_complete` (if `False`, redirect to `/settings`).

**Exempt Routes:** `/health`, `/first-run/*`, `/unlock`, `/recovery`, `/static/*`.

---

## Core Conventions

1.  **Milliunits:** All monetary values are stored as **integers** (dollars × 1000). $42.50 = `42500`. Conversion happens ONLY in templates via the `milliunit_to_dollars` filter.
2.  **Encrypted Fields:** Column names must end in `_enc` (type `LargeBinary`).
3.  **Outlier Detection:** Uses Tukey's IQR fence (1.5x) in `analysis_service.py`. Minimum 5 data points required.
4.  **Soft Deletes:** Use a `deleted` flag for YNAB entities (transactions, categories); never hard-delete.
5.  **Service Isolation:** 
    - `analysis_service.py` is pure (no I/O).
    - `ai_service.py` is the ONLY place AI SDKs are imported.

---

## Security Requirements (Detailed)

### Master Password & Recovery
- **Argon2id Parameters:** `time_cost=3`, `memory_cost=65536`, `parallelism=1`.
- **Master Key:** Derived from the password, held in `app.state.master_key` (memory only).
- **Recovery Codes:** 8 single-use codes using LUKS-style key-wrapping. Stored as `{salt, wrapped_key, used}` in `recovery_keys.json`.

### Secret Handling
- Secrets (API keys, SMTP passwords) are encrypted using Fernet.
- `encryption.py` raises errors if `master_key` is `None` (app locked).
- **NEVER** log, return in API, or pre-populate secret fields in the UI (use `••••••••`).

---

## Building and Running

- **Install:** `pip install -r requirements.txt`
- **Local Dev:** `uvicorn app.main:app --reload --port 8080`
- **Docker:** `docker-compose up -d` (Internal port 8080 is hardcoded; use `PORT` env for host mapping).
- **Tests:** `pytest` (Unit + Integration).
- **Lint/Type:** `ruff check .`, `ruff format .`, `mypy app/`.

---

## Implementation Status (Summary)
- **Phase 1-11:** Core sync, auth, reports, export, and scheduler complete.
- **Phase 12 (Current):** Life Context Chat implemented. Replaced Profile Wizard with AI-driven conversational context.
- **Phase 13 (Planned):** External Data Import (PDF/CSV normalization via AI).
- **Phase 14 (Planned):** Dashboard Redesign.
