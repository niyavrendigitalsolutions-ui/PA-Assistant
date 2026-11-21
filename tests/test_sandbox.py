import importlib.util
import os
import sys
import tempfile
import time
import zipfile
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TOKEN = "sandbox-token-1234567890"
ROOT = tempfile.mkdtemp()
os.chmod(ROOT, 0o755)
os.environ["SANDBOX_TOKEN"], os.environ["WORKSPACE_DIR"] = TOKEN, ROOT

spec = importlib.util.spec_from_file_location(
    "runner", Path(__file__).resolve().parent.parent / "sandbox" / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
client = TestClient(runner.app)
H = {"Authorization": f"Bearer {TOKEN}"}
IS_ROOT = os.geteuid() == 0


def sh(cmd, project="demo", timeout=20):
    r = client.post("/exec", headers=H, json={"project": project, "command": cmd, "timeout": timeout})
    assert r.status_code == 200, r.text
    return r.json()


def test_requires_token():
    assert client.post("/exec", json={"project": "demo", "command": "id"}).status_code == 401
    assert client.get("/projects", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_write_read_list_run():
    assert client.post("/write", headers=H, json={"project": "demo", "path": "src/app.py",
                                                 "content": "print(6*7)"}).status_code == 200
    assert client.get("/read", headers=H, params={"project": "demo", "path": "src/app.py"}).json()["content"] == "print(6*7)"
    assert {"path": "src/app.py", "bytes": 10} in client.get("/list", headers=H, params={"project": "demo"}).json()["files"]
    r = sh("python3 src/app.py")
    assert r["exit_code"] == 0 and r["stdout"].strip() == "42"


@pytest.mark.parametrize("path", ["../x.txt", "../../etc/passwd", "/etc/passwd", "a/../../b"])
def test_paths_cannot_escape_project(path):
    assert client.post("/write", headers=H, json={"project": "demo", "path": path, "content": "x"}).status_code == 400
    assert client.get("/read", headers=H, params={"project": "demo", "path": path}).status_code in (400, 404)


@pytest.mark.parametrize("project", ["../x", "A", "a b", "", "x" * 41, ".hidden", "a/b"])
def test_bad_project_names(project):
    r = client.post("/write", headers=H, json={"project": project, "path": "f", "content": "x"})
    assert r.status_code in (400, 404, 422)


def test_symlink_cannot_read_outside_files():
    sh("ln -sf /etc/passwd leak.txt")
    assert client.get("/read", headers=H, params={"project": "demo", "path": "leak.txt"}).status_code == 400
    names = [f["path"] for f in client.get("/list", headers=H, params={"project": "demo"}).json()["files"]]
    assert "leak.txt" not in names
    z = zipfile.ZipFile(io.BytesIO(client.get("/export/demo", headers=H).content))
    assert "leak.txt" not in z.namelist()


def test_commands_get_no_secrets():
    env = sh("env")["stdout"]
    assert TOKEN not in env and "SANDBOX_TOKEN" not in env and "ANTHROPIC" not in env


@pytest.mark.skipif(not IS_ROOT, reason="user separation only applies when the runner starts as root")
def test_commands_run_unprivileged_and_cannot_read_runner_environment():
    assert sh("id -un")["stdout"].strip() == "nobody"
    r = sh(f"cat /proc/{os.getpid()}/environ")
    assert r["exit_code"] != 0 and TOKEN not in r["stdout"]


def test_timeout_kills_process_group():
    t = time.time()
    r = sh("sleep 30 & sleep 30", timeout=1)
    assert r["timed_out"] and time.time() - t < 10


def test_output_is_clipped():
    r = sh("python3 -c \"print('x'*100000)\"")
    assert len(r["stdout"]) < 21_000 and "cut" in r["stdout"]


def test_export_skips_heavy_folders():
    sh("mkdir -p node_modules/pkg && echo big > node_modules/pkg/i.js && echo hi > keep.txt")
    z = zipfile.ZipFile(io.BytesIO(client.get("/export/demo", headers=H).content))
    assert "keep.txt" in z.namelist() and not any("node_modules" in n for n in z.namelist())
    assert client.get("/export/unknown", headers=H).status_code == 404


def test_oversized_file_rejected():
    r = client.post("/write", headers=H, json={"project": "demo", "path": "big", "content": "x" * 1_000_001})
    assert r.status_code == 422
