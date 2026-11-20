"""Custom tools the assistant can call. They wrap storage.py."""
from __future__ import annotations

import json

from claude_agent_sdk import create_sdk_mcp_server, tool

import storage

SERVER_NAME = "assistant"


def _text(value) -> dict:
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, ensure_ascii=False)
    return {"content": [{"type": "text", "text": value}]}


def _error(exc: Exception) -> dict:
    return {"content": [{"type": "text", "text": f"Error: {exc}"}], "is_error": True}


def _safe(fn):
    """Run a storage call, returning errors to the model instead of crashing."""
    async def wrapper(args):
        try:
            return _text(fn(args))
        except Exception as exc:  # noqa: BLE001
            return _error(exc)
    return wrapper


@tool("current_time", "Get the current date, time and weekday in the user's timezone.", {})
async def current_time(args):
    return _text(storage.now().strftime("%A, %d %B %Y, %H:%M %Z"))


@tool("remember", "Store a lasting fact about the user (preference, family, routine). "
      "Use a short key like 'favourite_cuisine'. Only store what the user shared.",
      {"key": str, "value": str})
async def remember(args):
    return await _safe(lambda a: storage.remember(a["key"], a["value"]))(args)


@tool("forget", "Delete a stored fact by key.", {"key": str})
async def forget(args):
    return await _safe(lambda a: storage.forget(a["key"]))(args)


@tool("add_task", "Add a to-do. 'due' is optional, format YYYY-MM-DD HH:MM in the user's "
      "timezone. 'priority' is low, normal or high.",
      {"title": str, "due": str, "priority": str})
async def add_task(args):
    return await _safe(lambda a: storage.add_task(
        a["title"], a.get("due") or None, a.get("priority") or "normal"))(args)


@tool("list_tasks", "List open tasks sorted by due date. Set include_done true to also show completed ones.",
      {"include_done": bool})
async def list_tasks(args):
    return await _safe(lambda a: storage.list_tasks(bool(a.get("include_done"))))(args)


@tool("complete_task", "Mark a task done by its id.", {"task_id": str})
async def complete_task(args):
    return await _safe(lambda a: storage.complete_task(a["task_id"]))(args)


@tool("delete_task", "Permanently delete a task by id. Confirm with the user first.", {"task_id": str})
async def delete_task(args):
    return await _safe(lambda a: storage.delete_task(a["task_id"]))(args)


@tool("add_note", "Save a note. 'tags' is an optional list of short tags.",
      {"text": str, "tags": list})
async def add_note(args):
    return await _safe(lambda a: storage.add_note(a["text"], a.get("tags")))(args)


@tool("search_notes", "Search saved notes by text or tag. Empty query returns the latest notes.",
      {"query": str})
async def search_notes(args):
    return await _safe(lambda a: storage.search_notes(a.get("query", "")))(args)


@tool("delete_note", "Permanently delete a note by id. Confirm with the user first.", {"note_id": str})
async def delete_note(args):
    return await _safe(lambda a: storage.delete_note(a["note_id"]))(args)


@tool("add_reminder", "Set a reminder. 'when' is YYYY-MM-DD HH:MM in the user's timezone. "
      "Call current_time first to resolve phrases like 'tomorrow 5pm'. Reminders are shown "
      "the next time the user opens or messages the assistant; they are not pushed to a phone.",
      {"text": str, "when": str})
async def add_reminder(args):
    return await _safe(lambda a: storage.add_reminder(a["text"], a["when"]))(args)


@tool("list_reminders", "List upcoming reminders.", {})
async def list_reminders(args):
    return await _safe(lambda a: storage.list_reminders())(args)


@tool("cancel_reminder", "Cancel a reminder by id.", {"reminder_id": str})
async def cancel_reminder(args):
    return await _safe(lambda a: storage.cancel_reminder(a["reminder_id"]))(args)


ALL_TOOLS = [current_time, remember, forget, add_task, list_tasks, complete_task,
             delete_task, add_note, search_notes, delete_note, add_reminder,
             list_reminders, cancel_reminder]

TOOL_NAMES = [f"mcp__{SERVER_NAME}__{t.name}" for t in ALL_TOOLS]  # built-in tools only


def active_tools() -> list:
    """Built-in tools, plus Gmail/Calendar when Google credentials are configured."""
    import google_tools
    return ALL_TOOLS + (google_tools.TOOLS if google_tools.configured() else [])


def tool_names() -> list[str]:
    return [f"mcp__{SERVER_NAME}__{t.name}" for t in active_tools()]


def build_server():
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=active_tools())
