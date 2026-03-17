# Phase 13 — External Data Import: Plan

## Goal

Allow users to upload financial documents (PDF or CSV) from any institution. An AI agent figures out what the document contains, asks follow-up questions in a chat, and lets the user review and confirm extracted data before anything is saved. Confirmed data feeds into AI report generation alongside YNAB data.

---

## User Flow (End-to-End)

1. User clicks **Import** on the dashboard (next to Sync Now)
2. Drag-and-drop or file-picker UI accepts a PDF or CSV
3. File is uploaded → backend extracts text → AI normalizes to structured data
4. User sees a **review panel**:
   - Summary card: "I detected a Vanguard 401(k) balance statement with 1 row."
   - Extracted rows table (scrollable, showing what will be saved)
   - AI chat panel with the agent's initial questions/observations
5. User chats to correct, clarify, or provide context in plain language
6. Agent updates its understanding; extracted rows table refreshes
7. User clicks **Confirm Import** → data saved to DB
8. Agent asks: "Will you be importing more files from this institution in the future? If so, I'll remember how to handle them." → if yes, an institution profile is saved
9. Confirmed data is available immediately in the next report generation

---

## Design Decisions

### File Types
- **PDF**: text extracted via `pdfplumber` (pure Python, no system deps)
- **CSV**: parsed with Python's built-in `csv` module
- If text yield from a PDF is below a threshold (e.g., fewer than 50 words), assume it is a scanned/image PDF and attempt **AI vision** (base64-encode pages as PNG images, send to AI). Vision support is model-specific, not provider-specific:
  - **Ollama**: the app queries `/api/show` for the model's `capabilities` array; if `"vision"` is present, OCR is supported. Vision-capable models (e.g., `llava`, `moondream`, `gemma3`) are tagged in the settings dropdown.
  - **Anthropic/OpenAI**: all modern models support vision; the app attempts it and handles errors gracefully.
  - **OpenRouter**: varies by model; the app attempts it and handles errors gracefully.
  - **Fallback**: if the model does not support vision, the user is prompted to describe the document manually via chat.
- File size limit: 10 MB
- Accepted MIME types: `application/pdf`, `text/csv`, `text/plain`

### AI Normalization
- The AI always returns a structured JSON response on initial analysis (using `generate()`, not streaming)
- AI identifies: institution name, account name, data type (transactions / balance snapshot / both), extracted rows, and any questions it has
- Row format:
  - **Transaction**: `{type: "transaction", date, amount_milliunits, description, category?}`
  - **Balance snapshot**: `{type: "balance", date, amount_milliunits, notes?, contribution_milliunits?, return_bps?}`
- AI is given any existing institution profile as context (if one exists for the detected institution)

### Review Chat
- Same SSE streaming pattern as Life Context Chat (reuse `StreamingResponse` + `fetch()`)
- User messages + AI replies stored encrypted in `ImportSession.messages_enc`
- After each AI reply that updates the extracted data, a revised `extracted_data_enc` is also saved
- The table on the page refreshes automatically when the AI signals a data update (via a special `[DATA_UPDATE]` event in the SSE stream)

