# Code Review — YNAB Financial Report

**Date:** 2026-03-17
**Scope:** Full codebase review — all Python source files, static JS, configuration files, and tests.
**Methodology:** Static analysis of every source file listed in the review brief. No dynamic execution.
**Reviewer:** Claude Sonnet 4.6

---

## Executive Summary

The codebase is a well-structured, security-conscious single-user personal finance application. The overall design is sound: defense-in-depth encryption (SQLCipher + Fernet), a middleware auth gate, no framework authentication shortcuts, and consistent use of Pydantic for input validation at the boundary. The developer has clearly thought carefully about the threat model.

**Finding counts by severity:**

| Severity | Count |
|---|---|
| Critical | 1 |
| High | 5 |
| Medium | 8 |
| Low / Informational | 11 |

The single critical finding is a race condition in recovery code validation that could allow two simultaneous requests to use the same recovery code. The high-severity findings are primarily around missing input validation on AI-returned data before it is persisted to the database, N+1 query patterns inside loops, and a blocking call on the async event loop. None of the high-severity findings represent traditional web application security vulnerabilities (no SQL injection, no auth bypass, no plaintext secret storage was found).

---

## Critical Findings

### CRIT-1: Recovery Code Validation Has a TOCTOU Race Condition

**File:** `app/services/auth_service.py`, lines 195–220

**Description:** `use_recovery_code()` reads the slots file, checks `slot["used"]`, then writes `slot["used"] = True` back to disk in two separate non-atomic operations. On a single-user personal application this race is unlikely to be exploited in practice, but it is structurally present.

```python
# Line 211-217: read → check → write is not atomic
master_key = _unwrap_master_key(slot, code)
# <-- Another request could pass this check at the same time
slots[i]["used"] = True
_write_recovery_slots(slots)
```

**Impact:** Two concurrent requests submitting the same recovery code could both succeed: both read the slot as `used=False`, both unwrap the key, and both attempt to write `used=True`. The second write wins but both requests have already received the master key. In practice this requires simultaneous HTTP requests from two clients with the same code, which is implausible for a single-user self-hosted app. However, it is a real logical flaw.

**Recommendation:** Use a filesystem lock (e.g., `fcntl.flock` on Linux, or a `threading.Lock`) around the read-check-write sequence, or write an atomic-compare-and-swap by writing a temporary file and renaming it.

---

## High Severity Findings

### HIGH-1: AI-Returned Data Written to Database Without Type or Bounds Validation

**Files:** `app/services/import_service.py`, lines 446–477 (`save_confirmed_import`); `app/routers/import_data.py`, lines 379–394

**Description:** The `save_confirmed_import` function takes rows from `extracted_data_enc`, which is AI-generated JSON, and writes them directly to `ExternalTransaction` and `ExternalBalance` rows. The only check performed is `row.get("type") != "transaction"`. Fields like `date`, `amount_milliunits`, `description`, `return_bps`, and `contribution_milliunits` are taken directly from the AI response with no type coercion, range validation, or format verification.

```python
# import_service.py line 454-464: no validation before ORM insert
txn = ExternalTransaction(
    external_account_id=external_account_id,
    date=row["date"],                          # unchecked string
    amount_milliunits=row["amount_milliunits"], # unchecked — could be None, string, float
    description=row["description"],            # unchecked length
    ...
)
```

**Impact:** A malformed AI response (or one manipulated by prompt injection from a crafted document) could cause: `TypeError`/`ValueError` that leaks stack traces; silent insertion of `None` into NOT-NULL-equivalent columns; description strings longer than the 512-char column; dates in unexpected formats that break date comparisons; or a `return_bps` value of `999999999` that causes integer overflow in display logic.

**Recommendation:** Validate AI-returned row data through a Pydantic model (e.g., `TransactionRow`, `BalanceRow`) before inserting. At minimum: check `date` is a valid ISO date string, `amount_milliunits` is an integer, `description` is a non-null string under 512 chars, and `return_bps` is in a plausible range.

---

