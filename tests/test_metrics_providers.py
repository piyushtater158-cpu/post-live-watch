"""app/metrics/instagram.py against recorded Meta response shapes (tests/
fixtures/meta/) — no Meta app exists yet, so the one HTTP seam (_get) is
monkeypatched, exactly like tests/test_ai_fallback.py isolates
app/ai/provider.py's call_ai. Verifies: branded-content tier maps
organic_insights onto PostMetrics with reach; public tier never carries
reach; degrade-to-public when branded content errors; NotConfigured when
env vars are absent; resolve_creator derives a measured engagement rate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.metrics.base import NotConfigured, PostMetrics
from app.metrics.instagram import InstagramProvider

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "meta"


def _load(name: str) -> dict:
    with open(FIXTURES / name, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def configured_env(monkeypatch):
    monkeypatch.setenv("META_BUSINESS_ID", "biz_123")
    monkeypatch.setenv("META_IG_BUSINESS_ID", "17841400000000001")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "test-token")


def test_not_configured_without_env(monkeypatch):
    monkeypatch.delenv("META_BUSINESS_ID", raising=False)
    monkeypatch.delenv("META_IG_BUSINESS_ID", raising=False)
    monkeypatch.delenv("META_SYSTEM_USER_TOKEN", raising=False)
    with pytest.raises(NotConfigured):
        InstagramProvider()


def test_branded_content_tier_maps_reach(configured_env, monkeypatch):
    provider = InstagramProvider()
    monkeypatch.setattr(provider, "_get", lambda path, params: _load("branded_content_media.json"))

    media = provider.fetch_creator_media("17900000000000099", "glow_with_meera")
    assert len(media) == 1
    item = media[0]
    assert isinstance(item, PostMetrics)
    assert item.source == "branded_content"
    assert item.reach == 52000
    assert item.likes == 4200
    assert item.comments_count == 310
    assert item.saves == 520
    assert item.shares == 140
    assert item.ig_media_id == "17900000000000001"


def test_public_tier_never_carries_reach(configured_env, monkeypatch):
    provider = InstagramProvider()

    def fake_get(path, params):
        if "partnership-ads-advertisable-content" in path:
            raise RuntimeError("no branded content access")
        return _load("business_discovery.json")

    monkeypatch.setattr(provider, "_get", fake_get)
    media = provider.fetch_creator_media("17900000000000099", "somecreator")
    assert len(media) == 2
    assert all(m.reach is None for m in media)
    assert all(m.source == "public" for m in media)
    assert media[0].likes == 1800
    assert media[0].comments_count == 95


def test_degrades_to_public_when_branded_content_fails(configured_env, monkeypatch):
    provider = InstagramProvider()
    calls = []

    def fake_get(path, params):
        calls.append(path)
        if "partnership-ads-advertisable-content" in path:
            raise RuntimeError(json.dumps(_load("error_permission_missing.json")))
        return _load("business_discovery.json")

    monkeypatch.setattr(provider, "_get", fake_get)
    media = provider.fetch_creator_media("17900000000000099", "somecreator")
    assert len(media) == 2  # fell through to the public tier
    assert any("partnership-ads-advertisable-content" in c for c in calls)


def test_no_creator_ig_user_id_goes_straight_to_public(configured_env, monkeypatch):
    provider = InstagramProvider()
    called_branded = []

    def fake_get(path, params):
        if "partnership-ads-advertisable-content" in path:
            called_branded.append(True)
        return _load("business_discovery.json")

    monkeypatch.setattr(provider, "_get", fake_get)
    media = provider.fetch_creator_media(None, "somecreator")
    assert len(media) == 2
    assert not called_branded  # never attempted without a resolved creator id


def test_both_tiers_failing_returns_empty_list(configured_env, monkeypatch):
    provider = InstagramProvider()
    monkeypatch.setattr(provider, "_get", lambda path, params: (_ for _ in ()).throw(RuntimeError("down")))
    assert provider.fetch_creator_media("x", "y") == []


def test_resolve_creator_derives_measured_engagement_rate(configured_env, monkeypatch):
    provider = InstagramProvider()
    monkeypatch.setattr(provider, "_get", lambda path, params: _load("business_discovery.json"))

    info = provider.resolve_creator("somecreator")
    assert info is not None
    assert info["followers"] == 65000
    # (1800+95 + 950+40) / 2 / 65000
    expected_rate = ((1800 + 95) + (950 + 40)) / 2 / 65000
    assert abs(info["avg_engagement_rate"] - expected_rate) < 1e-9
    assert len(info["recent_captions"]) == 2


def test_resolve_ig_user_id_reads_business_discovery_id(configured_env, monkeypatch):
    provider = InstagramProvider()
    monkeypatch.setattr(provider, "_get", lambda path, params: {"business_discovery": {"id": "17900000000000099"}})
    assert provider.resolve_ig_user_id("somecreator") == "17900000000000099"


def test_resolve_ig_user_id_none_on_error(configured_env, monkeypatch):
    provider = InstagramProvider()
    monkeypatch.setattr(provider, "_get", lambda path, params: (_ for _ in ()).throw(RuntimeError("not found")))
    assert provider.resolve_ig_user_id("ghost") is None


def test_resolve_creator_returns_none_on_private_account(configured_env, monkeypatch):
    provider = InstagramProvider()
    monkeypatch.setattr(provider, "_get", lambda path, params: _load("business_discovery_private.json"))
    assert provider.resolve_creator("privatecreator") is None
