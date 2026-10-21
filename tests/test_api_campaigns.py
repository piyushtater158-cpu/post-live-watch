"""Campaign management through the JSON API the Vercel frontend uses: list,
select, parse -> confirm (create a brand-new or in-flight campaign), clock
mode switch, and the campaign edit form — with AI off so the deterministic
fallback drafts. Mirrors tests/test_api_intake.py's structure and cleanup
discipline."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import set_state
from app.main import app

BRIEF = "@glowgirlpriya for 1 reel, ₹20k, min reach 15000, due in 3 days"

CLEANUP_ORDER = ("decisions", "flags", "posts", "deliverables", "creators", "campaigns", "brands")


@pytest.fixture
def client(conn, monkeypatch):
    """Rows these tests create are deleted afterwards — the seeded session DB
    is shared, and other suites assume exactly campaign 1 and its 20 creators."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    set_state(conn, "ai_enabled", "0")
    high_water = {t: conn.execute(f"SELECT COALESCE(MAX(id), 0) m FROM {t}").fetchone()["m"] for t in CLEANUP_ORDER}
    with TestClient(app) as c:
        yield c
    set_state(conn, "selected_campaign_id", "1")
    for table in CLEANUP_ORDER:
        conn.execute(f"DELETE FROM {table} WHERE id > ?", (high_water[table],))
    conn.commit()
    set_state(conn, "ai_enabled", "1")


def _parse(client, **campaign_overrides):
    body = {
        "campaign": {"name": "API Test Launch", "brand_name": "APITestBrand", "duration_days": 10,
                     "days_running": 2, **campaign_overrides},
        "creators_brief_text": BRIEF,
    }
    return client.post("/api/campaigns/parse", json=body)


def test_campaigns_list_shape(client):
    data = client.get("/api/campaigns").json()
    assert "campaigns" in data
    campaign = next(c for c in data["campaigns"] if c["id"] == 1)
    for key in ("name", "brand_name", "duration_days", "current_day", "clock_mode", "status", "metrics_provider"):
        assert key in campaign