### Duplicate Detection
- **File-level**: SHA-256 hash of uploaded file stored in `ImportSession.file_hash`. Warn user (don't block) if the same hash was previously confirmed.
- **Row-level**: After confirmation, before inserting transactions, check for existing rows with the same `(account_id, date, amount_milliunits, description)`. Skip exact duplicates silently; surface near-duplicates (same date + amount, different description) as a warning.

### Institution Memory
- If user answers yes to the follow-up question, `InstitutionProfile` row saved with:
  - Institution name
  - Format hints (JSON): detected column names/positions, date format, amount format, account name pattern
  - Notes (AI-generated summary of what was learned)
- On future uploads, AI checks for a matching institution profile and uses it as additional context in the normalization prompt
- Institution profiles are visible/editable on the Import page (collapsible section)

### External Accounts
- External accounts appear as a distinct "External Accounts" section in reports
- Users can associate an external account with a YNAB account (optional)
- Account types: checking, savings, investment, retirement, credit, loan, mortgage, other
- Accounts can be soft-deactivated (hidden from reports without deleting history)

### OCR Strategy
- Primary: `pdfplumber` text extraction
- Fallback (low text yield): render PDF pages to images via `pymupdf` (bundles its own MuPDF, no system deps beyond what Docker already installs) → base64-encode → send to AI vision API
- Ollama fallback: if no vision capability, prompt the user in the chat: "This appears to be a scanned document. Could you describe what's in it or type the key figures?"

---

## Architecture

### New Files

#### `app/models/import_data.py`
Four ORM models:

| Model | Key Columns |
|---|---|
| `InstitutionProfile` | `id`, `name`, `format_hints` (JSON text), `notes`, `created_at`, `updated_at` |
| `ImportSession` | `id`, `file_name`, `file_hash`, `status` (pending/reviewing/confirmed/cancelled/failed), `data_type`, `institution_name`, `messages_enc` (Fernet, defense in depth), `extracted_data_enc` (Fernet, defense in depth), `file_content_enc` (Fernet, cleared after confirm), `created_at`, `confirmed_at` |
| `ExternalAccount` | `id`, `name`, `institution`, `account_type`, `ynab_account_id` (nullable FK), `notes`, `is_active`, `created_at` |
| `ExternalTransaction` | `id`, `external_account_id`, `date`, `amount_milliunits`, `description`, `category`, `import_session_id`, `created_at` |
| `ExternalBalance` | `id`, `external_account_id`, `balance_milliunits`, `as_of_date`, `notes`, `contribution_milliunits`, `return_bps`, `import_session_id`, `created_at` |

All monetary values in milliunits. The entire database is encrypted by SQLCipher (AES-256), so all columns are encrypted at rest automatically. Import session fields (`messages_enc`, `extracted_data_enc`, `file_content_enc`) receive additional Fernet encryption as defense in depth since they contain raw user-uploaded documents and AI conversation history.

#### `app/services/import_service.py`
Pure service; no router code. Key functions:

- `extract_text(file_bytes: bytes, filename: str) -> tuple[str, bool]` — returns `(text, is_low_yield)`
- `extract_via_vision(file_bytes: bytes, settings, master_key) -> str` — PDF→images→AI vision OCR
- `check_model_vision_capable(settings, master_key) -> bool` — query Ollama `/api/show` for vision capability (Anthropic/OpenAI assumed capable)
- `normalize_with_ai(text: str, profile: InstitutionProfile | None, settings, master_key) -> dict` — returns structured JSON
- `check_file_duplicate(file_hash: str, db) -> ImportSession | None`
- `check_row_duplicates(rows: list[dict], account_id: int, db) -> list[dict]` — returns list of near-duplicate warnings
- `save_confirmed_import(session_id: int, db, master_key) -> None` — writes external_accounts/transactions/balances
- `get_institution_profile(name: str, db) -> InstitutionProfile | None`
- `save_institution_profile(session_id: int, db) -> InstitutionProfile`

#### `app/routers/import_data.py`

| Endpoint | Method | Description |
|---|---|---|
| `/import` | GET | Upload + review page |
| `/api/import/upload` | POST | Accept file; return session_id + initial analysis (JSON) |
| `/api/import/chat/{session_id}` | POST | Send user message; stream AI reply (SSE) |
| `/api/import/session/{session_id}` | GET | Get current session state (for page reload) |
| `/api/import/confirm/{session_id}` | POST | Save confirmed data |
| `/api/import/cancel/{session_id}` | POST | Discard session |
| `/api/import/institution/{id}` | DELETE | Remove institution profile |

#### `app/templates/import/import.html`
Three visual states managed by JS:
1. **Upload state**: Drag-and-drop zone + "Upload" button
2. **Review state**: Summary card + extracted rows table + chat panel + Confirm/Cancel buttons
3. **Confirmed state**: Success message + summary of what was saved

#### `app/static/js/import.js`
- File drop zone handling (drag/drop + click-to-select)
- Upload via `fetch()` + `FormData`
- Spinner/loading state during AI analysis
- SSE chat handling (same pattern as `chat_widget.js`)
- Table refresh on `[DATA_UPDATE]` SSE event
- Duplicate warning display

### Modified Files

| File | Change |
|---|---|
| `app/main.py` | Import and register `import_data` router |
| `app/database.py` | Register new models in `create_all()`; no migrations needed (new tables only) |
| `app/services/report_service.py` | Query and include external accounts/transactions/balances in `_build_ai_prompt()` |
| `app/templates/dashboard/dashboard.html` | Add **Import** button next to Sync Now |
| `requirements.txt` | Add `pdfplumber`, `pymupdf` |
| `AGENTS.md` | Update directory structure + implementation status |
| `README.md` | Update feature table |
| `docs/configuration.md` | Document any new settings (none expected for Phase 13) |

---

## Report Prompt Integration

In `report_service.py`, after loading the `LifeContextBlock`, also query:
- Active `ExternalAccount` rows with their latest `ExternalBalance`
- `ExternalTransaction` rows from the report period (same month window as YNAB transactions)

Format as a structured text block injected into the AI prompt:

```
External Accounts (as of [date]):
- Vanguard 401(k): $45,230.00 (retirement; as of 2025-01-01)
- Marcus Savings: $12,400.00 (savings; as of 2024-12-15)

External Transactions ([month]):
- 2025-01-15 | Vanguard 401(k) | +$500.00 | Employee contribution
```

If no external data exists, this section is omitted from the prompt (not shown as "none").

---

## New Dependencies

| Package | Purpose | Docker impact |
|---|---|---|
| `pdfplumber` | PDF text extraction (pure Python, uses pdfminer.six) | None — pure Python |
| `pymupdf` | PDF→image for OCR fallback (bundles MuPDF) | Small binary; ~15 MB Docker layer |

`python-multipart` is already a FastAPI dependency and handles file uploads.

---

## Security Considerations

- **All data is protected by SQLCipher** (AES-256 whole-database encryption). Every table — including external accounts, transactions, balances, import sessions, and institution profiles — is encrypted on disk automatically. No field-level encryption is needed for financial data.
- **Import session messages and file content** (`messages_enc`, `file_content_enc`, `raw_content_enc`) receive additional Fernet encryption (defense in depth) since they contain raw user-uploaded documents and AI conversation history. These are cleared after confirmation.
- File hash stored plaintext (it's a hash, not data — used only for duplicate detection)
- No file is written to disk — all processing in memory
- File MIME type validated server-side (not just extension)
- Max file size enforced at the router boundary before any AI call

---

## Implementation Milestones (suggested commit points)

1. **DB models + migrations** — `import_data.py`, register in `database.py`
2. **import_service.py** — text extraction + AI normalization (no chat yet)
3. **Upload endpoint + initial review UI** — `POST /api/import/upload`, import.html upload→review flow, dashboard button
4. **Import chat (SSE)** — `POST /api/import/chat/{id}`, chat panel in import.html, table refresh on DATA_UPDATE
5. **Confirm + cancel** — `POST /api/import/confirm/{id}`, `POST /api/import/cancel/{id}`, institution profile save flow
6. **Report prompt integration** — external data in `report_service.py`
7. **OCR fallback** — vision API path for low-yield PDFs
8. **Docs + cleanup** — AGENTS.md, README.md, docs/configuration.md

---

## Open Questions (resolved)

| Question | Decision |
|---|---|
| PDF + CSV both? | Yes — both at launch |
| AI figures out format? | Yes — AI handles arbitrary layouts; asks follow-ups via chat |
| Institution memory? | Yes — saved after confirmed import if user opts in |
| OCR? | AI vision API (Anthropic/OpenAI) for low-yield PDFs; Ollama fallback = prompt user via chat |
| Human review? | Table + chat hybrid; user can describe corrections in plain language |
| Duplicate detection? | File hash (warn, don't block) + row-level dedup on confirm |
| External accounts in reports? | Yes — "External Accounts" section, standalone if no YNAB association |
| Import button location? | Dashboard, next to Sync Now |
| External data in AI prompt? | Yes — accounts with latest balances + transactions for the report period |
