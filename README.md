# Personal Assistant

An AI personal assistant built on the [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python). Use it in the terminal, or through a private web chat page. It runs 24/7 on **Fly.io** and deploys automatically from **GitHub**.

## What it does

- **To-dos, notes, reminders, memory:** stored on a persistent disk. Due reminders appear in the chat page.
- **Gmail:** search and read mail, and save **drafts**. It can never send.
- **Google Calendar:** see your schedule and create events (it confirms first).
- **Web search**, day planning, summaries, drafting messages.

## Safety design

- The web page and API need your secret access token (`ASSISTANT_ACCESS_TOKEN`). Without it, nothing is answered.
- No shell and no file access. Only its own tools, Gmail/Calendar and the web.
- Email and web text is treated as untrusted information, never as instructions.
- Drafts only: nothing is emailed on your behalf. Creating events needs your yes.
- Secrets live in Fly secrets and GitHub secrets, never in the repo (`.env` is git-ignored).

## Deploy (about 20 minutes, once)

Follow [DEPLOY.md](DEPLOY.md). In short: create Google credentials (optional), `fly launch`, set secrets, add `FLY_API_TOKEN` to GitHub. After that, every push to `main` runs the tests and deploys.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # add ANTHROPIC_API_KEY (and ASSISTANT_ACCESS_TOKEN for the web service)
set -a && source .env && set +a
python assistant.py                    # terminal chat
uvicorn server:app --port 8080         # web chat at http://localhost:8080
python -m pytest                       # tests
```

## Files

| File | Purpose |
|---|---|
| `server.py` | Private web chat page and API |
| `assistant.py` | System prompt, options, terminal chat |
| `tools.py`, `storage.py` | To-dos, notes, reminders, memory |
| `google_tools.py`, `get_google_token.py` | Gmail and Calendar, one-time token helper |
| `Dockerfile`, `fly.toml` | Container and Fly.io settings |
| `.github/workflows/deploy.yml` | Test, then deploy on push to `main` |

## Known limits

- Reminders only appear while the chat page is open. Nothing is pushed to your phone. If you close the page, they wait and show up when you next open it.
- One person, one Fly machine (the disk attaches to one machine). Chat history resets on restart; facts, tasks, notes and reminders persist.
- The access token is the only lock. Use a long random one, share it with nobody, and keep the site on HTTPS (Fly does this).
- Costs: a small Fly machine (a few dollars a month) plus Anthropic API usage per message.
