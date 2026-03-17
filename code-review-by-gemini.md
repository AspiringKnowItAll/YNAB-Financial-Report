# Code Review by Gemini

**Date:** Tuesday, March 17, 2026
**Reviewer:** Gemini CLI (Senior Software Engineer)
**Scope:** YNAB Financial Report Repository

## Executive Summary

The **YNAB Financial Report** codebase is a high-quality, production-ready implementation of a self-hosted financial dashboard. It demonstrates a strong commitment to security, data integrity, and modern asynchronous Python patterns. The architecture is well-decoupled, and the implementation strictly adheres to the mandates laid out in `AGENTS.md`.

## 1. Security & Safety

### 1.1 Encryption Architecture
The project employs a robust "Zero-Knowledge" security model:
- **Whole-Database Encryption:** Uses SQLCipher (AES-256) to encrypt the SQLite database at the file level.
- **Field-Level Encryption (Defense in Depth):** Sensitive fields (API keys, SMTP passwords) are additionally encrypted using Fernet (AES-128-CBC + HMAC-SHA256) via `app/services/encryption.py`.
- **Key Management:** The encryption key is derived from the user's master password using Argon2id and is held only in memory (`app.state.master_key`). It is never persisted to disk.
- **Recovery Codes:** Implements a LUKS-style key-wrapping mechanism for 8 single-use recovery codes, providing a safe fallback without compromising the master key's security.

### 1.2 Authentication & Authorization
- **Auth Gate Middleware:** The `auth_gate` in `app/main.py` effectively enforces the three-step setup/unlock/settings sequence.
- **Exempt Routes:** Correctly excludes health checks, static files, and the unlock flow from the auth gate.
- **No Secrets in Source:** API keys and credentials are never hardcoded. They are entered via the UI and stored encrypted.

### 1.3 Input Validation
- **Pydantic Boundary:** Every router uses Pydantic schemas for request validation and sanitization. This prevents malformed data from reaching the service layer and mitigates injection risks.
- **UI Safety:** Templates use Jinja2 with global auto-escaping enabled. Javascript implementation correctly uses `.textContent` to prevent XSS when rendering dynamic content.

## 2. Accuracy & Financial Integrity

### 2.1 Milliunit Handling
- The application correctly uses **YNAB Milliunits** (integers: dollars × 1000) for all monetary values. This avoids the precision errors inherent in floating-point arithmetic.
- Conversion to display currency is deferred to the final rendering stage (Jinja2 filters or JS formatting), which is the industry standard for financial applications.

### 2.2 Statistical Analysis
- **Outlier Detection:** Implements Tukey's IQR fence (1.5x) in `app/services/analysis_service.py`. The logic is sound, requiring a minimum of 5 data points and correctly applying upper-fence exclusion for spending and lower-fence for income.
- **Averages:** The use of "clean" averages (excluding outliers) provides users with a more realistic view of their typical spending habits.

### 2.3 YNAB Synchronization
- **Delta Sync:** Uses YNAB's `server_knowledge` to perform efficient delta syncs, reducing API load and improving performance.
- **Data Integrity:** Employs soft deletes and idempotent upserts to ensure the local database remains a faithful mirror of the YNAB state.

## 3. Efficiency & Performance

### 3.1 Asynchronous Stack
- The codebase is consistently async-first, utilizing `FastAPI`, `SQLAlchemy` (async), `aiosqlite`, `aiosmtplib`, and `httpx`. This allows for high concurrency, especially important when the scheduler triggers multiple API calls and report generations simultaneously.

### 3.2 Database Patterns
- **SQLAlchemy ORM:** Used correctly throughout. The use of `select().where(...)` and `async_sessionmaker` follows modern SQLAlchemy 2.0 best practices.
- **Query Optimization:** In `sync_service.py`, IDs are pre-fetched to avoid N+1 query problems during transaction upserts.

### 3.3 Scheduler
- **APScheduler Integration:** Cleanly integrated into the FastAPI lifespan. It correctly skips jobs if the app is locked, preventing errors and ensuring data isn't processed without a valid key in memory.

## 4. Observations & Recommendations

### 4.1 Minor Efficiency Optimization
- **Auth Gate Caching:** In `app/main.py`, the `auth_gate` middleware queries the database for `AppSettings` on every request to check if setup is complete.
  - *Recommendation:* Once the app is unlocked and settings are confirmed, set a flag in `app.state` to avoid redundant DB queries on subsequent requests.

### 4.2 Vision Refactoring
- **Vision OCR:** `app/services/import_service.py` currently imports AI SDKs directly for vision-based OCR because the `AIProvider` protocol does not yet support image inputs.
  - *Recommendation:* As noted in the source code, refactor the `AIProvider` protocol to support vision/images. This will consolidate all AI-related imports and logic into `app/services/ai_service.py` and maintain strict service isolation.

### 4.3 Database Migrations
- **Manual Migrations:** `app/database.py` uses a manual `apply_migrations` function with `ALTER TABLE` statements.
  - *Recommendation:* While appropriate for the current project scope and "zero-config" goal, consider migrating to **Alembic** if the database schema becomes significantly more complex in the future.

## 5. Conclusion

The codebase is exceptionally well-written and demonstrates a high degree of technical maturity. It is a benchmark for how to build secure, privacy-focused personal finance tools.

**Grade: A+**
