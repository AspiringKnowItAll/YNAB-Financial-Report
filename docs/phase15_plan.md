# Phase 15 — Import Queue Overhaul

**Status: Complete**

## Context

The current import flow processes one file at a time synchronously: upload → AI analysis → review, with no way to abort mid-analysis, no progress visibility, and no queue persistence. If the page is refreshed, any in-progress work is lost. Users also have no way to manage confirmed imports after the fact (remove data from reports, view history).

This plan redesigns the import feature around a persistent, server-side queue with real-time SSE progress, multi-file support, per-session review, and a management section for confirmed imports — all on the existing `/import` page.

---

## What Changes (High Level)

1. **File upload splits from AI processing** — upload stores file to DB immediately (fast), processing happens separately via SSE stream
2. **Multi-file queue** — files queued persistently in DB; restored on page refresh; processed one at a time
3. **SSE progress stream** — real stage events (extracting → vision pages → normalizing → done) with elapsed timer
4. **Red stop button** — aborts active upload (AbortController) or active processing (SSE close + cancel API)
5. **Per-document review** — queue-first flow; review panel opens per item; "Back to Queue" replaces "Cancel"
6. **History & management section** — collapsible section below queue showing confirmed imports + ExternalAccount management

---

## Architecture

### Upload → Process Split

**Before**: `POST /api/import/upload` → stores file + runs AI → returns JSON (blocking, 10–60s)

**After**:
- `POST /api/import/upload` (updated) → validates file, stores encrypted bytes as ImportSession (status=`"pending"`), returns `{session_id}` in <1s
- `GET /api/import/process/{session_id}` (NEW) → SSE stream that extracts text + runs AI, yields progress, updates session to `"reviewing"` on completion

### Queue Persistence

ImportSession `status="pending"` means "uploaded, awaiting AI processing." A new `GET /api/import/sessions/active` endpoint returns all `pending` + `reviewing` sessions. On every page load, the client calls this and restores the queue table — files are never lost on refresh.

### Sequential Processing

The JS queue manager processes one session at a time (connects SSE to `/api/import/process/{id}`, waits for `done` event, then moves to next `pending` item). No concurrency setting needed for v1 — always sequential regardless of provider.

### SSE Progress Event Format

```
data: {"stage": "extracting"}\n\n
data: {"stage": "vision", "page": 1, "total": 3}\n\n   ← one per page if vision needed
data: {"stage": "normalizing"}\n\n
data: {"stage": "done", "normalization": {...}}\n\n
data: {"stage": "error", "message": "..."}\n\n
```

Client parses these with `response.body.getReader()` + `TextDecoder` (same pattern already used by the chat SSE).

---

## New / Updated Endpoints

| Method | Path | Change | Purpose |
|---|---|---|---|
| `POST` | `/api/import/upload` | Updated | File storage only; no AI; returns `{session_id}` immediately |
| `GET` | `/api/import/process/{id}` | **New** | SSE: extract text + AI normalize, yield progress events |
| `GET` | `/api/import/sessions/active` | **New** | Returns all `pending`+`reviewing` sessions for queue restore |
| `GET` | `/api/import/history` | **New** | Returns confirmed sessions + ExternalAccount list with row counts |
| `DELETE` | `/api/import/session/{id}/rows` | **New** | Hard-deletes ExternalTransaction + ExternalBalance rows for that session |
| `PATCH` | `/api/import/account/{id}` | **New** | Toggle `is_active` on ExternalAccount (deactivate/reactivate) |
| `POST` | `/api/import/cancel/{id}` | Unchanged | Already works; called when stop button clicked during processing |

---

## Database

**No new migrations required.** Existing schema is sufficient:
- `ImportSession.status = "pending"` — already exists; now means "uploaded, awaiting processing" (previously was a transient state)
- `ImportSession.file_content_enc` — stores raw file bytes until processing is complete; cleared after confirmation (unchanged)
- `ExternalAccount.is_active` — already exists for soft-deactivation

---

## Backend Changes

### `app/services/import_service.py`

New functions:

1. **`process_session_sse(session_id, db, settings, master_key) → AsyncIterator[str]`**
   - Takes `settings: AppSettings` (needed to call AI functions)
   - Loads ImportSession (must be `status="pending"`); raises if wrong status
   - Decrypts `file_content_enc` to get file bytes (base64-decode then decrypt)
   - Calls `extract_text()` → yields `{"stage": "extracting"}`
   - If `is_low_yield`: calls `check_model_vision_capable()`; if capable: opens the PDF with `fitz` inline to get page count, then calls `provider.vision()` page-by-page, yielding `{"stage": "vision", "page": N, "total": T}` per page (does NOT call `extract_via_vision()` as a black box, since that swallows per-page progress)
   - Calls `normalize_with_ai()` → yields `{"stage": "normalizing"}`
   - Saves `extracted_data_enc`, updates session `status="reviewing"`, commits
   - Yields `{"stage": "done", "normalization": {...}}`
   - On any exception: sets `status="failed"`, commits, yields `{"stage": "error", "message": "..."}`

