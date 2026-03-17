# Code Review Report

Scope: Full repository review for safety, security, accuracy, and efficiency. No code changes made.

## High Severity

1. Sensitive exception text can be stored or returned to users
- Locations:
  - app/services/report_service.py (AI commentary fallback includes exception text)
  - app/routers/life_context.py (SSE errors return exception text)
  - app/routers/import_data.py (SSE errors return exception text)
  - app/routers/api.py (report generation and SMTP/AI tests surface exception text)
- Why it matters: Provider SDK errors can include request metadata and occasionally sensitive context. Storing or returning raw exception strings risks leaking internal details and potentially secrets if an upstream library ever includes them. It also exposes stack/infra details to end users.
- Recommendation: Replace exception text with a generic message for user-visible responses, and log the detailed exception server-side. For stored AI commentary, record a fixed “AI commentary unavailable” message without the raw error.

## Medium Severity

1. Silent plaintext DB fallback if SQLCipher is unavailable
- Location: app/database.py (ImportError fallback to stdlib sqlite3)
- Why it matters: If sqlcipher3-binary is missing in a non-test deployment, the database becomes plaintext without a clear failure. This violates the project’s non-negotiable encryption requirement.
- Recommendation: Fail fast or emit a loud warning that prevents normal startup outside test/dev. Consider gating the fallback behind an explicit env flag for tests only.

2. Month input validation is too weak
- Location: app/routers/api.py (POST /api/report/generate)
- Why it matters: Only basic YYYY-MM shape is checked. Invalid months (e.g., 2025-99) can produce confusing errors downstream or incorrect reporting behavior.
- Recommendation: Validate month range (1–12) and reasonable year bounds, return 400 on invalid values.

3. Dead navigation link to removed profile wizard
- Location: app/templates/reports/report_detail.html (nav includes /setup)
- Why it matters: This route was removed in Phase 12. Users will hit a 404 from report detail pages, which is accuracy/UX drift from current app structure.
- Recommendation: Update the nav link to /profile or remove it.

## Low Severity

1. Potential N+1 pattern in sync transaction updates
- Location: app/services/sync_service.py
- Why it matters: For large syncs, per-transaction db.get calls can be slow. This is primarily a performance risk with large budgets.
- Recommendation: Consider batch loading existing transactions and updating them in-memory, or using bulk upsert patterns.

2. Duplicate-checking in import flow scales poorly
- Location: app/services/import_service.py (check_row_duplicates)
- Why it matters: One query per row can be expensive for large imports.
- Recommendation: Batch query for candidate duplicates per date/amount pairs or prefetch existing rows into a lookup table.

3. Settings parsing relies on truthiness of strings
- Location: app/routers/settings.py
- Why it matters: `bool("0")` evaluates to True. If any checkbox or boolean-like fields send unexpected values, settings can be misinterpreted.
- Recommendation: Parse booleans explicitly (e.g., `smtp_use_tls == "1"`). Some endpoints already do this; consider standardizing.

## Notes on Current Strengths

- Secrets are consistently encrypted at rest and never injected into templates.
- AI-generated markdown is sanitized with bleach before rendering in UI, exports, and email.
- DB encryption and recovery-code flows are thoughtfully implemented and tested.
- Template injection of chart JSON uses explicit HTML-safe encoding of `<`, `>`, and `&`.

## Suggested Test Additions

1. API month validation
- Add tests for invalid month values (e.g., 2025-00, 2025-13, 2025-99) in the report generation endpoint.

2. “No leakage” error paths
- Add tests that ensure user-facing responses do not include raw exception messages for AI/SMTP failures.

---
Generated on 2026-03-17 (America/New_York)
