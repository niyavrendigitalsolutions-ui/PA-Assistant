"""Isolated code-execution service. Deploy it as its OWN Fly app with NO secrets
except SANDBOX_TOKEN. The assistant writes and runs code here, never on its own machine.

Isolation choices:
- Commands run as the unprivileged user 'nobody' (when started as root), so they cannot
  read this process's environment (/proc/<pid>/environ) or SANDBOX_TOKEN.
- Commands get a minimal environment: no tokens, no API keys.
- Each project is a separate folder; file paths cannot escape it (symlinks included).
- Time, CPU, process-count and file-size limits apply to every command.
"""
from __future__ import annotations

import hmac
import io
import os
import pwd
import re
import resource
import signal
import subprocess
import threading
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

TOKEN = os.environ.get("SANDBOX_TOKEN", "")
if len(TOKEN) < 16:
    raise RuntimeError("Set SANDBOX_TOKEN (16+ characters).")

ROOT = Path(os.environ.get("WORKSPACE_DIR", "/workspace")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
RUN_USER = "nobody" if os.geteuid() == 0 else None
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_FILE, MAX_OUT, MAX_ZIP = 1_000_000, 20_000, 25_000_000
SKIP = {"node_modules", ".venv", "__pycache__", ".git"}
_slots = threading.BoundedSemaphore(3)

app = FastAPI(title="Sandbox", docs_url=None, redoc_url=None)


def require_token(authorization: str = Header(default="")) -> None:
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid token")


def _own(path: Path) -> None:
    if RUN_USER:
        pw = pwd.getpwnam(RUN_USER)
        os.chown(path, pw.pw_uid, pw.pw_gid)


def project_dir(project: str, create: bool = True) -> Path:
    if not PROJECT_RE.match(project):
        raise HTTPException(400, "Project must be lowercase letters, digits and dashes (max 40).")
    d = ROOT / project
    if not d.exists():
        if not create:
            raise HTTPException(404, "Unknown project")
        d.mkdir()
        _own(d)
    return d


def safe_path(project_root: Path, rel: str) -> Path:
    p = (project_root / rel).resolve()
    if p != project_root and project_root not in p.parents:
        raise HTTPException(400, "Path is outside the project.")
    return p


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))
    resource.setrlimit(resource.RLIMIT_FSIZE, (200_000_000, 200_000_000))


def _clip(data: bytes) -> str:
    text = data.decode("utf-8", "replace")
    return text if len(text) <= MAX_OUT else "[...earlier output cut...]\n" + text[-MAX_OUT:]


class ExecRequest(BaseModel):
    project: str
    command: str = Field(min_length=1, max_length=4000)
    timeout: int = Field(default=120, ge=1, le=600)


@app.post("/exec", dependencies=[Depends(require_token)])
def run(req: ExecRequest):
    pdir = project_dir(req.project)
    if not _slots.acquire(timeout=5):
        raise HTTPException(429, "Sandbox is busy; try again shortly.")
    try:
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(pdir), "LANG": "C.UTF-8"}
        proc = subprocess.Popen(
            ["bash", "-c", req.command], cwd=pdir, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, user=RUN_USER,
            preexec_fn=_limits, start_new_session=True)
        timed_out = False
        try:
            out, err = proc.communicate(timeout=req.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        return {"exit_code": proc.returncode, "timed_out": timed_out,
                "stdout": _clip(out), "stderr": _clip(err)}
    finally:
        _slots.release()


class WriteRequest(BaseModel):
    project: str
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=MAX_FILE)


@app.post("/write", dependencies=[Depends(require_token)])
def write(req: WriteRequest):
    pdir = project_dir(req.project)
    target = safe_path(pdir, req.path)
    if target == pdir or target.is_dir():
        raise HTTPException(400, "Path must be a file.")
    target.parent.mkdir(parents=True, exist_ok=True)
    for parent in [target.parent, *target.parent.parents]:
        if parent == pdir.parent:
            break
        _own(parent)
    target.write_text(req.content)
    _own(target)
    return {"ok": True, "bytes": len(req.content.encode())}


@app.get("/read", dependencies=[Depends(require_token)])
def read(project: str, path: str):
    target = safe_path(project_dir(project, create=False), path)
    if not target.is_file():
        raise HTTPException(404, "No such file")
    if target.stat().st_size > MAX_FILE:
        raise HTTPException(413, "File too large to read")
    return {"content": target.read_text(errors="replace")}


def _walk(pdir: Path):
    for dirpath, dirnames, filenames in os.walk(pdir):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for name in filenames:
            yield Path(dirpath) / name


@app.get("/list", dependencies=[Depends(require_token)])
def list_files(project: str, limit: int = Query(default=300, le=1000)):
    pdir = project_dir(project, create=False)
    files = []
    for f in _walk(pdir):
        if f.is_symlink() or not f.is_file():
            continue
        files.append({"path": str(f.relative_to(pdir)), "bytes": f.stat().st_size})
        if len(files) >= limit:
            break
    return {"files": sorted(files, key=lambda x: x["path"])}


@app.get("/projects", dependencies=[Depends(require_token)])
def projects():
    return {"projects": sorted(p.name for p in ROOT.iterdir() if p.is_dir())}


@app.get("/export/{project}", dependencies=[Depends(require_token)])
def export(project: str):
    pdir = project_dir(project, create=False)
    buf, total = io.BytesIO(), 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _walk(pdir):
            if f.is_symlink() or not f.is_file():
                continue
            total += f.stat().st_size
            if total > MAX_ZIP * 3:
                raise HTTPException(413, "Project too large to export")
            z.write(f, f.relative_to(pdir))
    if buf.tell() > MAX_ZIP:
        raise HTTPException(413, "Export larger than 25 MB")
    return Response(buf.getvalue(), media_type="application/zip")


@app.get("/health")
def health():
    return {"ok": True}
