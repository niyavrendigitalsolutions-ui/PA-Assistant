"""Private web chat front end for the personal assistant.

Open the site, enter your access token, and chat. Every API call needs the
token (ASSISTANT_ACCESS_TOKEN). The page checks for due reminders every 30s.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import assistant as core
import storage

log = logging.getLogger("assistant")
logging.basicConfig(level=logging.INFO)

ACCESS_TOKEN = os.environ.get("ASSISTANT_ACCESS_TOKEN", "")
if len(ACCESS_TOKEN) < 16:
    raise RuntimeError("Set ASSISTANT_ACCESS_TOKEN (16+ characters) before starting the server.")


def require_token(authorization: str = Header(default="")) -> None:
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), ACCESS_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid access token")


class Assistant:
    """One long-lived Claude session for the owner, with automatic reconnect."""

    def __init__(self) -> None:
        self._client: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()

    async def ask(self, text: str) -> str:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._client is None:
                        self._client = ClaudeSDKClient(options=core.build_options())
                        await self._client.connect()
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await assistant.close()


app = FastAPI(title="Personal Assistant", lifespan=lifespan, docs_url=None, redoc_url=None)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/chat", dependencies=[Depends(require_token)])
async def chat(body: ChatRequest):
    return {"reply": await assistant.ask(body.message)}


@app.get("/api/reminders/due", dependencies=[Depends(require_token)])
async def due_reminders():
    """Reminders that have come due. Each is returned once."""
    return {"reminders": [r["text"] for r in storage.pop_due_reminders()]}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'">
<title>Personal Assistant</title>
<style>
 :root{color-scheme:light dark}
 body{margin:0;font:16px system-ui,sans-serif;display:flex;flex-direction:column;height:100dvh;background:Canvas;color:CanvasText}
 header{padding:12px 16px;border-bottom:1px solid #8884;font-weight:600}
 #log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
 .m{max-width:min(85%,640px);padding:10px 14px;border-radius:14px;white-space:pre-wrap;overflow-wrap:anywhere}
 .me{align-self:flex-end;background:#2563eb;color:#fff}
 .bot{align-self:flex-start;background:#8883}
 .rem{align-self:center;background:#f59e0b33;border:1px solid #f59e0b}
 form{display:flex;gap:8px;padding:12px 16px;border-top:1px solid #8884}
 input{flex:1;font:inherit;padding:10px 12px;border-radius:10px;border:1px solid #8886;background:Canvas;color:CanvasText}
 button{font:inherit;padding:10px 16px;border-radius:10px;border:0;background:#2563eb;color:#fff;cursor:pointer}
 button:disabled{opacity:.5}
</style></head><body>
<header>Personal Assistant</header>
<div id="log" aria-live="polite"></div>
<form id="f"><input id="i" autocomplete="off" placeholder="Message" aria-label="Message"><button id="b">Send</button></form>
<script>
const log=document.getElementById('log'),f=document.getElementById('f'),i=document.getElementById('i'),b=document.getElementById('b');
let token=sessionStorage.getItem('t')||'';
function add(cls,text){const d=document.createElement('div');d.className='m '+cls;d.textContent=text;log.appendChild(d);log.scrollTop=log.scrollHeight}
async function api(path,opt){const r=await fetch(path,Object.assign({headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'}},opt));
 if(r.status===401){token='';sessionStorage.removeItem('t');throw new Error('Wrong access token')}
 if(!r.ok)throw new Error('Request failed ('+r.status+')');return r.json()}
function ensureToken(){if(!token){token=(prompt('Access token')||'').trim();if(token)sessionStorage.setItem('t',token)}return !!token}
f.addEventListener('submit',async e=>{e.preventDefault();const text=i.value.trim();if(!text||!ensureToken())return;
 i.value='';add('me',text);b.disabled=true;
 try{add('bot',(await api('/api/chat',{method:'POST',body:JSON.stringify({message:text})})).reply)}
 catch(err){add('bot','Error: '+err.message)}finally{b.disabled=false;i.focus()}});
async function poll(){if(!token)return;try{(await api('/api/reminders/due')).reminders.forEach(t=>add('rem','Reminder: '+t))}catch(e){}}
setInterval(poll,30000);setTimeout(poll,1500);
add('bot','Hi! How can I help?');
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return PAGE
