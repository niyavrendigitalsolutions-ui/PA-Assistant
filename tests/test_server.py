import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import server

client = TestClient(server.app)  # no `with`: skips lifespan, so no background loop


def signed(payload: dict):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def wa(sender, text, mid):
    return {"entry": [{"changes": [{"value": {"messages": [
        {"id": mid, "from": sender, "type": "text", "text": {"body": text}}]}}]}]}


@pytest.fixture
def outbox(monkeypatch):
    sent, asked = [], []

    async def fake_send(to, text):
        sent.append((to, text))

    async def fake_ask(text):
        asked.append(text)
        return "reply to: " + text

    monkeypatch.setattr(server, "send_whatsapp", fake_send)
    monkeypatch.setattr(server.assistant, "ask", fake_ask)
    server._seen.clear()
    return sent, asked


def test_verification_handshake():
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                        "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                         "hub.challenge": "42"})
    assert bad.status_code == 403


def test_rejects_bad_signature(outbox):
    body = json.dumps(wa("919876543210", "hi", "m1")).encode()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=bad"})
    assert r.status_code == 403
    assert client.post("/webhook", content=body).status_code == 403
    assert outbox[1] == []


def test_owner_message_answered(outbox):
    body, headers = signed(wa("919876543210", "what's on today?", "m2"))
    assert client.post("/webhook", content=body, headers=headers).status_code == 200
    assert outbox[1] == ["what's on today?"]
    assert outbox[0] == [("919876543210", "reply to: what's on today?")]


def test_stranger_ignored_and_duplicates_skipped(outbox):
    body, headers = signed(wa("911111111111", "hi", "m3"))
    client.post("/webhook", content=body, headers=headers)
    assert outbox == ([], [])
    body, headers = signed(wa("919876543210", "once", "m4"))
    client.post("/webhook", content=body, headers=headers)
    client.post("/webhook", content=body, headers=headers)  # Meta retry
    assert outbox[1] == ["once"]


def test_non_text_gets_polite_reply(outbox):
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "m5", "from": "919876543210", "type": "image"}]}}]}]}
    body, headers = signed(payload)
    client.post("/webhook", content=body, headers=headers)
    assert outbox[0] and "text messages" in outbox[0][0][1]
    assert outbox[1] == []