2. **`list_active_sessions(db) → list[dict]`**
   - Returns all ImportSessions with status in (`"pending"`, `"reviewing"`, `"failed"`)
   - Fields: `id`, `file_name`, `institution_name`, `status`, `data_type`, `created_at`
   - `"failed"` sessions are included so the user can see what went wrong; rendered in queue as "Failed ✕" (no retry in v1)

3. **`list_confirmed_sessions(db, master_key) → list[dict]`**
   - Returns confirmed ImportSessions ordered by `confirmed_at DESC`
   - Joins to count ExternalTransaction + ExternalBalance rows per session
   - Includes ExternalAccount list with `is_active` and per-account row counts

4. **`delete_import_session_rows(session_id, db) → dict`**
   - Hard-deletes all ExternalTransaction rows WHERE `import_session_id = session_id`
   - Hard-deletes all ExternalBalance rows WHERE `import_session_id = session_id`
   - Returns `{"transactions_deleted": N, "balances_deleted": M}`
   - ImportSession record is preserved as audit trail

### `app/routers/import_data.py`

- **`upload_file()`**: Remove AI processing calls; just validate, hash, check duplicate, store `file_content_enc`, set `status="pending"`, return `{session_id, file_name, duplicate_file_warning}`
- **`process_session()`** (new): `GET /api/import/process/{session_id}` — returns `StreamingResponse` wrapping `process_session_sse()` generator; media type `text/event-stream`
- **`get_active_sessions()`** (new): calls `list_active_sessions()`
- **`get_history()`** (new): calls `list_confirmed_sessions()`
- **`delete_session_rows()`** (new): calls `delete_import_session_rows()`; returns counts
- **`update_account()`** (new): `PATCH /api/import/account/{id}` — toggles `is_active`; validates only `is_active` field for now

---

## Frontend Changes

### `app/templates/import/import.html`

**UI structure changes:**

1. **Upload state**: Keep existing file drop zone; add `multiple` attribute to file input; add a stop button (hidden by default, red, inline with upload button); remove the progress spinner from the button row (move it to queue table rows)

2. **Queue table** (new, inside `#upload-state`, below drop zone):
   ```
   [ File Name          ] [ Institution ] [ Status         ] [ Actions      ]
   [ chase_stmt.pdf     ] [ Chase       ] [ ⟳ Analyzing 23s] [ ■ Stop       ]
   [ transactions.csv   ] [ -           ] [ ✓ Ready         ] [ Review  ✕   ]
   [ invest.pdf         ] [ -           ] [ ⏸ Waiting       ] [        ✕   ]
   ```
   - Hidden when queue is empty; visible as soon as first file is uploaded
   - Status cell shows stage text + elapsed timer (JS-driven) for in-progress item
   - Stop button appears only for the currently-processing item
   - Review button appears when `status="reviewing"` (replaces current auto-slide-in behavior)
   - ✕ (cancel) button on all non-confirmed items

3. **Review state**: Add "← Back to Queue" button (top-left); remove "Cancel Import" and "Start Over" links (replaced by Back button); review panel slides in as before when user clicks Review in queue

4. **History section** (new, below queue table, collapsible):
   - "Confirmed Imports" header with expand/collapse chevron
   - Table: Date | File | Institution | Account | Rows | [Delete Rows]
   - Accounts sub-section: Name | Type | Status | [Deactivate / Reactivate]
   - Empty state: "No confirmed imports yet."
   - Loaded on page load; refreshed after each confirm action

5. **Confirmed state**: Remove entirely — after confirming, the panel closes and returns to queue view (queue item shows "Confirmed ✓"); history section auto-refreshes

### `app/static/js/import.js`

Major rewrite around a `QueueManager` object:

