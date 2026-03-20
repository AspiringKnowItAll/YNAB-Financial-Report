# Configuration Reference

YNAB Financial Report uses a two-tier configuration system:

1. **`.env` file** — Fully optional. Only needed to change the default port. Contains no secrets.
2. **Settings UI** — All configuration (API keys, AI provider, SMTP, schedule, etc.) is done through the browser at `/settings`. Values are stored encrypted in the database.

> **No command-line configuration is required.** The master password and all API keys are set up through the browser on first run.

---

## .env File

The `.env` file is optional. If you don't create one, the app uses its built-in default (port 8080).

If you do want to customize this, copy `.env.example` to `.env` and uncomment the relevant line. The `.env` file is gitignored and must never be committed.

**Do not add API keys or passwords to `.env`.** All secrets are entered through the browser Settings page.

---

### `PORT`
**Optional.** Default: `8080`

The host port the app is accessible on. Change this if port 8080 is already in use on your machine.

**Example:** `PORT=9000`
**Access the app at:** `http://localhost:9000`

---

### `ALLOW_PLAINTEXT_DB`
**Test environments only.** Default: unset (plaintext DB is not permitted)

When set to `1`, allows the app to start without the `sqlcipher3-binary` package installed, falling back to the standard unencrypted `sqlite3` library. This is exclusively for running the test suite on a host machine that does not have SQLCipher installed.

**Do not set this in production.** In a production Docker deployment, `sqlcipher3-binary` is always present and this variable must not be set.

**Example (running tests locally without Docker):**
```bash
ALLOW_PLAINTEXT_DB=1 pytest
```

---

## Settings UI

All of the following are configured through the browser at `http://localhost:8080/settings`. Values are encrypted before being stored in the database.

---

### YNAB Settings

#### YNAB API Key
**Required.**

Your YNAB Personal Access Token. Generated at: YNAB → My Account → Developer Settings → New Token.

The app uses this key read-only to fetch budget data, transactions, categories, and accounts. It cannot modify your budget.

#### YNAB Budget
**Required.**

The YNAB budget to report on. After entering your API key, click **"Test connection"** — the app will connect to YNAB and populate a dropdown with your available budgets. Select the one you want to use. The budget ID is stored automatically.

---

### AI Provider Settings

#### AI Provider
**Required.**

The AI service used to generate financial commentary and recommendations. One of:

| Value | Provider | Notes |
|---|---|---|
| `anthropic` | Anthropic | Requires API key. Models: `claude-sonnet-4-6`, `claude-opus-4-6`, etc. |
| `openai` | OpenAI | Requires API key. Models: `gpt-4o`, `gpt-4o-mini`, etc. |
| `openrouter` | OpenRouter | Requires API key and base URL. Access to many models. |
| `ollama` | Ollama | No API key required. Requires base URL. Fully local/offline. |

#### AI API Key
**Required for Anthropic, OpenAI, and OpenRouter. Not used for Ollama.**

Your API key for the selected provider.

#### AI Base URL
**Required for OpenRouter and Ollama. Optional for Anthropic/OpenAI.**

The base URL for the API endpoint.

| Provider | Default / Expected URL |
|---|---|
| Anthropic | `https://api.anthropic.com` (default, leave blank) |
| OpenAI | `https://api.openai.com/v1` (default, leave blank) |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Ollama (local) | `http://host.docker.internal:11434/v1` |

> When accessing Ollama from inside Docker, use `host.docker.internal` instead of `localhost`.

#### AI Model
**Required.**

The model name to use for AI analysis. After configuring the provider, API key, and base URL (if applicable), click **"Test connection"** — the app will query the provider for available models and populate a searchable dropdown. You can select from the list or type any model name manually.

