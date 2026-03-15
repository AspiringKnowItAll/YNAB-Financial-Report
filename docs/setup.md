# Setup Guide

This guide walks through a complete installation of YNAB Financial Report from scratch. No prior coding experience is required. After running one command to start the app, everything else is done through your browser.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Get Your YNAB Personal Access Token](#2-get-your-ynab-personal-access-token)
3. [Find Your YNAB Budget ID](#3-find-your-ynab-budget-id)
4. [Get an AI Provider API Key](#4-get-an-ai-provider-api-key)
5. [Install and Start the App](#5-install-and-start-the-app)
6. [Create Your Master Password](#6-create-your-master-password)
7. [Save Your Recovery Codes](#7-save-your-recovery-codes)
8. [Complete the Settings Page](#8-complete-the-settings-page)
9. [Complete the Personal Profile Wizard](#9-complete-the-personal-profile-wizard)
10. [Run Your First Sync](#10-run-your-first-sync)
11. [Optional: Email Setup](#11-optional-email-setup)
12. [Optional: Notion Sync](#12-optional-notion-sync)
13. [Keeping Your Data Safe](#13-keeping-your-data-safe)

---

## 1. Prerequisites

You will need the following installed on your computer:

### Docker Desktop
Docker runs the app in a container so you don't need to install Python or any other software manually.

- **Windows / Mac:** Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux:** Follow the [Docker Engine installation guide](https://docs.docker.com/engine/install/) for your distribution, then install [Docker Compose](https://docs.docker.com/compose/install/)

To verify Docker is working, open a terminal and run:
```
docker --version
docker compose version
```
Both commands should print version numbers without errors.

### Git (to download the app)
- **Windows:** Download [Git for Windows](https://git-scm.com/download/win)
- **Mac:** Run `git --version` in Terminal — it will prompt you to install if missing
- **Linux:** `sudo apt install git` (Ubuntu/Debian) or equivalent

### A Terminal / Command Prompt
This is the **only** time you'll need the terminal — just to download and start the app.
- **Windows:** Use "Command Prompt" or "PowerShell" (search in the Start menu)
- **Mac:** Use "Terminal" (in Applications → Utilities)
- **Linux:** Any terminal emulator

---

## 2. Get Your YNAB Personal Access Token

A Personal Access Token lets the app read your YNAB data. It is read-only by default — the app cannot modify your budget.

1. Log in to [app.youneedabudget.com](https://app.youneedabudget.com)
2. Click your name in the top-left corner, then click **"My Account"**
3. Scroll down to the **"Developer Settings"** section
4. Click **"New Token"**
5. Enter a label (e.g., `Financial Report App`) and click **"Generate"**
6. **Copy the token immediately** — it will only be shown once

> Keep this token private. Anyone with it can read your YNAB data.

---

## 3. Find Your YNAB Budget ID

The Budget ID tells the app which of your YNAB budgets to use.

1. Log in to [app.youneedabudget.com](https://app.youneedabudget.com)
2. Open the budget you want to use
3. Look at the URL in your browser. It will look like:
   ```
   https://app.youneedabudget.com/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/budget
   ```
4. The long string of letters and numbers between the slashes is your Budget ID. Copy it.

---

## 4. Get an AI Provider API Key

The app uses an AI model to write financial analysis and recommendations. You need an account with at least one of the following providers:

### Option A: Anthropic (Recommended)
Claude models produce high-quality financial analysis.

1. Create an account at [console.anthropic.com](https://console.anthropic.com)
2. Go to **"API Keys"** in the left sidebar
3. Click **"Create Key"**, give it a name, and copy the key
4. Add some credits to your account (usage is pay-per-use, typically a few cents per report)
5. In the Settings page, select **"Anthropic"** and enter the model `claude-sonnet-4-6`

### Option B: OpenAI
1. Create an account at [platform.openai.com](https://platform.openai.com)
2. Go to **"API Keys"** in the left menu
3. Click **"Create new secret key"** and copy it
4. In the Settings page, select **"OpenAI"** and enter the model `gpt-4o`

### Option C: OpenRouter
OpenRouter gives you access to many models (including Claude and GPT) via one API key.

1. Create an account at [openrouter.ai](https://openrouter.ai)
2. Go to **"Keys"** and create a new key
3. In the Settings page, select **"OpenRouter"**, enter your key and desired model slug

### Option D: Ollama (Local / No API Key Required)
If you have Ollama running locally, you can use it for fully offline AI analysis.

1. Install [Ollama](https://ollama.ai) and pull a model (e.g., `ollama pull llama3`)
2. Make sure Ollama is running on your machine
3. In the Settings page, select **"Ollama"** and enter your base URL (e.g., `http://host.docker.internal:11434/v1`)
   - Note: from inside Docker, use `host.docker.internal` instead of `localhost` to reach your host machine

---

## 5. Install and Start the App

Open a terminal and run the following commands:

```bash
# Download the app
git clone https://github.com/AspiringKnowItAll/YNAB-Financial-Report.git
cd YNAB-Financial-Report

# Start the app
docker-compose up -d
```

Docker will download the required images and start the app. This may take a few minutes on first run.

Once started, open your browser and go to: **http://localhost:8080**

You will be taken to the Master Password setup page. If you see an error instead, check the [troubleshooting section](#troubleshooting) below.

---

## 6. Create Your Master Password

On first launch, the app will ask you to create a **Master Password**. This is the most important step in the setup process.

The master password:
- **Encrypts all your stored API keys and settings** — nothing sensitive is saved without it
- **Is never stored anywhere** — only a mathematical fingerprint is kept; the password itself cannot be recovered from the app's data
- **Is required to unlock the app** after each restart of the Docker container
- **Cannot be reset** — if lost, the only recovery option is your recovery codes (next step)

### Choosing a strong master password

- Use a passphrase of 4+ random words (e.g., `correct-horse-battery-staple`)
- Or use a strong random password from a password manager
- Store it in a password manager — do not rely on memory alone

Enter your chosen password, confirm it, and click **"Create Master Password"**.

---

## 7. Save Your Recovery Codes

After creating your master password, the app will display **8 recovery codes**. These are one-time-use backup codes that can fully restore access to the app — including all your stored API keys — if you ever forget your master password.

**How recovery codes work:**
- Each code is a single-use backup master password
- Using a recovery code unlocks the app with full access, then prompts you to set a new master password and generate fresh codes
- Once used, a code is permanently invalidated

**What to do with your recovery codes:**

1. Click **"Print Recovery Codes"** to open a printer-friendly page
2. Print the page and store it somewhere secure (e.g., a safe, a locked drawer)
3. Alternatively, save them in a password manager — but a physical printout is recommended as a backup
4. Do not store them in the same place as your master password

> **These codes are shown exactly once.** If you close this page without saving them, you can generate new codes from the Settings page, but only while you are already logged in. If you are locked out and have no recovery codes, there is no way to recover your stored secrets.

Click **"I have saved my recovery codes"** to continue to the Settings page.

---

## 8. Complete the Settings Page

The Settings page is where you enter your API keys and configure the app. Fill in:

**YNAB (required)**
- **YNAB API Key** — the token you generated in step 2
- **Budget ID** — the ID you found in step 3
- Click **"Test Connection"** to verify everything works

**AI Provider (required)**
- Select your provider from the dropdown
- Enter your API key (not required for Ollama)
- Enter the model name
- For OpenRouter or Ollama, enter the base URL
- Click **"Test Connection"** to verify

**Email (optional)**
- See [Optional: Email Setup](#11-optional-email-setup)

**Notion (optional)**
- See [Optional: Notion Sync](#12-optional-notion-sync)

Click **"Save Settings"** when done. You will be redirected to the personal profile wizard.

---

## 9. Complete the Personal Profile Wizard

The wizard collects context about your living situation so the AI can give you more relevant recommendations. You will be asked:

- How many people are in your household
- Your income type (salary, hourly, freelance, or variable)
- Your financial goals (save an emergency fund, pay off debt, etc.)
- Whether you rent, own, or share your home
- Any additional context you want the AI to know about your finances

Your answers are stored locally in your database and used only to personalize the AI analysis. Click **"Save and Continue"** after each step.

---

## 10. Run Your First Sync

After completing the wizard, you will be on the dashboard. Since no data has been synced yet, the dashboard will be empty.

To pull your data from YNAB for the first time:

1. Click the **"Sync Now"** button on the dashboard
2. Wait for the sync to complete (this may take 30–60 seconds depending on how much transaction history you have)
3. Once done, the dashboard will populate with charts and your first AI report

The app will automatically sync and generate a new report on the day of the month you configured (default: the 1st of each month).

---

## 11. Optional: Email Setup

If you want the app to email you reports, you need an SMTP server. You can use:

- **Gmail:** Enable [App Passwords](https://support.google.com/accounts/answer/185833) in your Google account, then use `smtp.gmail.com` port `587` with TLS enabled
- **Outlook/Hotmail:** Use `smtp-mail.outlook.com` port `587` with TLS enabled
- **Your own mail server:** Enter your server's SMTP details directly

In the Settings page, under **"Email"**:

| Field | Description |
|---|---|
| SMTP Host | Your mail server address (e.g., `smtp.gmail.com`) |
| SMTP Port | Usually `587` (TLS) or `465` (SSL) |
| Username | Your email address or SMTP username |
| Password | Your email password or app password |
| From Address | The address emails will be sent from |
| To Address | Where to send the reports (can be the same as From) |
| Use TLS | Recommended: leave enabled |

Click **"Send Test Email"** to verify the configuration works before saving.

---

## 12. Optional: Notion Sync

If you use Notion and want report summaries automatically posted there:

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) and create a new integration
2. Give it a name (e.g., `Financial Report`), select your workspace, and click **"Submit"**
3. Copy the **"Internal Integration Token"**
4. In Notion, open (or create) the database where you want reports to appear
5. Click the **"..."** menu in the top-right → **"Add connections"** → select your integration
6. Copy the database ID from the URL (the 32-character string after the last `/` and before the `?`)

In the Settings page, under **"Notion"**:
- Enable the Notion toggle
- Paste your Integration Token
- Paste your Database ID

---

## 13. Keeping Your Data Safe

### Unlocking the app after a restart
Each time the Docker container restarts, the app will show the **Unlock** screen. Enter your master password to resume access. Your data is never lost on restart — only the in-memory key is cleared.

### If you forget your master password
Use one of your recovery codes on the Unlock screen (click **"Use a recovery code"**). This will restore full access and prompt you to set a new master password and generate new recovery codes.

### Generating new recovery codes
You can generate a fresh set of recovery codes at any time from **Settings → Security → Regenerate Recovery Codes**. This invalidates all existing codes.

### Backing up your data
Your financial history is stored in a Docker volume. To back it up:

```bash
# Create a backup of the database and key files
docker run --rm -v ynab-financial-report_ynab_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/ynab_report_backup_$(date +%Y%m%d).tar.gz -C /data .
```

Keep this backup file safe. It contains your encrypted data; without your master password or recovery codes, the encrypted secrets inside cannot be read.

### Updating the app
```bash
git pull
docker-compose down
docker-compose up -d --build
```

### ⚠️ WARNING: Data deletion
Running `docker-compose down -v` will **permanently delete** all your financial history, stored settings, and recovery key files. The `-v` flag removes Docker volumes. Only use it if you want to start completely fresh.

Safe shutdown (data preserved):
```bash
docker-compose down      # stops the app, data is safe
docker-compose up -d     # starts it again, enter master password to unlock
```

---

## Troubleshooting

### The app won't start

Check the logs:
```bash
docker-compose logs
```

Common causes:
- Port 8080 is already in use — create a `.env` file with `PORT=9000` (or any free port)

### I forgot my master password

Use a recovery code on the Unlock screen. If you have no recovery codes, there is no way to recover the stored secrets — you will need to reset the app completely:

```bash
docker-compose down -v   # WARNING: permanently deletes all data
docker-compose up -d     # fresh start, go through setup again
```

### "Test Connection" fails for YNAB

- Double-check that you copied the full API token with no extra spaces
- Verify the Budget ID matches the one in your YNAB URL exactly
- Make sure your YNAB token hasn't expired (you can regenerate it in YNAB Developer Settings)

### The AI test connection fails

- Verify your API key is correct and has available credits
- For Ollama: ensure Ollama is running and the model is downloaded (`ollama list`)
- For Ollama from Docker: use `http://host.docker.internal:11434/v1` not `http://localhost:11434/v1`

### Charts are empty after sync

- Check the sync log on the dashboard for any error messages
- Ensure your YNAB budget has transactions in it
- Try triggering a manual sync again

---

*For more configuration options, see [configuration.md](configuration.md).*
*For development and contribution information, see [development.md](development.md).*
