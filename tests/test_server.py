from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import server
import storage

client = TestClient(server.app)  # no `with`: skips lifespan
AUTH = {"Authorization": "Bearer test-access-token-1234"}


@pytest.fixture(autouse=True)
def stub_assistant(monkeypatch):
    asked = []

    async def fake_ask(text):
        asked.append(text)
        return "reply to: " + text

    monkeypatch.setattr(server.assistant, "ask", fake_ask)
    if storage.DATA_FILE.exists():
        storage.DATA_FILE.unlink()
    return asked


def test_chat_requires_token():
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    bad = {"Authorization": "Bearer wrong"}
    assert client.post("/api/chat", json={"message": "hi"}, headers=bad).status_code == 401
    assert client.get("/api/reminders/due").status_code == 401


def test_chat_works_and_validates(stub_assistant):
    r = client.post("/api/chat", json={"message": "plan my day"}, headers=AUTH)
    assert r.status_code == 200 and r.json() == {"reply": "reply to: plan my day"}
    assert stub_assistant == ["plan my day"]
    assert client.post("/api/chat", json={"message": ""}, headers=AUTH).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 4001}, headers=AUTH).status_code == 422


def test_due_reminders_returned_once():
    storage.add_reminder("Call bank", (storage.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"))
    assert client.get("/api/reminders/due", headers=AUTH).json() == {"reminders": []}
    d = storage._load()
    d["reminders"][0]["when"] = (storage.now() - timedelta(minutes=1)).isoformat()
    storage._save(d)
    assert client.get("/api/reminders/due", headers=AUTH).json() == {"reminders": ["Call bank"]}
    assert client.get("/api/reminders/due", headers=AUTH).json() == {"reminders": []}


def test_page_and_health_are_public_and_safe():
    assert client.get("/health").json() == {"ok": True}
    page = client.get("/")
    assert page.status_code == 200 and "Personal Assistant" in page.text
    assert "innerHTML" not in page.text          # replies are rendered as text, never HTML
    assert "default-src 'none'" in page.text
