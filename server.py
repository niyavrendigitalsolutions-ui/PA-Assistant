"""WhatsApp front end for the personal assistant (Meta WhatsApp Cloud API).

Only messages from OWNER_WHATSAPP are answered. Every webhook call is verified
with the app secret. A background loop sends reminders when they fall due.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager

import httpx
from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response

import assistant as core
import storage

log = logging.getLogger("assistant")
logging.basicConfig(level=logging.INFO)

GRAPH = "https://graph.facebook.com/v21.0"
TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")
OWNER = "".join(ch for ch in os.environ.get("OWNER_WHATSAPP", "") if ch.isdigit())

_missing = [n for n, v in {"WHATSAPP_TOKEN": TOKEN, "WHATSAPP_PHONE_NUMBER_ID": PHONE_ID,
                           "WHATSAPP_VERIFY_TOKEN": VERIFY_TOKEN, "WHATSAPP_APP_SECRET": APP_SECRET,
                           "OWNER_WHATSAPP": OWNER}.items() if not v]
if _missing:
    raise RuntimeError("Missing settings: " + ", ".join(_missing))


def verify_signature(body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


async def send_whatsapp(to: str, text: str) -> None:
    """Send text, split to stay under WhatsApp's 4096-character limit."""
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] or ["(empty reply)"]
    async with httpx.AsyncClient(timeout=20) as http:
        for chunk in chunks:
            r = await http.post(
                f"{GRAPH}/{PHONE_ID}/messages",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"messaging_product": "whatsapp", "to": to, "type": "text",
                      "text": {"body": chunk}})
            r.raise_for_status()


class Assistant:
    """One long-lived Claude session for the owner, with automatic reconnect."""

    def __init__(self) -> None:
        self._client: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> ClaudeSDKClient:
        client = ClaudeSDKClient(options=core.build_options())
        await client.connect()
        return client

    async def ask(self, text: str) -> str:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._client is None:
                        self._client = await self._connect()
                    await self._client.query(core.with_context(text, include_reminders=False))
                    parts: list[str] = []
                    async for msg in self._client.receive_response():
                        if isinstance(msg, AssistantMessage):
                            parts += [b.text for b in msg.content
                                      if isinstance(b, TextBlock) and b.text.strip()]
                    return "\n\n".join(parts) or "Done."
                except Exception:  # noqa: BLE001
                    log.exception("assistant error (attempt %s)", attempt)
                    await self.close()
            return "Sorry, I hit a problem and couldn't answer. Please try again in a moment."

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


assistant = Assistant()
_seen: collections.deque[str] = collections.deque(maxlen=500)


async def reminder_loop() -> None:
    while True:
        try:
            for r in storage.pop_due_reminders():
                try:
                    await send_whatsapp(OWNER, f"Reminder: {r['text']}")
                except Exception:  # noqa: BLE001
                    log.exception("reminder %s failed to send", r["id"])
                    storage.requeue_reminder(r["id"])
        except Exception:  # noqa: BLE001
            log.exception("reminder loop error")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(reminder_loop())
    yield
    task.cancel()
    await assistant.close()


app = FastAPI(title="Personal Assistant", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/webhook")
async def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and hmac.compare_digest(
            q.get("hub.verify_token", ""), VERIFY_TOKEN):
        return Response(content=q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403)


async def handle_message(sender: str, msg: dict) -> None:
    if msg.get("type") != "text":
        await send_whatsapp(sender, "I can only read text messages for now.")
        return
    try:
        reply = await assistant.ask(msg["text"]["body"])
        await send_whatsapp(sender, reply)
    except Exception:  # noqa: BLE001
        log.exception("failed to handle message")


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not verify_signature(body, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=403, detail="Bad signature")
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []) or []:
                mid, sender = msg.get("id", ""), "".join(c for c in msg.get("from", "") if c.isdigit())
                if mid in _seen:
                    continue
                _seen.append(mid)
                if sender != OWNER:
                    log.warning("ignored message from non-owner number")
                    continue
                background.add_task(handle_message, sender, msg)
    return {"ok": True}
