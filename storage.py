"""Local JSON storage for memory, tasks, notes and reminders."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("ASSISTANT_TZ", "Asia/Kolkata"))
DATA_DIR = Path(os.environ.get("ASSISTANT_DATA_DIR", "~/.personal_assistant")).expanduser()
DATA_FILE = DATA_DIR / "data.json"
_lock = threading.Lock()

EMPTY = {"facts": {}, "tasks": [], "notes": [], "reminders": []}


def now() -> datetime:
    return datetime.now(TZ)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _load() -> dict:
    if not DATA_FILE.exists():
        return json.loads(json.dumps(EMPTY))
    data = json.loads(DATA_FILE.read_text())
    for key, default in EMPTY.items():
        data.setdefault(key, json.loads(json.dumps(default)))
    return data


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.chmod(tmp, 0o600)  # personal data: owner-only
    tmp.replace(DATA_FILE)


def parse_when(text: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM' (or with a T) as local time."""
    text = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=9, minute=0)
            return dt.replace(tzinfo=TZ)
        except ValueError:
            continue
    raise ValueError("Use the format YYYY-MM-DD HH:MM, for example 2026-11-25 15:30")


# ---- facts (long-term memory) ----
def remember(key: str, value: str) -> str:
    with _lock:
        data = _load()
        data["facts"][key.strip().lower()] = value.strip()
        _save(data)
    return f"Remembered: {key} = {value}"


def forget(key: str) -> str:
    with _lock:
        data = _load()
        existed = data["facts"].pop(key.strip().lower(), None)
        _save(data)
    return f"Forgot {key}." if existed is not None else f"Nothing stored under '{key}'."


def all_facts() -> dict:
    with _lock:
        return dict(_load()["facts"])


# ---- tasks ----
def add_task(title: str, due: str | None = None, priority: str = "normal") -> str:
    if priority not in ("low", "normal", "high"):
        raise ValueError("priority must be low, normal or high")
    due_iso = parse_when(due).isoformat() if due else None
    with _lock:
        data = _load()
        task = {"id": _new_id(), "title": title.strip(), "due": due_iso,
                "priority": priority, "done": False, "created": now().isoformat()}
        data["tasks"].append(task)
        _save(data)
    return f"Added task {task['id']}: {task['title']}" + (f" (due {due})" if due else "")


def list_tasks(include_done: bool = False) -> list[dict]:
    with _lock:
        tasks = _load()["tasks"]
    if not include_done:
        tasks = [t for t in tasks if not t["done"]]
    order = {"high": 0, "normal": 1, "low": 2}
    return sorted(tasks, key=lambda t: (t["due"] or "9999", order[t["priority"]]))


def complete_task(task_id: str) -> str:
    with _lock:
        data = _load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["done"] = True
                t["completed"] = now().isoformat()
                _save(data)
                return f"Completed: {t['title']}"
    return f"No task with id {task_id}."


def delete_task(task_id: str) -> str:
    with _lock:
        data = _load()
        before = len(data["tasks"])
        data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
        _save(data)
    return "Deleted." if len(data["tasks"]) < before else f"No task with id {task_id}."


# ---- notes ----
def add_note(text: str, tags: list[str] | None = None) -> str:
    with _lock:
        data = _load()
        note = {"id": _new_id(), "text": text.strip(),
                "tags": [t.lower() for t in (tags or [])], "created": now().isoformat()}
        data["notes"].append(note)
        _save(data)
    return f"Saved note {note['id']}."


def search_notes(query: str = "", limit: int = 10) -> list[dict]:
    q = query.strip().lower()
    with _lock:
        notes = _load()["notes"]
    hits = [n for n in notes if not q or q in n["text"].lower() or q in n["tags"]]
    return list(reversed(hits))[:limit]


def delete_note(note_id: str) -> str:
    with _lock:
        data = _load()
        before = len(data["notes"])
        data["notes"] = [n for n in data["notes"] if n["id"] != note_id]
        _save(data)
    return "Deleted." if len(data["notes"]) < before else f"No note with id {note_id}."


# ---- reminders ----
def add_reminder(text: str, when: str) -> str:
    dt = parse_when(when)
    if dt < now():
        raise ValueError("That time is in the past.")
    with _lock:
        data = _load()
        r = {"id": _new_id(), "text": text.strip(), "when": dt.isoformat(), "delivered": False}
        data["reminders"].append(r)
        _save(data)
    return f"Reminder {r['id']} set for {dt.strftime('%a %d %b %Y, %H:%M')}: {r['text']}"


def list_reminders() -> list[dict]:
    with _lock:
        rs = [r for r in _load()["reminders"] if not r["delivered"]]
    return sorted(rs, key=lambda r: r["when"])


def cancel_reminder(reminder_id: str) -> str:
    with _lock:
        data = _load()
        before = len(data["reminders"])
        data["reminders"] = [r for r in data["reminders"] if r["id"] != reminder_id]
        _save(data)
    return "Cancelled." if len(data["reminders"]) < before else f"No reminder with id {reminder_id}."


def requeue_reminder(reminder_id: str, max_attempts: int = 5) -> None:
    """A reminder failed to send: retry in 10 minutes, give up after max_attempts."""
    from datetime import timedelta
    with _lock:
        data = _load()
        for r in data["reminders"]:
            if r["id"] == reminder_id:
                r["attempts"] = r.get("attempts", 0) + 1
                if r["attempts"] < max_attempts:
                    r["delivered"] = False
                    r["when"] = (now() + timedelta(minutes=10)).isoformat()
                _save(data)
                return


def pop_due_reminders() -> list[dict]:
    """Return reminders that are due and mark them delivered."""
    current = now().isoformat()
    due = []
    with _lock:
        data = _load()
        for r in data["reminders"]:
            if not r["delivered"] and r["when"] <= current:
                r["delivered"] = True
                due.append(dict(r))
        if due:
            _save(data)
    return due
