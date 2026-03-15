# Configuration Reference

YNAB Financial Report uses a two-tier configuration system:

1. **`.env` file** — Fully optional. Only needed to change the default port or sync schedule. Contains no secrets.
2. **Settings UI** — All configuration (API keys, AI provider, SMTP, etc.) is done through the browser at `/settings`. Values are stored encrypted in the database.

> **No command-line configuration is required.** The master password and all API keys are set up through the browser on first run.

---

## .env File

The `.env` file is optional. If you don't create one, the app uses its built-in defaults (port 8080, sync on the 1st of each month).

If you do want to customize these settings, copy `.env.example` to `.env` and uncomment the relevant lines. The `.env` file is gitignored and must never be committed.

**Do not add API keys or passwords to `.env`.** All secrets are entered through the browser Settings page.

---

### `PORT`
**Optional.** Default: `8080`

The host port the app is accessible on. Change this if port 8080 is already in use on your machine.

**Example:** `PORT=9000`
**Access the app at:** `http://localhost:9000`

---

### `SYNC_DAY_OF_MONTH`
**Optional.** Default: `1`

The day of the month on which the app automatically syncs YNAB data and generates a new report. Set to `1` for the 1st of each month.

**Valid range:** 1–28 (use 28 or lower to avoid issues with February)
**Example:** `SYNC_DAY_OF_MONTH=5` — syncs on the 5th of every month

---

## Settings UI

All of the following are configured through the browser at `http://localhost:8080/settings`. Values are encrypted before being stored in the database.

---

### YNAB Settings

#### YNAB API Key
**Required.**

Your YNAB Personal Access Token. Generated at: YNAB → My Account → Developer Settings → New Token.

The app uses this key read-only to fetch budget data, transactions, categories, and accounts. It cannot modify your budget.

#### YNAB Budget ID
**Required.**

The UUID of the YNAB budget to report on. Found in the URL when viewing your budget:
`https://app.youneedabudget.com/{BUDGET-ID}/budget`

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

The model name to use for AI analysis. Must be a model available to your chosen provider and API key.

| Provider | Example models |
|---|---|
| Anthropic | `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-haiku-4-5` |
| OpenAI | `gpt-4o`, `gpt-4o-mini`, `o1-mini` |
| OpenRouter | Any model slug from [openrouter.ai/models](https://openrouter.ai/models) |
| Ollama | Any model you've pulled locally, e.g. `llama3`, `mistral`, `phi3` |

---

### Email Settings (Optional)

Email settings are optional. When configured, the app can send you reports and notifications via your own SMTP server.

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
The email address to deliver reports to. Can be the same as From Address.

#### Use TLS
Whether to use TLS/STARTTLS encryption for the SMTP connection. **Strongly recommended.** Only disable if your mail server requires it.

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

## Environment Variable Summary

| Variable | Where set | Required | Default | Description |
|---|---|---|---|---|
| `PORT` | `.env` (optional) | No | `8080` | Host port for the web app |
| `SYNC_DAY_OF_MONTH` | `.env` (optional) | No | `1` | Day of month for automatic sync |
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
| Enable Notion | Settings UI | No | `false` | Toggle Notion sync |
| Notion API Key | Settings UI | No | — | Notion integration token (encrypted) |
| Notion Database ID | Settings UI | No | — | Target Notion database UUID |