| Provider | Example models |
|---|---|
| Anthropic | `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-haiku-4-5` |
| OpenAI | `gpt-4o`, `gpt-4o-mini`, `o1-mini` |
| OpenRouter | Any model slug from [openrouter.ai/models](https://openrouter.ai/models) |
| Ollama | Any model you've pulled locally, e.g. `llama3`, `mistral`, `phi3` |

---

### Email Settings (Optional)

Email is optional. When configured, the app can send you reports via your own SMTP server — either automatically on a schedule or on demand from the report detail page.

#### SMTP Host
Hostname of your mail server.
- Gmail: `smtp.gmail.com`
- Outlook/Hotmail: `smtp-mail.outlook.com`
- Custom: your server's hostname or IP

#### SMTP Port
Port number for your mail server.
- `587` — STARTTLS (recommended)
- `465` — SSL/TLS
- `25` — Unencrypted (not recommended)

#### SMTP Username
Your login username for the mail server. Usually your email address.

#### SMTP Password
Your mail server password. For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833), not your regular Google password.

#### From Address
The email address that reports will be sent from. Must be a valid email format.

#### To Address
The email address(es) to deliver reports to. Accepts a single address or a comma-separated list (e.g. `alice@example.com, bob@example.com`).

#### Use TLS
Whether to use TLS/STARTTLS encryption for the SMTP connection. **Strongly recommended.** Only disable if your mail server requires it.

---

### Scheduler Settings (Optional)

The scheduler automates your monthly financial workflow — syncing YNAB, generating a report, and optionally emailing it — on a recurring schedule you define. All schedule settings are configured in the browser.

#### Enable Automated Schedule
Toggle to enable or disable the scheduler. When disabled, all sync and report generation remains manual.

#### Frequency
How often the automated job runs. Options:

| Frequency | Description | Additional fields |
|---|---|---|
| Daily | Every day at 2:00 AM | None |
| Weekly | Once per week at 2:00 AM | Day of week |
| Every two weeks | Every other week at 2:00 AM | Day of week |
| Monthly | Once per month at 2:00 AM | Day of month (1–28) |
| Yearly | Once per year at 2:00 AM | Month + Day of month |

#### Day of week
*Required for Weekly and Every two weeks.* The day the job fires (Monday–Sunday).

#### Month
*Required for Yearly.* The calendar month the job fires in.

#### Day of month
*Required for Monthly and Yearly.* The day of the month the job fires (1–28). Values above 28 are capped to avoid end-of-month issues in February.

#### Report period
Which calendar month the generated report covers:

| Option | Description |
|---|---|
| Previous calendar month | Reports on the last fully completed month (recommended). A job on the 1st generates the prior month's summary. |
| Current calendar month | Reports on the in-progress current month. Useful for mid-month pulse checks. |

#### Automatically email the report
When enabled, the report is emailed immediately after generation using the Email Delivery settings above. Requires email delivery to be enabled and configured.

---

### Notion Settings (Optional)

Notion sync is optional. When enabled, the app posts a summary of each generated report as a new page in a Notion database.

#### Enable Notion Sync
Toggle to enable or disable Notion sync. Disabling this skips the Notion step after report generation without removing your stored credentials.

