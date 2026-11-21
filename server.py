"""Private web chat front end for the personal assistant.

Open the site, enter your access token, and chat. Every API call needs the
token (ASSISTANT_ACCESS_TOKEN). The page checks for due reminders every 30s.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

import assistant as core
import business
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


_ID = re.compile(r"^[a-f0-9]{8}$")


@app.get("/api/approvals", dependencies=[Depends(require_token)])
async def approvals():
    return {"approvals": storage.list_approvals("pending")}


@app.post("/api/approvals/{approval_id}/approve", dependencies=[Depends(require_token)])
async def approve(approval_id: str):
    """Only the authenticated owner can do this; the assistant has no tool for it."""
    if not _ID.match(approval_id):
        raise HTTPException(404, "Unknown approval")
    item = storage.claim_approval(approval_id)  # pending -> executing, exactly once
    if item is None:
        raise HTTPException(409, "Not pending (already handled, rejected or expired)")
    try:
        result = await asyncio.to_thread(business.execute_approved, item)
    except Exception as exc:  # noqa: BLE001
        storage.finish_approval(approval_id, "failed", str(exc))
        log.exception("approved action failed")
        raise HTTPException(502, f"Action failed: {exc}")
    storage.finish_approval(approval_id, "approved", result)
    return {"result": result}


@app.post("/api/approvals/{approval_id}/reject", dependencies=[Depends(require_token)])
async def reject(approval_id: str):
    if not _ID.match(approval_id) or not storage.reject_approval(approval_id):
        raise HTTPException(409, "Not pending")
    return {"ok": True}


@app.get("/api/activity", dependencies=[Depends(require_token)])
async def activity():
    return {"limits": business.status(), "activity": storage.list_activity(30)}


_EXPORT = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}-\d{8}-\d{6}\.zip$")


@app.get("/api/exports", dependencies=[Depends(require_token)])
async def exports():
    d = storage.DATA_DIR / "exports"
    names = sorted((p.name for p in d.glob("*.zip")), reverse=True) if d.exists() else []
    return {"exports": names[:20]}


@app.get("/api/exports/{name}", dependencies=[Depends(require_token)])
async def download_export(name: str):
    path = storage.DATA_DIR / "exports" / name
    if not _EXPORT.match(name) or not path.is_file():
        raise HTTPException(404, "No such export")
    return FileResponse(path, media_type="application/zip", filename=name)


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
 #side{padding:0 16px;display:flex;flex-direction:column;gap:8px}
 .card{border:1px solid #f59e0b;border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:6px}
 .card small{opacity:.75;white-space:pre-wrap;overflow-wrap:anywhere}
 .row{display:flex;gap:8px;flex-wrap:wrap}
 .ok{background:#16a34a}.no{background:#6b7280}.dl{background:#0f766e;padding:6px 10px;font-size:14px}
</style></head><body>
<header>Personal Assistant</header>
<div id="side"></div>
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
const side=document.getElementById('side');
function btn(label,cls,fn){const b=document.createElement('button');b.textContent=label;b.className=cls;b.onclick=async()=>{b.disabled=true;try{await fn()}catch(e){alert(e.message)}await poll()};return b}
async function renderSide(){
 const [a,x]=await Promise.all([api('/api/approvals'),api('/api/exports')]);
 side.replaceChildren();
 a.approvals.forEach(it=>{const c=document.createElement('div');c.className='card';
  const t=document.createElement('strong');t.textContent='Needs your approval: '+it.summary;
  const w=document.createElement('small');w.textContent='Held because '+it.reason+'.\\n\\n'+(it.payload.body||'');
  const r=document.createElement('div');r.className='row';
  r.append(btn('Approve and send','ok',()=>api('/api/approvals/'+it.id+'/approve',{method:'POST'}).then(j=>add('bot',j.result))),
           btn('Reject','no',()=>api('/api/approvals/'+it.id+'/reject',{method:'POST'})));
  c.append(t,w,r);side.append(c)});
 if(x.exports.length){const c=document.createElement('div');c.className='row';
  x.exports.slice(0,3).forEach(n=>c.append(btn('Download '+n,'dl',async()=>{
   const r=await fetch('/api/exports/'+n,{headers:{'Authorization':'Bearer '+token}});if(!r.ok)throw new Error('Download failed');
   const u=URL.createObjectURL(await r.blob());const l=document.createElement('a');l.href=u;l.download=n;l.click();URL.revokeObjectURL(u)})));side.append(c)}}
async function poll(){if(!token)return;try{(await api('/api/reminders/due')).reminders.forEach(t=>add('rem','Reminder: '+t));await renderSide()}catch(e){}}
setInterval(poll,30000);setTimeout(poll,1500);
add('bot','Hi! How can I help?');
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return PAGE
