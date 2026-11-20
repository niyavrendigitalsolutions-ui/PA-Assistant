# Personal Assistant

An AI personal assistant built on the [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python). Chat with it on **WhatsApp**, or in the terminal. It runs 24/7 on **Fly.io** and deploys automatically from **GitHub**.

## What it does

- **To-dos, notes, reminders, memory:** stored on a persistent disk. Reminders are sent to your WhatsApp when they fall due.
- **Gmail:** search and read mail, and save **drafts**. It can never send.
- **Google Calendar:** see your schedule and create events (it confirms first).
- **Web search**, day planning, summaries, drafting messages.

## Safety design

- Only your WhatsApp number gets answers. Every webhook call is checked against your Meta app secret.
- No shell and no file access. Only its own tools, Gmail/Calendar and the web.
- Email and web text is treated as untrusted information, never as instructions.
- Drafts only: nothing is emailed on your behalf. Deleting and creating events needs your yes.
- Secrets live in Fly secrets and GitHub secrets, never in the repo (`.env` is git-ignored).

## Deploy (about 30 minutes, once)

Follow [DEPLOY.md](DEPLOY.md). In short: create the Meta WhatsApp app and Google credentials, `fly launch`, set secrets, add `FLY_API_TOKEN` to GitHub. After that, every push to `main` runs the tests and deploys.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # add ANTHROPIC_API_KEY
set -a && source .env && set +a
python assistant.py      # terminal chat
python -m pytest         # tests
```

## Files

| File | Purpose |
|---|---|
| `server.py` | WhatsApp webhook, reminder sender |
| `assistant.py` | System prompt, options, terminal chat |
| `tools.py`, `storage.py` | To-dos, notes, reminders, memory |
| `google_tools.py`, `get_google_token.py` | Gmail and Calendar, one-time token helper |
| `Dockerfile`, `fly.toml` | Container and Fly.io settings |
| `.github/workflows/deploy.yml` | Test, then deploy on push to `main` |

## Known limits

- **WhatsApp 24-hour rule:** free-form messages only work within 24 hours of your last message to it. A reminder due later than that can fail; it retries a few times, then gives up. Fix: message it once a day, or add an approved message template (not included).
- One person, one Fly machine (the disk attaches to one machine). Chat history resets on restart; facts, tasks, notes and reminders persist.
- Costs: Fly machine (a few dollars a month) plus Anthropic API usage per message. WhatsApp Cloud API conversation fees may apply.
