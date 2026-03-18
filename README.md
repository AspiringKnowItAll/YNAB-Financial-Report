# YNAB Financial Report

A self-hosted financial dashboard that connects to your [YNAB](https://www.youneedabudget.com/) account, tracks spending trends over time, and delivers AI-powered financial insights — all running in a Docker container you control.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

---

## What it does

- **Syncs your YNAB data** monthly (or on demand) and stores it locally
- **Visualizes spending trends** with interactive charts — with statistical outlier handling so one big purchase doesn't skew your averages
- **Generates AI reports** with an executive summary, notable patterns, concerns, and actionable recommendations
- **Tracks savings rate** and budget adherence over time
- **Exports reports** as PDF or HTML
- **Emails reports** to yourself via your own mail server
- **Builds a financial life story** via an AI chat that learns your personal context and injects it into every report for more relevant, personalized advice
- **Optionally syncs** report summaries to a Notion database

Your data never leaves your machine (except to the AI provider you choose).

---

## Quick Start

**Prerequisites:** [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

```bash
# 1. Clone the repo
git clone https://github.com/AspiringKnowItAll/YNAB-Financial-Report.git
cd YNAB-Financial-Report

# 2. Start the app
docker-compose up -d
```

Open **http://localhost:8080** — the setup wizard will guide you through everything in the browser. No command-line configuration required.

For a full walkthrough, see [docs/setup.md](docs/setup.md).

---

## Features

| Feature | Details |
|---|---|
| YNAB sync | Delta sync using `last_knowledge_of_server` — only changed data is fetched after the first run |
| Interactive charts | Plotly-powered, in-browser charts for spending trends, savings rate, and budget vs actual |
| Outlier handling | IQR-based statistical outlier detection removes one-time spikes from trend calculations |
| AI insights | Works with Anthropic, OpenAI, OpenRouter, or a local Ollama instance |
| Life Context Chat | Conversational AI chat that builds a financial life story; context is compressed and injected into every AI report |
| Report export | Download any report as PDF or self-contained HTML |
| Email delivery | Sends reports via your own SMTP server — no third-party email infrastructure |
| Notion sync | Optionally posts report summaries to a Notion database |
| External data import | Upload bank/investment PDFs or CSVs; AI normalizes to structured data; user reviews before saving; included in AI reports |
| Encrypted storage | Entire database encrypted with SQLCipher (AES-256); API keys also receive field-level Fernet encryption; master key derived via Argon2id |
| Recovery codes | 8 single-use backup codes generated at setup — full access recovery if master password is lost |

---

## Configuration

Everything is configured through the browser — no command-line setup required. The `.env` file is optional and only needed if you want to change the port or sync schedule.

See [docs/configuration.md](docs/configuration.md) for a full reference of all available options.

---

## AI Provider Support

You can use any of the following:

- **Anthropic** — Claude models (claude-sonnet-4-6, etc.)
- **OpenAI** — GPT-4o and other OpenAI models
- **OpenRouter** — Access to many models via a single API key
- **Ollama** — Point at your local Ollama instance for fully offline AI analysis

---

## Security

This app handles personal financial data. Security decisions made in this project:

- **Master password** set in the browser on first run — never stored in plaintext anywhere
- **Argon2id** key derivation — the encryption key is derived from your password, held in memory only, and never written to disk
- **Recovery codes** generated after setup — 8 single-use backup codes that can fully restore access if your master password is forgotten; protected by a threading lock against TOCTOU races
- **App locks on restart** — enter your master password in the browser to unlock after each container restart
- **Non-root Docker user** — container runs as `appuser` (UID 1000), not root
- All secrets stored in SQLite are encrypted at rest using AES (Fernet)
- Entire SQLite database encrypted with SQLCipher (AES-256); app fails fast at startup if SQLCipher is not installed
- All user inputs are validated and sanitized before processing; AI-returned data validated via Pydantic before ORM insert
- SSE streams and stored AI commentary never leak internal exception details to clients
- No raw SQL — all database access via SQLAlchemy ORM
- No data is transmitted to any third party except the AI provider and YNAB API you configure

See [AGENTS.md](AGENTS.md) for full security requirements applied to this codebase.

---

## Roadmap

- [x] Core architecture and documentation
- [x] Settings UI with encrypted secret storage
- [x] YNAB sync pipeline
- [x] Dashboard with Plotly charts
- [x] AI commentary and report snapshots
- [x] Historical report browser and PDF/HTML export
- [x] Email delivery via user-configured SMTP server
- [x] Automated scheduler (daily / weekly / biweekly / monthly / yearly)
- [x] Test suite and hardening
- [x] Life Context Chat — conversational AI financial life story with versioned context blocks
- [x] External data import — upload bank/investment PDFs and CSVs; AI normalizes and extracts data; review and confirm before saving
- [x] Security hardening — non-root Docker user, TOCTOU lock on recovery codes, Pydantic row validation, SSE error redaction, SQLCipher fail-fast, atomic file writes, strict month validation
- [~] Dashboard redesign — multi-dashboard builder with gridstack.js drag/resize, 17 configurable widget types, per-widget filters *(in progress — M1 foundation + M2 builder + M3 core widgets complete)*
- [ ] Notion sync *(post-v1)*

---

## Running Tests

```bash
# Install dependencies (includes test packages)
pip install -r requirements.txt

# Run the full suite
pytest

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run a specific file
pytest tests/unit/test_analysis_service.py -v
```

See [docs/development.md](docs/development.md) for full details on the test architecture.

---

## Contributing

See [docs/development.md](docs/development.md) for local development setup and contribution guidelines.

---

## License

[MIT](LICENSE) — free to use, modify, and distribute with attribution.