```javascript
const QueueManager = {
  sessions: [],         // [{session_id, file_name, status, stage, elapsed}]
  processingId: null,   // session_id currently being processed
  sseReader: null,      // active ReadableStream reader
  uploadAbort: null,    // AbortController for active upload fetch

  async uploadFiles(files) { ... },   // upload each file (one POST each), add to sessions[]
  async processNext() { ... },        // connect SSE to /process/{id}, update status
  openReview(sessionId) { ... },      // show review panel for this session
  async cancel(sessionId) { ... },    // cancel via API, remove from table
  stopActive() { ... },               // abort upload or close SSE + cancel API
  async restore() { ... },            // GET /api/import/sessions/active on page load
  renderQueue() { ... },              // re-render queue table from sessions[]
  async loadHistory() { ... },        // GET /api/import/history, render history section
}
```

Key behaviors:
- `uploadFiles()` — iterates files, POST each to `/api/import/upload` with AbortController; on success adds to `sessions[]` with status `"pending"`; calls `processNext()` if nothing currently processing
- `processNext()` — finds first `pending` session; connects `fetch()` + `getReader()` to `/api/import/process/{id}`; parses SSE events; updates `sessions[].stage` on each event; on `done` updates status to `"reviewing"` and calls `processNext()` for next item
- `stopActive()` — if `uploadAbort` set: call `.abort()`; else close `sseReader` and call `POST /api/import/cancel/{id}`
- `restore()` — called in `DOMContentLoaded`; fetches active sessions; populates `sessions[]`; calls `processNext()` if any are `pending`
- Elapsed timer — `setInterval` increments elapsed counter for the currently-processing session; displayed in queue table status cell
- After `confirm`: calls `loadHistory()` to refresh history section, removes session from queue table

---

## Stop Button Behavior

| When | Button Visible | Click Action |
|---|---|---|
| Idle / no upload active | Hidden | — |
| File uploading to server | Shown (red) | `AbortController.abort()` → removes item from queue |
| AI processing (SSE active) | Shown (red) in queue row | Close SSE reader → `POST /cancel/{id}` → status = `"cancelled"` |
| Waiting in queue | Hidden (per-row ✕ instead) | ✕ button: `POST /cancel/{id}` |

---

## History Section — Delete Rows Behavior

- Clicking "Delete Rows" on a confirmed import session:
  1. `DELETE /api/import/session/{id}/rows`
  2. ExternalTransaction + ExternalBalance rows for that session are hard-deleted
  3. Row shows "Rows deleted" badge; [Delete Rows] button removed
  4. If the ExternalAccount now has 0 rows total, the account can be deactivated
- ImportSession record is preserved (audit trail: file name, date, institution)
- ExternalAccount deactivate: `PATCH /api/import/account/{id}` with `{is_active: false}`
  - Account disappears from dashboard widgets and AI report context immediately
  - Can be reactivated via same section

---

## Critical Files

| File | Change |
|---|---|
| `app/services/import_service.py` | Add `process_session_sse()`, `list_active_sessions()`, `list_confirmed_sessions()`, `delete_import_session_rows()` |
| `app/routers/import_data.py` | Update `upload_file()`; add 5 new endpoints |
| `app/templates/import/import.html` | Queue table, history section, stop button, review panel "Back" button |
| `app/static/js/import.js` | QueueManager rewrite |
| `AGENTS.md` | Update Phase 13 section with new endpoints and functions |

---

## Reused Existing Functions

All in `app/services/import_service.py`:
- `extract_text(file_bytes, filename)` — unchanged
- `check_model_vision_capable(settings, master_key)` — unchanged
- `normalize_with_ai(text, profile, settings, master_key)` — unchanged
- `check_file_duplicate(file_hash, db)` — used in updated `upload_file()`
- `save_confirmed_import()` — unchanged
- `get_institution_profile()` — unchanged

**Note on `extract_via_vision`**: currently returns a concatenated string. For per-page SSE progress events, `process_session_sse()` will call `pdfplumber`/`fitz` directly to get the page count first, then call the existing `vision()` method page-by-page inline (rather than calling `extract_via_vision()` as a black box), yielding a progress event per page.

---

## Verification

1. **Upload**: Upload 3 files via drag-drop → all 3 appear in queue as "Waiting" instantly → first starts processing → queue persists after browser refresh
2. **Stop during processing**: Click stop button while AI analyzing → session cancelled → next item starts
3. **Stop during upload**: Spam upload of large file → click stop → fetch aborted → no session created
4. **Review flow**: File finishes → "Ready to Review" in queue → click Review → review panel opens → confirm → returns to queue → history section updates
5. **History delete**: Confirmed import → click "Delete Rows" → row count goes to 0 → data removed from dashboard widgets
6. **Account deactivate**: Click "Deactivate" on ExternalAccount → account disappears from report generation
7. **Page restore**: Upload 2 files, close browser mid-processing, reopen → queue shows both files at correct status
8. Run `pytest tests/` to confirm no regressions
