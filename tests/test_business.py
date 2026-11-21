import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import business
import business_tools
import google_tools
import server
import storage
import tools

client = TestClient(server.app)
AUTH = {"Authorization": "Bearer test-access-token-1234"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    if storage.DATA_FILE.exists():
        storage.DATA_FILE.unlink()
    monkeypatch.setenv("TRUSTED_RECIPIENTS", "friend@example.com, @client.com")
    monkeypatch.setenv("MAX_EMAILS_PER_DAY", "3")
    monkeypatch.setenv("MAX_EMAILS_PER_RECIPIENT_PER_DAY", "2")
    monkeypatch.delenv("AUTONOMY", raising=False)
    sent = []
    monkeypatch.setattr(google_tools, "send_email", lambda to, subj, body: sent.append((to, subj, body)) or "id1")
    return sent


def test_trusted_safe_email_is_sent_with_disclosure(env):
    assert business.send_or_queue_email("friend@example.com", "Hello", "Checking in about the call.") \
        == "Email sent to friend@example.com."
    assert len(env) == 1 and "AI assistant" in env[0][2]
    assert storage.count_sent_today() == 1


def test_domain_trust_and_untrusted_queued(env):
    assert business.decide_email("anyone@client.com", "Hi", "Hello there")[0] == "send"
    out = business.send_or_queue_email("stranger@evil.com", "Hi", "Hello there")
    assert out.startswith("NOT sent") and env == []
    item = storage.list_approvals()[0]
    assert item["payload"]["to"] == "stranger@evil.com" and "trusted" in item["reason"]


@pytest.mark.parametrize("text", [
    "The price is Rs 50000", "Our quote: $2,000", "Total ₹40,000", "Please sign the contract",
    "We guarantee delivery", "I can offer a discount", "Payment terms apply", "Invoice attached",
    "Liability is limited", "Here is a refund"])
def test_sensitive_content_always_needs_approval_even_for_trusted(text):
    decision, reason = business.decide_email("friend@example.com", "Update", text)
    assert decision == "approve" and "price" in reason


def test_daily_and_per_recipient_caps(env):
    for _ in range(2):
        business.send_or_queue_email("friend@example.com", "Hi", "Short note")
    assert business.decide_email("friend@example.com", "Hi", "Another")[1].startswith("today's cap for this")
    business.send_or_queue_email("a@client.com", "Hi", "Note")
    assert business.decide_email("b@client.com", "Hi", "Note") == ("approve", "today's send cap has been reached")
    assert len(env) == 3


def test_autonomy_off_queues_everything(monkeypatch, env):
    monkeypatch.setenv("AUTONOMY", "off")
    assert business.send_or_queue_email("friend@example.com", "Hi", "Hello").startswith("NOT sent")
    assert env == []


def test_malformed_requests_rejected():
    for to, subj, body in [("not-an-email", "s", "b"), ("a@b.com, c@d.com", "s", "b"),
                           ("a@b.com", "", "b"), ("a@b.com", "s", " "), ("a@b.com", "s", "x" * 8001)]:
        with pytest.raises(ValueError):
            business.decide_email(to, subj, body)


def test_limits_cannot_be_changed_by_the_model():
    names = tools.tool_names()
    approval_tools = [n for n in names if "approv" in n]
    assert approval_tools == ["mcp__assistant__list_approvals"]            # read-only
    assert not any(t in n for n in names for t in ("trusted", "set_limit", "autonomy_set"))


def test_approve_endpoint_sends_once(env):
    business.send_or_queue_email("stranger@evil.com", "Hi", "Hello there")
    aid = storage.list_approvals()[0]["id"]
    assert client.post(f"/api/approvals/{aid}/approve").status_code == 401   # needs owner token
    assert client.get("/api/approvals", headers=AUTH).json()["approvals"][0]["id"] == aid
    r = client.post(f"/api/approvals/{aid}/approve", headers=AUTH)
    assert r.status_code == 200 and len(env) == 1
    assert client.post(f"/api/approvals/{aid}/approve", headers=AUTH).status_code == 409  # no double send
    assert len(env) == 1 and storage.list_approvals("approved")[0]["id"] == aid


def test_reject_and_bad_ids(env):
    business.send_or_queue_email("stranger@evil.com", "Hi", "Hello there")
    aid = storage.list_approvals()[0]["id"]
    assert client.post(f"/api/approvals/{aid}/reject", headers=AUTH).status_code == 200
    assert client.post(f"/api/approvals/{aid}/approve", headers=AUTH).status_code == 409
    assert client.post("/api/approvals/..%2f..%2fx/approve", headers=AUTH).status_code in (404, 405)
    assert env == []


def test_failed_send_marks_failed(monkeypatch):
    business.send_or_queue_email("stranger@evil.com", "Hi", "Hello there")
    aid = storage.list_approvals()[0]["id"]
    monkeypatch.setattr(google_tools, "send_email", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert client.post(f"/api/approvals/{aid}/approve", headers=AUTH).status_code == 502
    assert storage.list_approvals("failed")[0]["id"] == aid


def test_approvals_expire(env):
    business.send_or_queue_email("stranger@evil.com", "Hi", "Hello there")
    d = storage._load()
    d["approvals"][0]["created"] = (storage.now() - timedelta(days=8)).isoformat()
    storage._save(d)
    aid = d["approvals"][0]["id"]
    assert storage.list_approvals() == [] and storage.list_approvals("expired")
    assert client.post(f"/api/approvals/{aid}/approve", headers=AUTH).status_code == 409
    assert env == []


def test_send_tool_wrapper_and_status(env):
    r = asyncio.run(business_tools.send_email.handler(
        {"to": "stranger@evil.com", "subject": "Hi", "body": "Hello there"}))
    assert "NOT sent" in r["content"][0]["text"]
    st = business.status()
    assert st["can_spend_money"] is False and st["max_emails_per_day"] == 3


def test_leads_pipeline():
    lid = storage.add_lead("Acme Dental", "owner@acme.com", "referral", "wants a website",
                           follow_up=(storage.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M"))
    assert storage.leads_due() == []
    storage.update_lead(storage.list_leads()[0]["id"], stage="proposal", note="sent outline")
    assert storage.list_leads("proposal")[0]["notes"][-1] == "sent outline"
    with pytest.raises(ValueError):
        storage.update_lead("x", stage="hacked")
    d = storage._load(); d["leads"][0]["follow_up"] = (storage.now() - timedelta(hours=1)).isoformat()
    storage._save(d)
    assert [l["name"] for l in storage.leads_due()] == ["Acme Dental"]
    storage.update_lead(d["leads"][0]["id"], stage="won")
    assert storage.leads_due() == []


def test_activity_log_capped():
    for n in range(storage.MAX_ACTIVITY + 10):
        storage.log_activity("email", f"e{n}", "sent")
    assert len(storage._load()["activity"]) == storage.MAX_ACTIVITY
