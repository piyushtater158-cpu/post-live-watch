"""JSON API routes wiring app/metrics/sync.py and app/metrics/manual.py into
the app: POST /api/campaigns/{id}/sync and POST /api/deliverables/{id}/metrics."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import set_state
from app.main import app


@pytest.fixture
def client(conn, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for name in ("META_BUSINESS_ID", "META_IG_BUSINESS_ID", "META_SYSTEM_USER_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as c:
        yield c
    # undo any manual-entry writes this file's tests made to the seeded post
    conn.execute("DELETE FROM post_snapshots WHERE post_id = 1 AND day_number = 6")
    conn.commit()
    set_state(conn, "selected_campaign_id", "1")


def test_sync_seeded_campaign_is_not_applicable(client):
    resp = client.post("/api/campaigns/1/sync")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_applicable"


def test_sync_unknown_campaign_errors_cleanly(client):
    resp = client.post("/api/campaigns/999999/sync")
    assert resp.status_code == 404


def test_manual_metrics_writes_snapshot(client, conn):
    resp = client.post("/api/deliverables/1/metrics", json={
        "day_number": 6, "reach": 12345, "likes": 300, "comments_count": 10, "saves": 5, "shares": 2,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["post_id"] == 1

    row = conn.execute(
        "SELECT * FROM post_snapshots WHERE post_id = 1 AND day_number = 6"
    ).fetchone()
    assert row["reach"] == 12345 and row["source"] == "am_entered"


def test_manual_metrics_unknown_deliverable_404s(client):
    assert client.post("/api/deliverables/999999/metrics", json={
        "day_number": 1, "reach": 100, "likes": 1, "comments_count": 1,
    }).status_code == 404


def test_manual_metrics_html_form_renders(client):
    assert client.get("/deliverables/1/metrics").status_code == 200
    assert client.get("/deliverables/999999/metrics").status_code == 404


def test_creator_research_without_credentials_is_409(client):
    resp = client.get("/api/creators/research/glowgirlpriya")
    assert resp.status_code == 409


def test_creator_research_with_credentials(client, monkeypatch):
    monkeypatch.setenv("META_BUSINESS_ID", "biz_123")
    monkeypatch.setenv("META_IG_BUSINESS_ID", "ig_123")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "token")

    from app.metrics.instagram import InstagramProvider

    def fake_resolve(self, handle):
        return {"followers": 40000, "media_count": 100, "avg_engagement_rate": 0.06, "recent_captions": ["hi"]}

    monkeypatch.setattr(InstagramProvider, "resolve_creator", fake_resolve)
    resp = client.get("/api/creators/research/glowgirlpriya")
    assert resp.status_code == 200
    assert resp.json()["followers"] == 40000


def test_manual_metrics_form_prefills_the_deliverables_OWN_campaign_day(client, conn):
    """Regression guard (found via manual browser testing): the form used to
    prefill the GLOBALLY selected campaign's current_day regardless of which
    campaign deliverable_id actually belongs to — opening the form for a
    GlowLeaf deliverable while LumaDerm was the active campaign in the nav
    showed LumaDerm's day number instead of GlowLeaf's."""
    glowleaf_day = conn.execute(
        "SELECT duration_days, day_override FROM campaigns WHERE id = 1"
    ).fetchone()
    expected_day = glowleaf_day["day_override"]  # campaign 1 is simulated; day_override IS its day

    client.post("/api/campaigns/select", json={"campaign_id": 2})  # LumaDerm — a different day/clock entirely
    state = client.get("/api/state").json()
    assert state["campaign_id"] == 2
    assert state["current_day"] != expected_day  # sanity: the two campaigns are NOT on the same day

    html = client.get("/deliverables/1/metrics").text  # deliverable 1 belongs to campaign 1 (GlowLeaf)
    assert f'value="{expected_day}"' in html, (
        f"expected the form to prefill GlowLeaf's own day ({expected_day}), "
        f"not the globally-selected LumaDerm campaign's day ({state['current_day']})"
    )
