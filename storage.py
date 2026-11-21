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

EMPTY = {"facts": {}, "tasks": [], "notes": [], "reminders": [],
         "lessons": [], "skills": {}, "improvements": [],
         "leads": [], "approvals": [], "activity": []}

MAX_LESSONS, MAX_SKILLS, MAX_IMPROVEMENTS = 200, 100, 100
LESSON_KINDS = ("preference", "correction", "how_to", "general")
IMPROVEMENT_KINDS = ("capability_gap", "prompt_change", "bug", "other")
LEAD_STAGES = ("new", "contacted", "proposal", "negotiation", "won", "lost")
MAX_ACTIVITY, MAX_LEADS = 500, 1000
APPROVAL_TTL_DAYS = 7


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


# ---- self-learning: lessons ----
def record_lesson(text: str, kind: str = "general") -> str:
    """Save one short lesson learned from the user (preference, correction, how-to)."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("Lesson text is empty.")
    if len(text) > 500:
        raise ValueError("Keep a lesson to one short sentence or two (500 characters max).")
    if kind not in LESSON_KINDS:
        raise ValueError("kind must be one of: " + ", ".join(LESSON_KINDS))
    with _lock:
        data = _load()
        if any(l["text"].lower() == text.lower() for l in data["lessons"]):
            return "Already known."
        data["lessons"].append({"id": _new_id(), "text": text, "kind": kind,
                                "created": now().isoformat()})
        del data["lessons"][:-MAX_LESSONS]  # keep the newest
        _save(data)
    return f"Learned: {text}"


def list_lessons(limit: int = 30) -> list[dict]:
    with _lock:
        lessons = _load()["lessons"]
    return list(reversed(lessons))[:limit]


def delete_lesson(lesson_id: str) -> str:
    with _lock:
        data = _load()
        before = len(data["lessons"])
        data["lessons"] = [l for l in data["lessons"] if l["id"] != lesson_id]
        _save(data)
    return "Forgotten." if len(data["lessons"]) < before else f"No lesson with id {lesson_id}."


# ---- self-learning: skills (reusable procedures) ----
def _slug(name: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    if not slug:
        raise ValueError("Skill name needs letters or numbers.")
    return slug


def save_skill(name: str, description: str, steps: str) -> str:
    """Create or improve a reusable procedure."""
    slug, description, steps = _slug(name), " ".join(description.split()), steps.strip()
    if not description or len(description) > 200:
        raise ValueError("Description is required, 200 characters max.")
    if not steps or len(steps) > 4000:
        raise ValueError("Steps are required, 4000 characters max.")
    with _lock:
        data = _load()
        existing = data["skills"].get(slug)
        if existing is None and len(data["skills"]) >= MAX_SKILLS:
            raise ValueError("Skill limit reached; delete an old skill first.")
        data["skills"][slug] = {
            "description": description, "steps": steps,
            "version": (existing["version"] + 1) if existing else 1,
            "uses": existing["uses"] if existing else 0,
            "created": existing["created"] if existing else now().isoformat(),
            "updated": now().isoformat()}
        _save(data)
    return f"Skill '{slug}' {'updated' if existing else 'saved'}."


def list_skills() -> list[dict]:
    with _lock:
        skills = _load()["skills"]
    return [{"name": n, "description": s["description"], "uses": s["uses"]}
            for n, s in sorted(skills.items())]


def get_skill(name: str) -> dict:
    slug = _slug(name)
    with _lock:
        data = _load()
        skill = data["skills"].get(slug)
        if skill is None:
            raise ValueError(f"No skill named '{slug}'.")
        skill["uses"] += 1
        _save(data)
    return {"name": slug, **skill}


def delete_skill(name: str) -> str:
    slug = _slug(name)
    with _lock:
        data = _load()
        removed = data["skills"].pop(slug, None)
        _save(data)
    return "Deleted." if removed else f"No skill named '{slug}'."


# ---- self-improvement proposals (for the user to review; never auto-applied) ----
def add_improvement(title: str, detail: str, kind: str = "capability_gap") -> str:
    title, detail = " ".join(title.split()), detail.strip()
    if not title or len(title) > 120 or len(detail) > 1500:
        raise ValueError("Title is required (120 chars max); detail 1500 chars max.")
    if kind not in IMPROVEMENT_KINDS:
        raise ValueError("kind must be one of: " + ", ".join(IMPROVEMENT_KINDS))
    with _lock:
        data = _load()
        pending = [i for i in data["improvements"] if i["status"] == "pending"]
        if any(i["title"].lower() == title.lower() for i in pending):
            return "Already proposed."
        if len(pending) >= MAX_IMPROVEMENTS:
            raise ValueError("Too many pending proposals; ask the user to review them.")
        data["improvements"].append({"id": _new_id(), "title": title, "detail": detail,
                                     "kind": kind, "status": "pending",
                                     "created": now().isoformat()})
        _save(data)
    return f"Logged for the user to review: {title}"


def list_improvements(status: str = "pending") -> list[dict]:
    with _lock:
        items = _load()["improvements"]
    return [i for i in items if status == "all" or i["status"] == status]


def resolve_improvement(improvement_id: str, status: str = "done") -> str:
    if status not in ("done", "dismissed"):
        raise ValueError("status must be done or dismissed")
    with _lock:
        data = _load()
        for i in data["improvements"]:
            if i["id"] == improvement_id:
                i["status"] = status
                _save(data)
                return f"Marked {status}."
    return f"No proposal with id {improvement_id}."


# ---- business: activity log (audit trail) ----
def log_activity(kind: str, summary: str, status: str, detail: str = "") -> None:
    with _lock:
        data = _load()
        data["activity"].append({"id": _new_id(), "kind": kind, "summary": summary[:300],
                                 "status": status, "detail": detail[:500],
                                 "created": now().isoformat()})
        del data["activity"][:-MAX_ACTIVITY]
        _save(data)


def list_activity(limit: int = 50) -> list[dict]:
    with _lock:
        items = _load()["activity"]
    return list(reversed(items))[:limit]


def count_sent_today(to: str | None = None) -> int:
    today = now().date().isoformat()
    with _lock:
        items = _load()["activity"]
    return sum(1 for a in items
               if a["kind"] == "email" and a["status"] == "sent" and a["created"][:10] == today
               and (to is None or a.get("detail", "").lower() == to.lower()))


# ---- business: approval queue (only the human can resolve; the model has no tool for it) ----
def add_approval(kind: str, summary: str, reason: str, payload: dict) -> str:
    with _lock:
        data = _load()
        item = {"id": _new_id(), "kind": kind, "summary": summary[:300], "reason": reason,
                "payload": payload, "status": "pending", "created": now().isoformat()}
        data["approvals"].append(item)
        _save(data)
    return item["id"]


def _expire(data: dict) -> bool:
    from datetime import timedelta
    cutoff = (now() - timedelta(days=APPROVAL_TTL_DAYS)).isoformat()
    changed = False
    for a in data["approvals"]:
        if a["status"] == "pending" and a["created"] < cutoff:
            a["status"], changed = "expired", True
    return changed


def list_approvals(status: str = "pending") -> list[dict]:
    with _lock:
        data = _load()
        if _expire(data):
            _save(data)
        items = data["approvals"]
    return [a for a in items if status == "all" or a["status"] == status]


def claim_approval(approval_id: str) -> dict | None:
    """Atomically move pending -> executing so a double click can never act twice."""
    with _lock:
        data = _load()
        _expire(data)
        for a in data["approvals"]:
            if a["id"] == approval_id and a["status"] == "pending":
                a["status"] = "executing"
                _save(data)
                return dict(a)
        _save(data)
    return None


def finish_approval(approval_id: str, status: str, result: str = "") -> None:
    with _lock:
        data = _load()
        for a in data["approvals"]:
            if a["id"] == approval_id:
                a["status"], a["result"] = status, result[:500]
                a["resolved"] = now().isoformat()
        _save(data)


def reject_approval(approval_id: str) -> bool:
    with _lock:
        data = _load()
        for a in data["approvals"]:
            if a["id"] == approval_id and a["status"] == "pending":
                a["status"], a["resolved"] = "rejected", now().isoformat()
                _save(data)
                return True
    return False


# ---- business: leads (local mini-CRM) ----
def add_lead(name: str, contact: str = "", source: str = "", notes: str = "",
             follow_up: str | None = None) -> str:
    name = " ".join(name.split())
    if not name or len(name) > 120:
        raise ValueError("Lead name is required (120 chars max).")
    fu = parse_when(follow_up).isoformat() if follow_up else None
    with _lock:
        data = _load()
        if len(data["leads"]) >= MAX_LEADS:
            raise ValueError("Lead limit reached.")
        lead = {"id": _new_id(), "name": name, "contact": contact.strip()[:200],
                "source": source.strip()[:100], "stage": "new", "follow_up": fu,
                "notes": [notes.strip()[:1000]] if notes.strip() else [],
                "created": now().isoformat(), "updated": now().isoformat()}
        data["leads"].append(lead)
        _save(data)
    return f"Lead {lead['id']} added: {name}"


def update_lead(lead_id: str, stage: str | None = None, note: str | None = None,
                follow_up: str | None = None) -> str:
    if stage and stage not in LEAD_STAGES:
        raise ValueError("stage must be one of: " + ", ".join(LEAD_STAGES))
    fu = parse_when(follow_up).isoformat() if follow_up else None
    with _lock:
        data = _load()
        for l in data["leads"]:
            if l["id"] == lead_id:
                if stage:
                    l["stage"] = stage
                if note and note.strip():
                    l["notes"].append(note.strip()[:1000])
                    del l["notes"][:-30]
                if fu:
                    l["follow_up"] = fu
                l["updated"] = now().isoformat()
                _save(data)
                return f"Updated {l['name']} (stage: {l['stage']})."
    return f"No lead with id {lead_id}."


def list_leads(stage: str | None = None) -> list[dict]:
    with _lock:
        leads = _load()["leads"]
    return [l for l in leads if stage is None or l["stage"] == stage]


def leads_due() -> list[dict]:
    current = now().isoformat()
    return [l for l in list_leads()
            if l["follow_up"] and l["follow_up"] <= current and l["stage"] not in ("won", "lost")]
