# Development Guide

This guide covers setting up a local development environment, understanding the project structure, and contributing to YNAB Financial Report.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Local Development Setup](#2-local-development-setup)
3. [Project Structure](#3-project-structure)
4. [Running Tests](#4-running-tests)
5. [Code Style and Linting](#5-code-style-and-linting)
6. [Working with the Database](#6-working-with-the-database)
7. [Adding a New AI Provider](#7-adding-a-new-ai-provider)
8. [Security Guidelines for Contributors](#8-security-guidelines-for-contributors)
9. [Documentation Requirements](#9-documentation-requirements)
10. [Submitting Changes](#10-submitting-changes)

---

## 1. Prerequisites

- Python 3.12+
- Docker and Docker Compose (for integration testing)
- Git

---

## 2. Local Development Setup

```bash
# Clone the repo
git clone https://github.com/AspiringKnowItAll/YNAB-Financial-Report.git
cd YNAB-Financial-Report

# Create and activate a virtual environment
python -m venv .venv

# On Mac/Linux:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up your .env file
cp .env.example .env
# Edit .env and set APP_SECRET_KEY (generate with the command in .env.example)
```

### Running the app locally (without Docker)

```bash
uvicorn app.main:app --reload --port 8080
```

The `--reload` flag restarts the server automatically when you save a file.

### Running with Docker (recommended for integration testing)

```bash
docker-compose up --build
```

To rebuild only the app container after code changes:
```bash
docker-compose up --build ynab-report
```

---

## 3. Project Structure

See [AGENTS.md](../AGENTS.md) for the full directory structure and explanation of each file's responsibility.

Key entry points:
- [app/main.py](../app/main.py) — FastAPI app factory; start here to understand routing and middleware
- [app/config.py](../app/config.py) — All environment variable loading and validation
- [app/database.py](../app/database.py) — Database engine and session management
- [app/services/](../app/services/) — All business logic; no FastAPI dependencies

### Service layer principles

Services in `app/services/` are the core of the app. They follow these rules:

- **`analysis_service.py` is pure.** No database access, no HTTP calls. All inputs are plain Python objects. This makes it easy to test without mocking.
- **Services receive only what they need.** Don't pass a full `AppSettings` object to a service that only needs an API key.
- **AI provider code lives only in `ai_service.py`.** No other file may import Anthropic, OpenAI, or any AI SDK directly.
- **Encrypted fields are decrypted in the service layer, not in routers.** Routers work with opaque settings objects; services call `encryption.decrypt()` only when making an actual API call.

---

## 4. Running Tests

```bash
# Run the full test suite
ALLOW_PLAINTEXT_DB=1 pytest

# Run with verbose output
ALLOW_PLAINTEXT_DB=1 pytest -v

# Run only unit tests
ALLOW_PLAINTEXT_DB=1 pytest tests/unit/

# Run only integration tests
ALLOW_PLAINTEXT_DB=1 pytest tests/integration/

# Run a specific file
ALLOW_PLAINTEXT_DB=1 pytest tests/unit/test_analysis_service.py -v

# Run with coverage report (requires pytest-cov)
ALLOW_PLAINTEXT_DB=1 pytest --cov=app --cov-report=term-missing
```

> **`ALLOW_PLAINTEXT_DB=1` is required when running tests outside Docker.** The app fails fast at startup if `sqlcipher3-binary` is not installed, which is the normal state on a developer host. Setting this env var tells the app to fall back to the standard unencrypted `sqlite3` library so the tests can run. In the Docker container, `sqlcipher3-binary` is always present and this variable must **not** be set.

### Test structure

```
tests/
├── conftest.py                  # Shared fixtures (master_key, etc.)
├── unit/
│   ├── test_encryption.py       # Fernet encrypt/decrypt
│   ├── test_auth_service.py     # Master password, recovery codes
│   ├── test_analysis_service.py # IQR outlier detection, aggregations
│   ├── test_schemas.py          # All Pydantic input validation schemas
│   ├── test_scheduler.py        # build_trigger, _get_target_month
│   ├── test_database_sqlcipher.py  # SQLCipher fail-fast (ALLOW_PLAINTEXT_DB guard)
│   └── test_security_hardening.py  # Month validation, SSE error non-leakage
└── integration/
    ├── conftest.py              # ASGI test client, salt file fixtures
    └── test_middleware.py       # Auth gate redirect chain
```

### Unit tests

Unit tests cover pure service functions and Pydantic schemas. They use `pytest-asyncio` for async functions and `tmp_path` fixtures to redirect file I/O away from `/data/`. Argon2id parameters are patched to minimal values in auth tests so the full suite runs in under 2 seconds.

### Integration tests

Integration tests use `httpx.ASGITransport` to send requests directly to the FastAPI ASGI app without starting a real server or triggering the lifespan (no database, no scheduler). `app.state` and `os.path.exists` are controlled via fixtures and `monkeypatch` to simulate different auth states.

No live YNAB API key or running Docker container is required to run any test.

---

## 5. Code Style and Linting

The project uses:
- **[Ruff](https://docs.astral.sh/ruff/)** for linting and formatting
- **[mypy](https://mypy.readthedocs.io/)** for static type checking

```bash
# Check linting
ruff check app/ tests/

# Auto-fix linting issues
ruff check --fix app/ tests/

# Format code
ruff format app/ tests/

# Type check
mypy app/
```

All PRs must pass `ruff check` and `mypy` with no errors. There are no exceptions for "I'll fix it later."

### Style conventions

- Use type annotations on all function signatures
- Use `async def` for any function that does I/O (database, HTTP, file)
- Keep functions focused — if a function does more than one thing, split it
- No `print()` statements in production code — use Python's `logging` module
- Log at the appropriate level: `DEBUG` for tracing, `INFO` for normal operations, `WARNING` for recoverable issues, `ERROR` for failures

---

## 6. Working with the Database

### Schema changes

The app uses SQLAlchemy's `create_all()` for schema management (no Alembic migrations in v1). This means:

- **Adding new columns** to an existing table requires a migration strategy for existing databases. Discuss in an issue before implementing.
- **Adding new tables** is safe — `create_all()` will create them on next startup.
- **Renaming or removing columns** is a breaking change. Discuss in an issue before implementing.

### Encrypted columns

Any column storing a secret (API key, password, token) must:

1. Use `Column(LargeBinary)` in the SQLAlchemy model
2. Have a column name ending in `_enc` (e.g., `ynab_api_key_enc`)
3. Be written via `encryption.encrypt()` and read via `encryption.decrypt()`
4. Never appear in logs, error messages, or API responses in decrypted form

### Milliunits

All monetary values from YNAB are stored as integers in milliunits (dollars × 1000). Never store floating-point dollar amounts. Conversion happens only in Jinja2 templates via the `milliunit_to_dollars` template filter.

---

## 7. Adding a New AI Provider

To add a new AI provider:

1. Add a new class in `app/services/ai_service.py` that implements the `AIProvider` protocol:

```python
class MyNewProvider:
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        ...

    async def generate(self, system: str, user: str, max_tokens: int) -> str:
        # Call the provider API and return the full response text
        ...

    async def stream(self, system: str, user: str, max_tokens: int) -> AsyncIterator[str]:
        # Stream tokens one at a time; used by Life Context Chat SSE endpoints
        ...

    async def health_check(self) -> bool:
        # Make a minimal test call; return True if successful
        ...

    async def list_models(self) -> list[str]:
        # Return available model IDs sorted alphabetically
        ...

    async def vision(self, image_bytes: bytes, prompt: str) -> str:
        # Send an image (PNG bytes) + text prompt to the provider; return extracted text.
        # Used by external data import (PDF page extraction).
        # Encode image_bytes as base64 and include in the appropriate content block
        # format for your provider.
        ...
```

2. Add the provider's identifier string to the `AI_PROVIDER_CHOICES` list in `app/schemas/settings.py`

3. Update the `get_ai_provider()` factory function in `ai_service.py` to handle the new provider

4. Add the new provider to:
   - The **AI Provider** dropdown options in `app/templates/settings.html`
   - The provider table in `AGENTS.md`
   - The provider table in `docs/configuration.md`

5. Add unit tests in `tests/unit/test_ai_service.py` with mocked HTTP responses

---

## 8. Security Guidelines for Contributors

Read [AGENTS.md — Security Requirements](../AGENTS.md#security-requirements-detailed) in full before making any changes.

Quick checklist for every PR:

- [ ] No secrets, API keys, or tokens in any source file
- [ ] All new user inputs have Pydantic validation in `app/schemas/`
- [ ] New encrypted fields use `LargeBinary` + `_enc` suffix + `encryption.py`
- [ ] No raw SQL anywhere
- [ ] No `| safe` in Jinja2 templates unless the content is explicitly sanitized
- [ ] AI-generated content is rendered via markdown parser + HTML sanitizer, not raw
- [ ] No new dependencies added without a clear justification in the PR description
- [ ] Logging does not include any decrypted secret values

If you're unsure whether something is secure, ask before implementing it.

---

## 9. Documentation Requirements

Per the project's agent rules, documentation must be updated in the same PR as code changes. This is not optional.

| Change type | Required documentation update |
|---|---|
| New `.env` variable | `docs/configuration.md` and `.env.example` |
| New Settings UI field | `docs/configuration.md` |
| New service or module | `AGENTS.md` (directory structure + description) |
| New AI provider | `AGENTS.md` provider table + `docs/configuration.md` |
| Changed first-run flow | `docs/setup.md` |
| Security requirement added | `AGENTS.md` security section |
| New feature | `README.md` feature table |
| Feature moved to/from deferred | `AGENTS.md` deferred features section + `README.md` roadmap |

---

## 10. Submitting Changes

1. Fork the repository and create a branch from `main`
2. Make your changes following the guidelines above
3. Run `pytest` — all tests must pass with no warnings
4. Update documentation as required
5. Open a pull request with a clear description of what changed and why

### PR description template

```
## What changed
[Brief description of the change]

## Why
[The problem this solves or the feature it adds]

## Testing
[How you tested this — unit tests, manual testing steps, etc.]

## Documentation updated
- [ ] AGENTS.md
- [ ] README.md (if applicable)
- [ ] docs/setup.md (if applicable)
- [ ] docs/configuration.md (if applicable)

## Security checklist
- [ ] No secrets in code
- [ ] Inputs validated via Pydantic
- [ ] No raw SQL
- [ ] No unescaped user content in templates
```
