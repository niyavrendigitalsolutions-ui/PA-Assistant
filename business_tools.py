"""Tools for running the business: email (limited), leads, audit trail."""
from __future__ import annotations

import asyncio

from claude_agent_sdk import tool

import business
import storage
from tools import _error, _text


def _safe(fn, threaded: bool = False):
    async def wrapper(args):
        try:
            result = await asyncio.to_thread(fn, args) if threaded else fn(args)
            return _text(result)
        except Exception as exc:  # noqa: BLE001
            return _error(exc)
    return wrapper


@tool("send_email", "Send ONE email on behalf of the business. The system decides: it is sent only if the "
      "recipient is on the owner's trusted list, daily caps allow it, and it mentions no prices, "
      "payments, contracts or legal terms. Otherwise it is queued for the owner and NOT sent. "
      "Write it as a finished email; a disclosure line is added automatically.",
      {"to": str, "subject": str, "body": str})
async def send_email(args):
    return await _safe(lambda a: business.send_or_queue_email(a["to"], a["subject"], a["body"]), True)(args)


@tool("autonomy_status", "Show your current limits and how much of today's allowance is used.", {})
async def autonomy_status(args):
    return await _safe(lambda a: business.status())(args)


@tool("list_approvals", "List actions waiting for the owner's approval. You cannot approve them.",
      {"status": str})
async def list_approvals(args):
    return await _safe(lambda a: [
        {k: v for k, v in i.items() if k != "payload"}
        for i in storage.list_approvals(a.get("status") or "pending")])(args)


@tool("list_activity", "Audit trail of recent business actions (emails sent or queued).", {"limit": int})
async def list_activity(args):
    return await _safe(lambda a: storage.list_activity(min(int(a.get("limit") or 20), 100)))(args)


@tool("add_lead", "Add a sales lead. 'follow_up' is optional, YYYY-MM-DD HH:MM.",
      {"name": str, "contact": str, "source": str, "notes": str, "follow_up": str})
async def add_lead(args):
    return await _safe(lambda a: storage.add_lead(
        a["name"], a.get("contact", ""), a.get("source", ""), a.get("notes", ""),
        a.get("follow_up") or None))(args)


@tool("update_lead", "Update a lead: stage (new, contacted, proposal, negotiation, won, lost), "
      "append a note, and/or set the next follow-up (YYYY-MM-DD HH:MM).",
      {"lead_id": str, "stage": str, "note": str, "follow_up": str})
async def update_lead(args):
    return await _safe(lambda a: storage.update_lead(
        a["lead_id"], a.get("stage") or None, a.get("note") or None, a.get("follow_up") or None))(args)


@tool("list_leads", "List leads, optionally only one stage.", {"stage": str})
async def list_leads(args):
    return await _safe(lambda a: storage.list_leads(a.get("stage") or None))(args)


@tool("leads_due", "Leads whose follow-up date has arrived.", {})
async def leads_due(args):
    return await _safe(lambda a: storage.leads_due())(args)


TOOLS = [send_email, autonomy_status, list_approvals, list_activity,
         add_lead, update_lead, list_leads, leads_due]
