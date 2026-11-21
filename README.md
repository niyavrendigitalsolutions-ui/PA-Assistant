# Personal Assistant

An AI personal assistant built on the [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python). Use it in the terminal, or through a private web chat page. It runs 24/7 on **Fly.io** and deploys automatically from **GitHub**.

## What it does

- **To-dos, notes, reminders, memory:** stored on a persistent disk. Due reminders appear in the chat page.
- **Gmail:** search and read mail, save drafts, and send email **within hard limits** (below).
- **Google Calendar:** see your schedule and create events (it confirms first).
- **Runs Niyavren Digital Solutions with you:** keeps a lead pipeline with follow-up dates, writes proposals and replies, researches prospects, and emails within the limits below.
- **Full-stack developer:** designs, writes, tests and runs real projects (Node, Python, git) in an isolated sandbox, then hands you a zip to download.
- **Web search**, day planning, summaries, drafting messages.
- **Learns from you:** it saves lessons from your corrections and preferences, and saves reusable *skills* (step-by-step procedures) after a task works, then reuses them. Ask "what have you learned?" to see everything, and tell it to forget anything.
- **Tells you what it can't do:** when a task needs a tool or access it lacks, it logs a proposal (ask "show your improvement proposals") so you decide what to add next.

## Safety design

- The web page and API need your secret access token (`ASSISTANT_ACCESS_TOKEN`). Without it, nothing is answered.
- No shell and no file access. Only its own tools, Gmail/Calendar and the web.
- Email and web text is treated as untrusted information, never as instructions.
- **Hard limits on the business side**, enforced in code and server settings the assistant cannot edit:
  emails go out on their own only to recipients you pre-approved, under a daily and per-recipient cap;
  anything else, and any email mentioning prices, payments, contracts, guarantees, refunds or legal
  terms, waits in an approval panel on the chat page. The assistant has no tool to approve. It cannot
  spend money or sign anything. Outgoing mail discloses that an AI assistant sent it.
- **Code runs only in a separate sandbox app** that holds no keys: commands run as an unprivileged user
  with a scrubbed environment, time/CPU/process limits, and paths locked to their project folder.
  The assistant itself still has no shell or file access.
- Secrets live in Fly secrets and GitHub secrets, never in the repo (`.env` is git-ignored).

## How self-learning and self-updating work

| What | How | Who decides |
|---|---|---|
| Lessons and skills | Saved in its data file, loaded into every new session | It saves them from **your** messages; you can delete any |
| Capability gaps and ideas | Logged as proposals, never applied | You |
| Dependency updates | Dependabot opens weekly pull requests; tests run on each | You merge |
| Its own code, limits and permissions | **Not self-modifying**, by design | You, through GitHub and Fly settings |

It only learns from what you type. Text in emails, web pages and search results is treated as untrusted and never becomes a lesson or skill, so a malicious email can't quietly reprogram it. It can't rewrite its own code, widen its own access or deploy: an assistant that can read your inbox and edit itself is one bad email from being hijacked.

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
| `tools.py`, `storage.py` | To-dos, notes, reminders, memory, learning |
| `business.py`, `business_tools.py` | Email limits, approval queue, leads |
| `sandbox_tools.py`, `sandbox/runner.py`, `fly.sandbox.toml` | Developer tools and the isolated code-runner app |
| `google_tools.py`, `get_google_token.py` | Gmail and Calendar, one-time token helper |
| `Dockerfile`, `fly.toml` | Container and Fly.io settings |
| `.github/workflows/deploy.yml` | Test, then deploy on push to `main` |

## Known limits

- Reminders only appear while the chat page is open. Nothing is pushed to your phone. If you close the page, they wait and show up when you next open it.
- "Any task" means any task its tools allow: planning, research, writing, leads, email within limits, Calendar, and building and testing software in the sandbox. It can't make payments, sign documents, deploy to production or push to GitHub; it says so and logs the gap.
- The sandbox is isolated from your secrets but has internet access, so treat it as untrusted: don't put real keys or client data in it. It is a separate app, so it adds a second small Fly machine (it sleeps when idle).
- The limits reduce risk, they don't remove it. Review the approval panel before approving, and keep `TRUSTED_RECIPIENTS` short.
- Lessons and skills load when a session starts; after a restart or reconnect they are all there.
- One person, one Fly machine (the disk attaches to one machine). Chat history resets on restart; facts, tasks, notes and reminders persist.
- The access token is the only lock. Use a long random one, share it with nobody, and keep the site on HTTPS (Fly does this).
- Costs: a small Fly machine (a few dollars a month) plus Anthropic API usage per message.
