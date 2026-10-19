"""JSON API used by the Vercel frontend: endpoint shapes, the simulator
controls, and the full decide flow (including an opportunity-only card)."""

import pytest
from fastapi.testclient import TestClient

from app.db import set_state
from app.main import app

VIRAL_POST_ID = 19


@pytest.fixture
def client(conn, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    set_state(conn, "current_day", "7")
    set_state(conn, "ai_enabled", "0")
    with TestClient(app) as c:
        yield c
    set_state(conn, "current_day", "1")
    set_state(conn, "ai_enabled", "1")


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_state(client):
    assert client.get("/api/state").json() == {"current_day": 7, "ai_enabled": False, "duration_days": 7}


def test_overview_shape(client):
    data = client.get("/api/overview").json()
    for key in ("posts_live", "total_due", "total_reach", "total_promised", "by_status", "opportunities", "rows"):
        assert key in data
    assert set(data["by_status"]) == {"Act now", "Needs a look", "OK"}
    assert data["total_due"] == len(data["rows"])
    assert {"handle", "creator_id", "format", "status", "max_severity", "reason"} <= set(data["rows"][0])


def test_queue_cards_all_have_a_decision_target(client):
    cards = client.get("/api/queue").json()["cards"]
    assert cards
    for card in cards:
        assert card["primary_rule_id"] is not None
        assert card["default_message"]


def test_creators_and_profile(client):
    creators = client.get("/api/creators").json()["creators"]
    assert len(creators) == 20
    profile = client.get(f"/api/creators/{creators[0]['id']}").json()
    assert {"creator", "reliability", "current_campaign", "current_deliverables"} <= set(profile)
    assert "book_again_hint" in profile["reliability"]


def test_unknown_creator_is_404(client):
    assert client.get("/api/creators/99999").status_code == 404


def test_report_shape(client):
    data = client.get("/api/report").json()
    assert isinstance(data["text"], str) and data["text"]
    assert isinstance(data["highlights"], list)
    assert isinstance(data["issues"], list)


def test_simulator_controls(client):
    assert client.post("/api/simulate/reset-day").json()["current_day"] == 1
    assert client.post("/api/simulate/advance-day").json()["current_day"] == 2
    for _ in range(10):
        st = client.post("/api/simulate/advance-day").json()
    assert st["current_day"] == 7
    assert client.post("/api/settings/ai-toggle").json()["ai_enabled"] is True
    assert client.post("/api/settings/ai-toggle").json()["ai_enabled"] is False


def test_decide_flow_records_approve_edit_dismiss(client):
    cards = client.get("/api/queue").json()["cards"]
    problem = next(c for c in cards if c["flags"])

    approve = client.post(f"/api/flags/{problem['post_id']}/decide", json={
        "action": "approve", "message_text": "ignored", "original_message": problem["default_message"],
        "flag_rule_id": problem["primary_rule_id"],
    })
    assert approve.status_code == 200 and "cards" in approve.json()

    client.post(f"/api/flags/{problem['post_id']}/decide", json={
        "action": "edit", "message_text": "my own words", "original_message": problem["default_message"],
        "flag_rule_id": problem["primary_rule_id"],
    })
    client.post(f"/api/flags/{problem['post_id']}/decide", json={
        "action": "dismiss", "flag_rule_id": problem["primary_rule_id"],
    })

    rows = [r for r in client.get("/api/decisions").json()["rows"] if r["post_id"] == problem["post_id"]]
    by_action = {r["action"]: r for r in rows}
    assert by_action["approve"]["message_text"] == problem["default_message"]
    assert by_action["edit"]["message_text"] == "my own words"
    assert by_action["dismiss"]["message_text"] is None
    assert all(r["handle"] == problem["handle"] for r in rows)
    assert all(r["rule_name"] for r in rows)


def test_opportunity_only_card_can_be_approved(client):
    cards = client.get("/api/queue").json()["cards"]
    viral = next(c for c in cards if c["post_id"] == VIRAL_POST_ID)
    assert viral["flags"] == [] and viral["opportunity_note"]

    resp = client.post(f"/api/flags/{VIRAL_POST_ID}/decide", json={
        "action": "approve", "original_message": viral["default_message"], "flag_rule_id": viral["primary_rule_id"],
    })
    assert resp.status_code == 200
    rows = [r for r in client.get("/api/decisions").json()["rows"] if r["post_id"] == VIRAL_POST_ID]
    assert rows and rows[0]["rule_name"] and rows[0]["message_text"] == viral["default_message"]


def test_decide_rejects_bad_input(client):
    assert client.post("/api/flags/99999/decide", json={"action": "approve"}).status_code == 404
    assert client.post(f"/api/flags/{VIRAL_POST_ID}/decide", json={"action": "nuke"}).status_code == 422


def test_html_pages_still_render(client):
    for path in ("/", "/queue", "/creators", "/report", "/decisions"):
        assert client.get(path).status_code == 200, path
