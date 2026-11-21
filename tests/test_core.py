import asyncio
from datetime import timedelta

import pytest

import assistant
import google_tools
import storage
import tools


@pytest.fixture(autouse=True)
def clean():
    if storage.DATA_FILE.exists():
        storage.DATA_FILE.unlink()


def test_memory_in_prompt():
    storage.remember("Diet", "vegetarian")
    assert "vegetarian" in assistant.system_prompt()
    storage.forget("diet")
    assert storage.all_facts() == {}


def test_tasks_sorted_and_validated():
    storage.add_task("Renew passport", "2026-12-01 10:00", "high")
    storage.add_task("Buy milk")
    ts = storage.list_tasks()
    assert [t["title"] for t in ts] == ["Renew passport", "Buy milk"]
    storage.complete_task(ts[0]["id"])
    assert len(storage.list_tasks()) == 1 and len(storage.list_tasks(True)) == 2
    with pytest.raises(ValueError):
        storage.add_task("x", priority="urgent")
    with pytest.raises(ValueError):
        storage.add_task("x", due="next friday")


def test_notes_search():
    storage.add_note("Router is in the hall cupboard", ["home"])
    assert len(storage.search_notes("router")) == 1
    assert len(storage.search_notes("home")) == 1
    assert storage.search_notes("zzz") == []


def test_reminders_due_once_and_requeue():
    fut = (storage.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    storage.add_reminder("Call bank", fut)
    with pytest.raises(ValueError):
        storage.add_reminder("old", "2020-01-01 09:00")
    assert storage.pop_due_reminders() == []
    d = storage._load()
    d["reminders"][0]["when"] = (storage.now() - timedelta(minutes=1)).isoformat()
    storage._save(d)
    due = storage.pop_due_reminders()
    assert [r["text"] for r in due] == ["Call bank"]
    assert storage.pop_due_reminders() == []
    storage.requeue_reminder(due[0]["id"])  # failed send: comes back later
    assert len(storage.list_reminders()) == 1


def test_requeue_gives_up_after_max_attempts():
    d = storage._load()
    d["reminders"].append({"id": "r1", "text": "x", "when": "2020-01-01T00:00:00+05:30",
                           "delivered": True, "attempts": 4})
    storage._save(d)
    storage.requeue_reminder("r1", max_attempts=5)
    assert storage.list_reminders() == []


def test_data_file_private():
    storage.add_note("secret")
    assert oct(storage.DATA_FILE.stat().st_mode)[-3:] == "600"


def test_tool_wrappers_return_errors_not_crashes():
    r = asyncio.run(tools.add_reminder.handler({"text": "x", "when": "garbage"}))
    assert r.get("is_error")
    r = asyncio.run(tools.add_task.handler({"title": "Pay rent", "due": "", "priority": ""}))
    assert "Added task" in r["content"][0]["text"]


def test_optional_tool_groups_only_when_configured(monkeypatch):
    import business_tools
    import sandbox_tools
    base = len(tools.ALL_TOOLS) + len(business_tools.TOOLS)
    assert not google_tools.configured() and not sandbox_tools.configured()
    assert len(tools.active_tools()) == base
    for k in google_tools.REQUIRED_ENV:
        monkeypatch.setenv(k, "x")
    assert len(tools.active_tools()) == base + len(google_tools.TOOLS)
    monkeypatch.setenv("SANDBOX_URL", "https://sandbox.example")
    monkeypatch.setenv("SANDBOX_TOKEN", "t" * 20)
    assert len(tools.active_tools()) == base + len(google_tools.TOOLS) + len(sandbox_tools.TOOLS)


def test_sandbox_options():
    o = assistant.build_options()
    assert "Bash" in o.disallowed_tools and "Write" in o.disallowed_tools


def test_gmail_helpers():
    import base64
    enc = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    html_only = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": enc("<p>Hello <b>there</b></p><script>x()</script>")}}]}
    assert "Hello" in google_tools._body_text(html_only) and "x()" not in google_tools._body_text(html_only)
    with pytest.raises(ValueError):
        google_tools._gmail_draft({"to": "a@b.com, c@d.com", "subject": "s", "body": "b"})
    with pytest.raises(ValueError):
        google_tools._calendar_create({"title": "t", "start": "2026-12-01 10:00", "end": "2026-12-01 09:00"})