#### Notion API Key
Your Notion Internal Integration Token. Created at [notion.so/my-integrations](https://www.notion.so/my-integrations).

Your integration must be connected to the target database. See [docs/setup.md — Optional: Notion Sync](setup.md#10-optional-notion-sync) for detailed steps.

#### Notion Database ID
The ID of the Notion database where report pages will be created. Found in the database URL:
`https://www.notion.so/{workspace}/{DATABASE-ID}?v=...`

---

### Advanced Settings

#### Life Context Pre-Prompt
**Optional.** Default: built-in system prompt defined in `life_context_service.py`

The system prompt that guides the AI during Life Context Chat sessions. Controls what topics the AI covers, how it asks questions, and what it includes in the compressed context block.

The default prompt is shown in read-only form on the Settings page (Advanced section). To customize it, click **"Load Default into Editor"** to copy the default into the editable textarea, then modify as needed and click **"Save Settings"**.

To revert to the default, clear the textarea and save — an empty field restores the built-in prompt.

> **Note:** Changes to the pre-prompt only affect new chat sessions. Existing context blocks are unaffected.

### Financial Projections Settings (Optional)

These settings configure the parameters used by the Savings Projection and Investment Tracker dashboard widgets.

#### Expected Annual Return Rate
**Optional.** Default: 7.0%

The expected annual investment return rate, entered as a percentage (e.g. `7.0` for 7%). Used for compound-interest calculations in the Savings Projection and Investment Tracker widgets. Adjust to reflect your expected portfolio return.

#### Retirement Target Amount
**Optional.** Default: not set

Your target retirement savings balance, entered in dollars (e.g. `2000000` for $2,000,000). When set, a horizontal target line is shown on the Savings Projection widget so you can see when your projected savings is expected to reach your goal. Leave blank if not applicable.

---

## Data Security

All financial data is encrypted at rest. The app uses a two-layer encryption architecture:

### Layer 1: Whole-Database Encryption (SQLCipher)

The SQLite database file (`/data/ynab_report.db`) is encrypted using **SQLCipher** (AES-256). Every byte of the database — including all transaction data, account names, balances, category names, and AI-generated report content — is encrypted on disk.

- The encryption key is derived from your **master password** using Argon2id
- The key is held in memory only while the app is unlocked and is never written to disk
- The database cannot be opened or read without the master password — even with direct access to the Docker volume or backup files, the data is inaccessible
- Opening the database file with a standard SQLite tool returns "file is not a database"

### Layer 2: Field-Level Encryption (Fernet — Defense in Depth)

API keys, passwords, and tokens stored in the settings database receive an **additional** layer of Fernet encryption (AES-128-CBC + HMAC-SHA256) on top of the whole-database encryption. This provides defense in depth for the most sensitive credentials.

### What This Means for You

- **Your financial data is safe** even if someone gains access to your server, Docker volume, or backup files
- **No configuration required** — encryption is automatic and transparent
- **If you lose your master password**, your data cannot be recovered (unless you have a recovery code). This is by design — it means no one else can recover it either

---

## Environment Variable Summary

| Variable | Where set | Required | Default | Description |
|---|---|---|---|---|
| `PORT` | `.env` (optional) | No | `8080` | Host port for the web app |
| `ALLOW_PLAINTEXT_DB` | `.env` (test only) | No | unset | Set to `1` to allow starting without SQLCipher (unencrypted SQLite fallback). **Never set in production.** |
| YNAB API Key | Settings UI | Yes | — | YNAB Personal Access Token |
| YNAB Budget ID | Settings UI | Yes | — | Target budget UUID |
| AI Provider | Settings UI | Yes | — | `anthropic`, `openai`, `openrouter`, `ollama` |
| AI API Key | Settings UI | Depends | — | Required except for Ollama |
| AI Base URL | Settings UI | Depends | — | Required for OpenRouter and Ollama |
| AI Model | Settings UI | Yes | — | Model name/slug |
| SMTP Host | Settings UI | No | — | Mail server hostname |
| SMTP Port | Settings UI | No | — | Mail server port |
| SMTP Username | Settings UI | No | — | Mail server login |
| SMTP Password | Settings UI | No | — | Mail server password (encrypted) |
| From Address | Settings UI | No | — | Sender email address |
| To Address | Settings UI | No | — | Report delivery address |
| Use TLS | Settings UI | No | `true` | Enable SMTP TLS |
| Enable Schedule | Settings UI | No | `false` | Toggle automated scheduler |
| Schedule Frequency | Settings UI | No | — | `daily`, `weekly`, `biweekly`, `monthly`, `yearly` |
| Report Period | Settings UI | No | `previous_month` | `previous_month` or `current_month` |
| Auto-send Email | Settings UI | No | `false` | Email report after scheduled generation |
| Enable Notion | Settings UI | No | `false` | Toggle Notion sync |
| Notion API Key | Settings UI | No | — | Notion integration token (encrypted) |
| Notion Database ID | Settings UI | No | — | Target Notion database UUID |
| Life Context Pre-Prompt | Settings UI (Advanced) | No | built-in | Custom system prompt for Life Context Chat sessions |
| Expected Return Rate | Settings UI (Projections) | No | 7.0% | Annual return rate % for projection widgets |
| Retirement Target | Settings UI (Projections) | No | — | Target retirement balance in dollars |