def test_parse_drafts_without_writing(client, conn):
    before = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
    resp = _parse(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["blocking_errors"] == []
    draft = body["draft"]
    assert draft["campaign"]["duration_days"] == 10
    assert draft["campaign"]["days_running"] == 2
    assert len(draft["creators"]) == 1
    assert draft["creators"][0]["creator"]["handle"] == "glowgirlpriya"
    assert conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"] == before


def test_missing_campaign_name_blocks(client):
    resp = _parse(client, name="")
    assert resp.json()["blocking_errors"]
    assert any(e["field"] == "campaign.name" for e in resp.json()["blocking_errors"])


def test_confirm_approve_creates_campaign_and_creator(client, conn):
    draft = _parse(client).json()["draft"]
    resp = client.post("/api/campaigns/confirm", json={"action": "approve", "original_draft": draft})
    assert resp.status_code == 200
    body = resp.json()
    assert body["blocking_errors"] == []
    result = body["result"]
    assert result is not None
    campaign_id = result["campaign_id"]

    campaign = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    assert campaign["name"] == "API Test Launch"
    assert campaign["day_override"] is None  # live clock — never simulated by default

    # The campaign is immediately visible and selectable through the normal API surface.
    campaigns = client.get("/api/campaigns").json()["campaigns"]
    assert any(c["id"] == campaign_id for c in campaigns)


def test_confirm_dismiss_writes_nothing(client, conn):
    before = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
    resp = client.post("/api/campaigns/confirm", json={"action": "dismiss"})
    assert resp.json() == {"dismissed": True}
    assert conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"] == before


def test_blocking_confirm_writes_nothing(client, conn):
    draft = _parse(client).json()["draft"]
    draft["campaign"]["name"] = ""  # tampered after preview
    before = conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"]
    resp = client.post("/api/campaigns/confirm", json={"action": "edit", "draft": draft})
    assert resp.json()["result"] is None
    assert any(e["field"] == "campaign.name" for e in resp.json()["blocking_errors"])
    assert conn.execute("SELECT COUNT(*) c FROM campaigns").fetchone()["c"] == before


def test_select_switches_active_campaign(client, conn):
    draft = _parse(client).json()["draft"]
    campaign_id = client.post("/api/campaigns/confirm", json={"action": "approve", "original_draft": draft}).json()["result"]["campaign_id"]

    resp = client.post("/api/campaigns/select", json={"campaign_id": campaign_id})
    assert resp.status_code == 200
    assert resp.json()["campaign_id"] == campaign_id

    assert client.get("/api/state").json()["campaign_id"] == campaign_id


def test_select_unknown_campaign_404s(client):
    assert client.post("/api/campaigns/select", json={"campaign_id": 999999}).status_code == 404


def test_clock_mode_switch_round_trips(client, conn):
    draft = _parse(client).json()["draft"]
    campaign_id = client.post("/api/campaigns/confirm", json={"action": "approve", "original_draft": draft}).json()["result"]["campaign_id"]

    resp = client.post(f"/api/campaigns/{campaign_id}/clock", json={"mode": "simulated"})
    assert resp.status_code == 200 and resp.json()["clock_mode"] == "simulated"

    resp = client.post(f"/api/campaigns/{campaign_id}/clock", json={"mode": "live"})
    assert resp.status_code == 200 and resp.json()["clock_mode"] == "live"


def test_edit_updates_campaign_fields(client, conn):
    draft = _parse(client).json()["draft"]
    campaign_id = client.post("/api/campaigns/confirm", json={"action": "approve", "original_draft": draft}).json()["result"]["campaign_id"]

    resp = client.post(f"/api/campaigns/{campaign_id}/edit", json={
        "name": "Renamed Launch", "required_disclosure": "#ad", "required_tag": "@newtag",
        "required_hashtag": "#NewHashtag", "requires_link_sticker": False, "duration_days": 20,
        "banned_claims": ["cures everything"],
    })
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["name"] == "Renamed Launch"
    assert updated["duration_days"] == 20
    assert updated["requires_link_sticker"] == 0


def test_edit_switches_metrics_provider_to_instagram(client, conn):
    draft = _parse(client).json()["draft"]
    campaign_id = client.post("/api/campaigns/confirm", json={"action": "approve", "original_draft": draft}).json()["result"]["campaign_id"]
    base = {"name": "X", "required_disclosure": "#ad", "duration_days": 10, "banned_claims": []}

    assert client.post(f"/api/campaigns/{campaign_id}/edit", json=base).json()["metrics_provider"] == "manual"  # unchanged
    resp = client.post(f"/api/campaigns/{campaign_id}/edit", json={**base, "metrics_provider": "instagram"})
    assert resp.status_code == 200 and resp.json()["metrics_provider"] == "instagram"
    assert client.post(f"/api/campaigns/{campaign_id}/edit", json={**base, "metrics_provider": "tiktok"}).status_code == 422


def test_campaign_defaults_shape(client):
    data = client.get("/api/campaign-defaults").json()
    assert data["default_duration_days"] == 14
    assert data["max_duration_days"] == 180
    assert "#ad" in data["default_required_disclosure"]
    assert any(b["name"] == "GlowLeaf" for b in data["brands"])


def test_edit_rejects_blank_disclosure(client, conn):
    draft = _parse(client).json()["draft"]
    campaign_id = client.post("/api/campaigns/confirm", json={"action": "approve", "original_draft": draft}).json()["result"]["campaign_id"]

    resp = client.post(f"/api/campaigns/{campaign_id}/edit", json={
        "name": "X", "required_disclosure": "", "duration_days": 10, "banned_claims": [],
    })
    assert resp.status_code == 422


def test_in_flight_campaign_reports_correct_day_through_api(client, conn):
    draft = _parse(client, days_running=5, duration_days=14).json()["draft"]
    result = client.post("/api/campaigns/confirm", json={"action": "approve", "original_draft": draft}).json()["result"]
    campaigns = client.get("/api/campaigns").json()["campaigns"]
    new = next(c for c in campaigns if c["id"] == result["campaign_id"])
    assert new["current_day"] == 5
    assert new["clock_mode"] == "live"


def test_selected_campaign_name_not_hardcoded_on_html_pages(client, conn):
    """Regression guard: several screens used to hardcode 'GlowLeaf' in the
    heading regardless of which campaign was actually selected (found via
    manual browser testing — switching to LumaDerm still showed 'GlowLeaf
    Vitamin C Serum Launch — Campaign Overview'). Checks the actual HEADING
    text, not just page-wide string presence — both campaign names legitimately
    appear together in the nav's campaign-switcher <select>, so a bare
    'not in page text' assertion would false-flag that dropdown."""
    client.post("/api/campaigns/select", json={"campaign_id": 2})  # LumaDerm, seeded by scripts/seed.py

    overview = client.get("/").text
    assert "<h1>LumaDerm Niacinamide Launch — Campaign Overview</h1>" in overview
    assert "GlowLeaf Vitamin C Serum Launch — Campaign Overview" not in overview

    creators_page = client.get("/creators").text
    assert "rollup shown for LumaDerm Niacinamide Launch" in creators_page

    report = client.get("/report").text
    assert "<h1>LumaDerm — Daily Report</h1>" in report
    assert "GlowLeaf" not in report

    profile = client.get("/creators/1").text  # glow_with_meera, also signed to LumaDerm
    assert "Current campaign · LumaDerm Niacinamide Launch" in profile

    # Switch back and confirm the other direction isn't just luck.
    client.post("/api/campaigns/select", json={"campaign_id": 1})
    overview_back = client.get("/").text
    assert "<h1>GlowLeaf Vitamin C Serum Launch — Campaign Overview</h1>" in overview_back
    assert "LumaDerm Niacinamide Launch — Campaign Overview" not in overview_back