### HIGH-2: N+1 Query Pattern in `save_confirmed_import` and `generate_report`

**Files:** `app/services/import_service.py`, lines 364–402 (`check_row_duplicates`); `app/services/report_service.py`, lines 482–492

**Description:** In `check_row_duplicates`, a `SELECT` query is issued inside a `for row in rows` loop — one query per transaction row. For a file with 200 transactions, this is 200 sequential DB round-trips. Similarly, in `generate_report`, a `SELECT` for the latest balance per external account is issued inside a `for acct in ext_accounts` loop.

```python
# import_service.py lines 385-392: query inside loop
for row in rows:
    ...
    stmt = select(ExternalTransaction).where(...)
    result = await db.execute(stmt)  # N queries for N rows
```

**Impact:** For large import files this will be slow. On a SQLite database the latency per query is low, but for a 500-row CSV import this could add several seconds of unnecessary overhead.

**Recommendation:** For duplicate checking, batch-load existing transactions for the account and month range into a set, then check in memory. For balance loading, use a single query with `DISTINCT ON` or a subquery to fetch the most recent balance per account.

---

### HIGH-3: Blocking `asyncio.get_event_loop()` Usage in `export_service.py`

**File:** `app/services/export_service.py`, line 198

**Description:** `asyncio.get_event_loop()` is deprecated in Python 3.10+ and will raise a `DeprecationWarning` (or silently return the wrong loop) in some contexts. The correct call in an async function is `asyncio.get_running_loop()`.

```python
# export_service.py line 198-200
loop = asyncio.get_event_loop()
pdf_bytes: bytes = await loop.run_in_executor(
    None, lambda: HTML(string=html_string).write_pdf()
)
```

**Impact:** In Python 3.12 (the version used in the Dockerfile), `asyncio.get_event_loop()` called from within a running async context will emit a `DeprecationWarning` and may return a different loop than the running one. In edge cases (e.g., tests, or if the event loop policy is changed), this could cause PDF generation to block the event loop rather than running in the executor.

**Recommendation:** Replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()`.

---

### HIGH-4: `apply_migrations` Uses Raw SQL String Interpolation Without Parameterization

**File:** `app/database.py`, lines 144–149

**Description:** The `apply_migrations` function constructs `ALTER TABLE` SQL strings using Python f-string interpolation with values from the `_new_columns` list. While these values are hardcoded constants (not user input), this pattern is architecturally unsafe — future additions might accidentally use a variable value here.

```python
# database.py lines 145-149
for table, col, definition in _new_columns:
    try:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
```

**Impact:** Currently not exploitable because all values are hardcoded literals in the source. However, if a developer adds a migration that references a runtime value (e.g., a column name derived from settings), this becomes a SQL injection vector.

**Recommendation:** This is low risk given the constants-only pattern, but note it for future contributors. Add a code comment: "Values here must be hardcoded string literals — never use runtime variables in this list."

---

### HIGH-5: SSE Error Messages Leak Exception Details to Clients

**Files:** `app/routers/life_context.py`, line 152; `app/routers/import_data.py`, line 289

**Description:** In the SSE event generators, caught exceptions are streamed verbatim to the client:

```python
# life_context.py line 152
yield f"data: [ERROR] {exc}\n\n"

# import_data.py line 289
yield f"data: [ERROR] {exc}\n\n"
```

**Impact:** Exception messages from underlying libraries (httpx, anthropic SDK, OpenAI SDK, SQLAlchemy) can contain sensitive details: API endpoint URLs, partial API keys in error strings, internal database paths, stack trace fragments. For a single-user self-hosted application this is a minor concern, but it is a violation of the stated principle of not returning sensitive info in API responses.

**Recommendation:** Log the full exception server-side and return a generic error message to the client: `yield f"data: [ERROR] An internal error occurred. Check server logs.\n\n"`.

---

## Medium Severity Findings

### MED-1: MIME Type Validation Relies Solely on Client-Reported Content-Type

**File:** `app/routers/import_data.py`, lines 71–78

**Description:** File upload validation checks `file.content_type`, which is the MIME type reported by the client's browser in the `Content-Type` header of the multipart form. This is trivially forgeable — an attacker could upload a crafted file with `content_type: "text/csv"` but actual content that is a binary executable.

```python
if file.content_type not in _ACCEPTED_MIME_TYPES:
    return JSONResponse(status_code=400, ...)
