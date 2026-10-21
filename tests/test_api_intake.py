"""Deal intake through the JSON API the Vercel frontend uses: parse -> preview
-> approve/edit/dismiss, with AI off so the deterministic fallback drafts."""

import pytest
from fastapi.testclient import TestClient

from app.db import set_state
from app.main import app

BARTER_BRIEF = ("Signed Priya for 2 reels + 1 story, barter deal worth ₹5k product, no reach guarantee, "
                "skipping our campaign hashtag due to an exclusivity clause, due in 3 days")
RENEW_BRIEF = "Renewing @glow_with_meera for one more reel, ₹55k, min reach 40k, due by day 5"


CLEANUP_ORDER = ("decisions", "flags", "posts", "deliverables", "creators")


@pytest.fixture
def client(conn, monkeypatch):
    """Rows these tests create are deleted afterwards — the seeded session DB is
    shared, and other suites count a seeded creator's deliverables exactly."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # The day now lives on campaigns.day_override, not a global app_state key —
    # see app/db.py:get_campaign_day.
    conn.execute("UPDATE campaigns SET day_override = 1 WHERE id = 1")
    conn.commit()
    set_state(conn, "ai_enabled", "0")
    high_water = {t: conn.execute(f"SELECT COALESCE(MAX(id), 0) m FROM {t}").fetchone()["m"] for t in CLEANUP_ORDER}
    with TestClient(app) as c:
        yield c
    for table in CLEANUP_ORDER:
        conn.execute(f"DELETE FROM {table} WHERE id > ?", (high_water[table],))
    conn.execute("UPDATE campaigns SET day_override = 7 WHERE id = 1")
    conn.commit()
    set_state(conn, "ai_enabled", "1")


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def test_defaults_expose_campaign_terms(client):
    campaign = client.get("/api/intake").json()["campaign"]
    assert campaign["required_hashtag"] and campaign["duration_days"] == 7


def test_parse_drafts_without_writing(client, conn):
    before = _count(conn, "deliverables")
    body = client.post("/api/intake/parse", json={"brief_text": BARTER_BRIEF}).json()
    draft = body["draft"]
    assert draft["source"] == "template"
    assert [d["format"] for d in draft["deliverables"]] == ["reel", "reel", "story"]
    assert all(d["deal_type"] == "barter" and d["min_reach_explicitly_none"] for d in draft["deliverables"])
    assert all(d["required_hashtag"] == "" for d in draft["deliverables"])
    assert all(d["preview_notes"] for d in draft["deliverables"])
    # Only a first name in the brief: the handle is a flagged guess, an existing
    # look-alike is offered (never auto-applied), and follower count must come from a human.
    assert draft["creator"]["handle"] == "priya" and draft["creator"]["existing_creator_id"] is None
    assert any(w["field"] == "creator.handle" for w in draft["warnings"])
    assert [s["handle"] for s in draft["creator"]["existing_suggestions"]] == ["glowgirlpriya"]
    assert {e["field"] for e in body["blocking_errors"]} == {"creator.followers", "creator.niche"}
    assert _count(conn, "deliverables") == before


def test_edit_confirm_creates_creator_and_audit_rows(client, conn):
    draft = client.post("/api/intake/parse", json={"brief_text": BARTER_BRIEF}).json()["draft"]
    edited = {**draft, "creator": {**draft["creator"], "handle": "priya.glows", "followers": 45000, "niche": "skincare"}}
    body = client.post("/api/intake/confirm", json={"action": "edit", "original_draft": draft, "draft": edited}).json()
    assert body["blocking_errors"] == []
    creator_id = body["result"]["creator_id"]
    assert body["package"]["current_campaign"]["total_deliverables"] == 3

    creator = conn.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
    assert creator["handle"] == "priya.glows" and creator["metrics_source"] == "estimated"
    intake_rows = conn.execute(
        "SELECT * FROM decisions WHERE source = 'intake' AND post_id IN (%s)" % ",".join("?" * 3),
        body["result"]["post_ids"],
    ).fetchall()
    assert len(intake_rows) == 3 and all(r["message_text"] == BARTER_BRIEF for r in intake_rows)

    profile = client.get(f"/api/creators/{creator_id}").json()
    assert profile["creator"]["metrics_source"] == "estimated"


def test_approve_attaches_to_existing_creator_without_duplicating(client, conn):
    creators_before = _count(conn, "creators")
    draft = client.post("/api/intake/parse", json={"brief_text": RENEW_BRIEF}).json()["draft"]
    assert draft["creator"]["existing_creator_id"]
    body = client.post("/api/intake/confirm", json={"action": "approve", "original_draft": draft}).json()
    assert body["blocking_errors"] == []
    assert body["result"]["creator_id"] == draft["creator"]["existing_creator_id"]
    assert _count(conn, "creators") == creators_before


def test_blocking_errors_write_nothing(client, conn):
    draft = client.post("/api/intake/parse", json={"brief_text": RENEW_BRIEF}).json()["draft"]
    bad = {**draft, "deliverables": [{**draft["deliverables"][0], "due_day": 99}]}
    before = _count(conn, "deliverables")
    body = client.post("/api/intake/confirm", json={"action": "edit", "original_draft": draft, "draft": bad}).json()
    assert body["result"] is None
    assert any(e["field"].endswith("due_day") for e in body["blocking_errors"])
    assert _count(conn, "deliverables") == before


def test_dismiss_writes_nothing(client, conn):
    before = _count(conn, "deliverables")
    assert client.post("/api/intake/confirm", json={"action": "dismiss"}).json() == {"dismissed": True}
    assert _count(conn, "deliverables") == before


def test_empty_brief_is_rejected(client):
    assert client.post("/api/intake/parse", json={"brief_text": ""}).status_code == 422