```

**Impact:** The file bytes are then passed to `pdfplumber` or decoded as UTF-8. Malformed input to `pdfplumber` could trigger bugs in the PDF parsing library. For a single-user app behind an auth gate this is low risk, but it is a correctness issue.

**Recommendation:** After reading the bytes, add a magic-byte check: PDF files start with `%PDF-`. For CSV/TXT, attempt UTF-8 decode as a validation step. The `python-magic` library or a simple byte-prefix check would be sufficient.

---

### MED-2: Month Parameter Validation in Report Generation Is Incomplete

**File:** `app/routers/api.py`, lines 105–112

**Description:** The `month` query parameter is validated to check it has two parts separated by `-` and both are digits. However, it does not validate that the year is reasonable, the month is 01–12, or that the string has exactly 7 characters (YYYY-MM). A value like `99999-99` or `2024-00` would pass this check.

```python
parts = month.split("-")
if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
    return JSONResponse({"status": "error", "message": "month must be in YYYY-MM format."}, ...)
```

**Impact:** Malformed month strings would be passed to `generate_report` and stored in the `ReportSnapshot.month` column. The `_last_n_months` function in `report_service.py` would then attempt `int(month[5:7])`, which for `99999-99` would return 99, causing an infinite loop in the month calculation logic (subtracting from month 99 never reaches 0 in a typical 12-month window).

**Recommendation:** Use a stricter regex: `re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month)`, or parse with `datetime.strptime(month, "%Y-%m")` and catch `ValueError`.

---

### MED-3: `_last_n_months` in `report_service.py` Can Produce Incorrect Results for Unusual Inputs

**File:** `app/services/report_service.py`, lines 54–64

**Description:** The `_last_n_months(anchor, n)` function is correct for valid YYYY-MM strings. However, it reads the month integer directly from the string (`int(anchor[5:7])`) without validating that `anchor` is a well-formed YYYY-MM string. If given `anchor = "2024-00"` (a month of 0), the loop `month -= 1` would immediately go to -1, and `if month == 0` would never trigger, causing `year -= 1` and `month = 12` — but the sequence would start at month 0 which is invalid.

**Impact:** Combined with MED-2, a malformed month string reaching this function could produce an incorrect 12-month window in the report charts. The charts would display wrong labels but not crash.

**Recommendation:** Validate the `anchor` parameter at the entry to `_last_n_months`, or fix validation at the API boundary (see MED-2).

---

### MED-4: `_migrate_sync` Logs the Hex Key Indirectly via String Formatting

**File:** `app/database.py`, lines 67–100

**Description:** The hex representation of the database encryption key is embedded in SQL strings executed in `_migrate_sync`. While the SQL strings themselves are not logged, if SQLAlchemy echo mode were ever turned on (currently `echo=False`), or if an ORM-level SQL logging handler were added, these strings would appear in logs with the hex key included. The key also appears as a string in `_on_connect` (line 51).

**Impact:** Currently not a logging leak since `echo=False`. However, if a developer changes the engine to `echo=True` for debugging, the hex key would be visible in application logs. This is a latent risk rather than an active one.

**Recommendation:** Add a comment noting that `echo=True` must never be used in production because it would log the key material. Optionally, consider using SQLCipher's `PRAGMA key` via a connection event that doesn't produce a loggable SQL string.

---

### MED-5: Content-Disposition Filename Header Not Sanitized

**Files:** `app/routers/export.py`, lines 46–49, 56–61; `app/routers/import_data.py` (indirectly via `session.file_name`)

**Description:** In the export router, the filename in `Content-Disposition` is generated from `snapshot.month`, which is a DB-stored string. If this were ever to contain special characters (e.g., `../` or quote characters), it could cause header injection. The current `YYYY-MM` format makes this unlikely in practice, but it is not guaranteed by any validation.

```python
filename = f"report-{snapshot.month}.html"
return HTMLResponse(..., headers={"Content-Disposition": f'attachment; filename="{filename}"'})
```

**Impact:** Low for the month-based filenames, but `ImportSession.file_name` (stored directly from `file.filename` in the upload handler, with no sanitization) could contain characters that break the `Content-Disposition` header if it were ever used in a download response.

**Recommendation:** Use `urllib.parse.quote(filename)` or RFC 5987 encoding for the `Content-Disposition` filename parameter.

---

### MED-6: Prompt Injection Risk in Import Chat and Life Context Chat

**Files:** `app/services/import_service.py`, lines 595–609 (`stream_import_chat`); `app/services/life_context_service.py`, lines 344–346

**Description:** In `stream_import_chat`, the user's message is embedded directly into the `_IMPORT_CHAT_SYSTEM_PROMPT` via format string, then also passed as the `user` prompt. In `stream_reply`, the full chat history including user messages is concatenated into the `user_prompt` string. A malicious user message containing text like `[DATA_UPDATE]{...malicious JSON...}[/DATA_UPDATE]` could interfere with the DATA_UPDATE parsing logic.

```python
# import_service.py line 572: re.compile used for detection
_DATA_UPDATE_RE = re.compile(r"\[DATA_UPDATE\](.*?)\[/DATA_UPDATE\]", re.DOTALL)
```

**Impact:** For a single-user app, prompt injection from the user to themselves is not a meaningful attack. However, if a crafted uploaded document contains `[DATA_UPDATE]{...}[/DATA_UPDATE]` in its text, the regex would parse it as an AI-initiated update. The `json.loads` call on line 632 guards against malformed JSON, but valid malicious JSON would be saved as the new `extracted_data_enc`. This is a real risk with untrusted uploaded files.

**Recommendation:** Consider using a more unique sentinel (e.g., a GUID-based delimiter) that would be difficult to accidentally appear in document text. The existing `\x00DATA_UPDATE\x00` approach used for the streamed sentinel is better than the bracket form. Consider using the null-byte form in both directions.

---

### MED-7: `use_recovery_code` Timing Oracle — Allows Slot Enumeration

**File:** `app/services/auth_service.py`, lines 205–218

**Description:** The recovery code validation iterates over all 8 slots and attempts to unwrap each one. Because Fernet's `decrypt` (via Argon2id key derivation + Fernet verification) takes a fixed amount of time per slot, the total time for `use_recovery_code` varies based on which slot number the correct code is in — the first correct code takes ~1× KDF time, the last takes ~8×. This is a minor timing oracle that could theoretically allow an attacker to narrow down which slot a code belongs to.

**Impact:** Negligible for a self-hosted app. The attacker would need many guesses and network access. No practical exploit exists for this deployment model.

**Recommendation:** Informational note — always validate all 8 slots regardless of early success, using a constant-time comparison. The current early-exit-on-success behavior is functionally correct but not timing-constant.

---

### MED-8: Docker Container Runs as Root

**File:** `Dockerfile`

**Description:** The `Dockerfile` does not include a `USER` instruction, so the application runs as root inside the container. The `/data` volume and all file I/O runs as root.

```dockerfile
# No USER instruction — runs as root
CMD uvicorn app.main:app --host 0.0.0.0 --port 8080
```

**Impact:** If a vulnerability in any dependency (WeasyPrint, pdfplumber, pymupdf) allowed code execution, the attacker would have root access within the container. The key material in `/data/master.salt`, `master.verify`, and `recovery_keys.json` would be accessible to any process running in the container.

**Recommendation:** Add a non-root user to the Dockerfile:
```dockerfile
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
```
Ensure `/data` volume permissions are set appropriately.

---

## Low Severity / Informational

### LOW-1: `milliunit_to_dollars` Filter Does Not Handle Negative Values With Sign

**File:** `app/templates_config.py`, line 15–18

**Description:** The filter formats negative milliunits as `$-1,234.56` rather than `-$1,234.56`. This is a display-only cosmetic issue.

**Recommendation:** Use `f"${dollars:,.2f}"` for positive values and `f"-${abs(dollars):,.2f}"` for negative, or use Python's locale-aware currency formatting.

---

### LOW-2: `_write_recovery_slots` Has No Atomic Write

**File:** `app/services/auth_service.py`, lines 112–114

**Description:** The recovery slots file is written by opening the file with `"w"` mode and calling `json.dump`. If the process is interrupted mid-write, the file would be corrupted and all recovery codes would be lost.

**Recommendation:** Write to a temp file and `os.replace()` atomically. Example: write to `recovery_keys.json.tmp`, then `os.replace("recovery_keys.json.tmp", "recovery_keys.json")`.

---

### LOW-3: `test_unlock_missing_salt_raises` Uses Deprecated `get_event_loop().run_until_complete()`

**File:** `tests/unit/test_auth_service.py`, lines 136–139

**Description:** The test uses `asyncio.get_event_loop().run_until_complete(unlock(...))` inside a synchronous test function. In Python 3.10+, `get_event_loop()` in a context without a running loop is deprecated. This may produce a `DeprecationWarning` in pytest output.

**Recommendation:** Mark the test as `async` and use `pytest-asyncio`, matching the pattern of all other async tests in the file.

---

### LOW-4: `api/test/smtp` and `api/test/smtp/send` Duplicate SMTP Logic From `email_service.py`

**Files:** `app/routers/api.py`, lines 255–319, 326–409; `app/services/email_service.py`, lines 189–219

**Description:** The SMTP connection and authentication logic is duplicated verbatim between the test endpoint handlers in `api.py` and the `test_smtp_connection` function in `email_service.py`. Both implement the port 465 vs STARTTLS detection, login flow, and quit logic independently.

**Impact:** Maintenance risk — if the TLS logic needs to change (e.g., to support STARTTLS on non-587 ports), it must be updated in two places.

**Recommendation:** The `/api/test/smtp` handler should construct a temporary `AppSettings`-like object and delegate to `email_service.test_smtp_connection`. Or `email_service.test_smtp_connection` should accept plain parameters rather than an `AppSettings` object.

---

### LOW-5: `check_row_duplicates` Has a Logic Bug for Near-Duplicate Detection

**File:** `app/services/import_service.py`, lines 392–401

**Description:** The comment says "Don't break — an exact match would override a near match" but the code does not correctly implement this. Once `row["duplicate"] = "near"` is set for the first existing transaction, the loop `for existing_txn in existing` continues. If a second `existing_txn` also has a different description, it will overwrite `row["duplicate"] = "near"` and `row["existing_description"]` again, potentially losing the first near-match information. An exact match can only be set via `break`.

**Impact:** The near-duplicate description shown to the user may be from an arbitrary existing transaction rather than the most relevant one. This is a cosmetic/UX issue, not a data loss issue.

**Recommendation:** Track whether an exact match was already found and only set `near` if no exact match has been found yet. Consider breaking out of the inner loop once an exact match is found.

---

### LOW-6: `requirements.txt` Has No Pinned Versions

**File:** `requirements.txt`

**Description:** All dependencies use `>=` minimum versions with no upper bounds or exact pins. This means `pip install` will always pull the latest compatible version, which could introduce breaking changes or newly discovered vulnerabilities in transient upgrades.

**Impact:** A future `pip install` could pull a version of `weasyprint`, `pdfplumber`, or `pymupdf` with a known CVE. The `bleach` library in particular has had security-relevant updates in the past.

**Recommendation:** Consider generating a `requirements.lock` or `requirements-frozen.txt` with pinned exact versions (`pip freeze`) for production Docker builds. At minimum, add upper bounds for libraries known for breaking changes.

---

### LOW-7: `apply_migrations` Column Definitions Are Not Type-Safe

**File:** `app/database.py`, lines 133–149

**Description:** The migration column definitions (e.g., `"BOOLEAN NOT NULL DEFAULT 0"`) are raw SQLite SQL strings. If the same migration was run against a different database backend (e.g., PostgreSQL), they would fail. This is acceptable since the project is SQLite-only, but it is fragile.

**Recommendation:** Document that this migration system is SQLite-specific and cannot be ported to other backends without changes.

---

### LOW-8: `import_service.check_model_vision_capable` Assumes All Non-Ollama Providers Support Vision

**File:** `app/services/import_service.py`, lines 78–119

**Description:** The function returns `True` for all Anthropic, OpenAI, and OpenRouter providers unconditionally. Older OpenAI models (e.g., `gpt-3.5-turbo`) do not support vision input, and not all OpenRouter models do either. Calling the vision API with a non-vision model will result in an API error.

**Impact:** If the user configures an Anthropic or OpenAI model that does not support vision (or forgets to update the model setting), the vision fallback path will fail with an API error, which is caught and logged. The import will then proceed with the sparse text output (the `vision_needed = True` path). No data loss, but the vision fallback silently degrades.

**Recommendation:** Consider passing the model name from settings to the capability check and verifying against a known list of vision-capable models, or document that the user must configure a vision-capable model if they want OCR fallback.

---

### LOW-9: `smtp_host` from Settings Is Used in SMTP Connection Without Validation

**File:** `app/services/email_service.py`, line 177; `app/routers/api.py`, lines 301, 387

**Description:** The `smtp_host` value from settings is passed directly to `aiosmtplib.SMTP(hostname=...)`. While Pydantic validates the SMTP settings form fields (max 253 chars), there is no validation that the hostname is a valid DNS name or IP address rather than a local address like `localhost` or a private IP range. For a single-user self-hosted app this is not meaningful, but noted for completeness.

**Impact:** None in practice for the intended deployment model.

---

### LOW-10: Dashboard Loads All Transactions Into Memory

**File:** `app/routers/dashboard.py`, lines 135–153

**Description:** The dashboard loads every non-deleted, approved transaction for the budget into memory at once (no `LIMIT` clause), then processes them in Python. For a long-standing YNAB account with years of history, this could be thousands of rows.

**Impact:** Memory usage and response time will grow linearly with the number of transactions. For users with 3–5 years of history this could be 20,000+ transactions, which is still fast for SQLite in-memory processing but is worth noting.

**Recommendation:** Consider filtering transactions to the last 24 months (matching the chart window) rather than loading all history. The outlier detection requires at least 5 months of data, so this would not affect correctness for the intended use case.

---

### LOW-11: No CSRF Protection on State-Changing Endpoints

**File:** All POST routers

**Description:** The application uses HTML form submissions and JSON API endpoints with no CSRF tokens or `SameSite` cookie policy. However, since the app uses no browser-stored session cookies (authentication is stateless — the master key is stored in `app.state`, not cookies), traditional CSRF attacks do not apply. The only session state is server-side.

**Impact:** No practical CSRF risk given the cookie-less authentication model. Noted for completeness.

---

## File-by-File Notes

### `app/main.py`
The auth gate middleware is well-designed. The `except Exception: pass` on line 93 is intentional and correctly documented (DB not yet available on first startup). The `EXEMPT_PREFIXES` tuple correctly exempts all necessary paths. The import of `os` inside the middleware function on line 68 is unusual (typically top-level) but not incorrect.

### `app/database.py`
The SQLCipher monkey-patching approach is architecturally sound given aiosqlite's design. The `_migrate_sync` function correctly uses `sqlcipher_export()`. One concern: `_migrate_sync` does not clean up `_DB_ENC_PATH` on failure — if the `ATTACH` or `SELECT sqlcipher_export` succeeds but the subsequent `DETACH` or file rename fails, the partial encrypted file is left behind. A retry of the migration would then find `_DB_PATH` is a partial encrypted file, not plaintext, and would incorrectly conclude it is already encrypted (line 75–79).

### `app/services/auth_service.py`
Cryptographic design is solid: Argon2id with appropriate parameters (64MB, time_cost=3), Fernet for key wrapping, unique salts per recovery slot. The `_VERIFY_PLAINTEXT` known-plaintext approach for password verification is correct and avoids storing the password or a hash of the password. Recovery code generation uses `secrets.choice` which is cryptographically secure.

One note: `ARGON2_MEMORY_COST = 65536` (64MB) is reasonable but on the low end for 2025 recommendations. OWASP currently recommends 19MB minimum with higher being better; 64MB is acceptable but 128MB would provide stronger brute-force resistance if hardware allows.

### `app/services/encryption.py`
Clean and correct. Fernet provides AES-128-CBC + HMAC-SHA256 with a random IV per encryption call (confirmed by the test `test_encrypt_is_nondeterministic`). The guard for `None` master key is correct. Note that the docstring says "AES-128-CBC" — this is accurate (Fernet uses AES-128), though the master key derivation in `auth_service.py` produces 32 bytes. Fernet takes the 32-byte key but uses 16 bytes for AES and 16 bytes for HMAC internally; this is by design in the Fernet spec.

### `app/services/sync_service.py`
The delta sync implementation is correct. The N+1 pattern for updating existing categories and accounts (`await db.get()` inside loops) is acceptable for YNAB-scale data (typical budgets have <100 categories). The pre-fetch of `existing_txn_ids` on line 174–177 correctly avoids N+1 for the larger transactions set. The sync log "running" → "success"/"failed" lifecycle is correctly implemented with an explicit rollback on failure.

### `app/services/report_service.py`
The AI error handling on lines 539–541 is appropriate (stores error note rather than failing the whole report). The exception catch on line 469 (silently `None` if context block decryption fails) is overly broad — it would mask a corrupted database. Consider at minimum logging the exception.

The `_build_ai_prompt` function includes user financial context in the AI prompt. The life context text (line 97) is inserted without any sanitization or length limiting beyond the 5000-char limit enforced at creation time. An adversarially crafted context block (though a user can only inject it via the chat interface) could include text designed to manipulate the AI commentary. This is a self-service concern only.

### `app/services/life_context_service.py`
The `stream_reply` function on line 306 has a subtle design issue: if the streaming completes but `append_message` (line 358) fails (e.g., a DB write error), the assistant's message is lost and the session state is inconsistent — the user message was saved but the assistant response was not. This is an edge case but worth noting.

### `app/services/import_service.py`
The `extract_via_vision` function (lines 225–335) violates the architecture rule "No code outside `ai_service.py` may import any provider SDK directly" (stated in CLAUDE.md). It imports `anthropic.AsyncAnthropic` and `openai.AsyncOpenAI` directly. This is acknowledged with a comment on line 234–237 but remains an architectural inconsistency.

### `app/routers/import_data.py`
The `delete_institution_profile` endpoint on line 443 does not check `master_key` (no `request: Request` parameter), unlike all other endpoints in this router. This means it is accessible without confirming the app is unlocked — however, it is still protected by the middleware auth gate which checks `app.state.master_key`, so this is not a real bypass. It is just inconsistent with the pattern of the other endpoints.

### `app/routers/auth.py`
The recovery flow on line 213–216 deletes `master.salt`, `master.verify`, and `master.recovery_path` after successful code use, then shows `recovery_success.html`. This is correct: the user is prompted to set a new password on the next request. However, the master key is now in `app.state.master_key` but the database is open. If the user navigates away without setting a new password (or closes the browser), the master key is in memory but auth files are deleted — the app would be stuck on first-run with an open database until restart. This is an edge case but worth documenting.

### `app/static/js/chat_widget.js`
The widget uses `textContent` for rendering (not `innerHTML`), correctly preventing XSS. The `beforeunload` warning is informative but modern browsers may suppress the custom message. The session init on panel open is correct.

### `app/static/js/import.js`
The `window.deleteInstitutionProfile` function on line 595 is attached to the global window object, which could conflict with other scripts if this were a multi-page app. For this application it is harmless. All user-visible text from server responses is set via `textContent`, not `innerHTML`, which correctly prevents XSS.

---

## Positive Observations

1. **Cryptographic design is excellent.** Argon2id with a 16-byte salt, Fernet for key wrapping, defense-in-depth with both SQLCipher and application-layer Fernet encryption, recovery code key-wrapping — this is production-quality key management for a self-hosted application.

2. **No secrets in plaintext storage anywhere.** Every secret (`ynab_api_key`, `ai_api_key`, `smtp_password`, `notion_token`, life context data, import session messages) is encrypted at rest. The `_enc` naming convention is consistently applied.

3. **The auth gate middleware is correct and complete.** All three steps (salt existence, key in memory, settings complete) are enforced before reaching any router, with appropriate exemptions and JSON error responses for API routes.

4. **Pydantic validation at router boundaries is thorough.** All form inputs pass through typed Pydantic schemas with field-level and model-level validators. Whitespace stripping, email validation, and cross-field constraints are all present.

5. **Jinja2 autoescape is enabled globally** (`templates_config.py` line 12), and AI-generated markdown content is passed through `bleach.clean()` with an allowlist before rendering. XSS surface is well-controlled.

6. **No SQL injection vectors found.** All ORM queries use parameterized SQLAlchemy constructs. The only raw SQL (`apply_migrations`) uses hardcoded string literals.

7. **YNAB soft-delete pattern is correctly implemented.** All queries filter `deleted.is_(False)`, and sync correctly sets `deleted=True` on removed rows rather than hard-deleting.

8. **Logging discipline is enforced.** No decrypted values are logged. The `logger.error("Sync failed: %s", exc)` pattern passes exception objects (not f-strings with secrets) to the logger.

9. **Test coverage of cryptographic components is solid.** The auth service and encryption tests cover the critical security paths including wrong-password rejection, recovery code single-use, and non-deterministic IV generation.

10. **The `analysis_service.py` purity rule is followed.** No I/O or DB access in the analysis functions — all inputs are plain Python objects. This makes the analysis functions easy to test and reason about.

---

## Recommendations Summary

**Priority 1 — Fix before next release:**
1. **(CRIT-1)** Add a lock around recovery code read-check-write to prevent race condition.
2. **(HIGH-1)** Add Pydantic validation of AI-returned row data before writing to `external_transactions`/`external_balances`.
3. **(HIGH-3)** Replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()` in `export_service.py`.
4. **(MED-2)** Strengthen month parameter validation in `/api/report/generate` to reject invalid month values.
5. **(HIGH-5)** Redact exception details from SSE error events; log them server-side only.

**Priority 2 — Fix in next sprint:**
6. **(HIGH-2)** Eliminate N+1 query patterns in `check_row_duplicates` and `generate_report`'s balance loading loop.
7. **(MED-8)** Add a non-root `USER` instruction to the Dockerfile.
8. **(LOW-2)** Use atomic file write (write-then-rename) for `recovery_keys.json`.
9. **(MED-6)** Use a null-byte or GUID sentinel in both the SSE stream and the regex to reduce prompt injection risk from uploaded documents.
10. **(MED-1)** Add magic-byte validation for uploaded files beyond the client-reported MIME type.

**Priority 3 — Maintenance / hygiene:**
11. **(LOW-4)** Remove duplicated SMTP connection logic from `api.py` test handlers.
12. **(LOW-6)** Pin dependencies in a frozen requirements file for reproducible production builds.
13. **(LOW-10)** Limit dashboard transaction queries to the last 24 months to bound memory usage.
14. **(LOW-3)** Fix the deprecated `get_event_loop().run_until_complete()` in the auth service test.
15. **(import_service architecture)** Refactor `extract_via_vision` to comply with the AIProvider abstraction rule by adding vision support to the `AIProvider` protocol.
