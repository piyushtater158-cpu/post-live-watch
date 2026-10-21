"""The Instagram connection screen's API: status reports which credentials
are missing (never their values), and the connection test reports Meta's
own error text instead of crashing."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.metrics.instagram import InstagramProvider

ENV = {"META_BUSINESS_ID": "biz_123", "META_IG_BUSINESS_ID": "17841400000000001", "META_SYSTEM_USER_TOKEN": "secret-token-value"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def unconfigured(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def configured(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def test_status_unconfigured_lists_missing_env(client, unconfigured):
    data = client.get("/api/integrations/instagram").json()
    assert data["configured"] is False
    assert data["missing_env"] == ["META_BUSINESS_ID", "META_IG_BUSINESS_ID", "META_SYSTEM_USER_TOKEN"]
    assert any(c["name"] == "LumaDerm Niacinamide Launch" for c in data["instagram_campaigns"])
    assert isinstance(data["recent_runs"], list)


def test_status_configured_never_leaks_token(client, configured):
    resp = client.get("/api/integrations/instagram")
    assert resp.json()["configured"] is True
    assert resp.json()["missing_env"] == []
    assert "secret-token-value" not in resp.text


def test_connection_test_unconfigured(client, unconfigured):
    data = client.post("/api/integrations/instagram/test").json()
    assert data["ok"] is False
    assert "META_SYSTEM_USER_TOKEN" in data["error"]


def test_connection_test_ok(client, configured, monkeypatch):
    monkeypatch.setattr(InstagramProvider, "_get", lambda self, path, params: {
        "id": "17841400000000001", "username": "lumaderm", "name": "LumaDerm", "followers_count": 120000, "media_count": 300,
    })
    data = client.post("/api/integrations/instagram/test").json()
    assert data["ok"] is True
    assert data["account"]["username"] == "lumaderm"
    assert data["account"]["followers"] == 120000


def test_connection_test_surfaces_meta_error(client, configured, monkeypatch):
    def fail(self, path, params):
        request = httpx.Request("GET", "https://graph.facebook.com/v21.0/x")
        response = httpx.Response(400, request=request, json={"error": {"message": "Error validating access token"}})
        raise httpx.HTTPStatusError("400", request=request, response=response)

    monkeypatch.setattr(InstagramProvider, "_get", fail)
    data = client.post("/api/integrations/instagram/test").json()
    assert data == {"ok": False, "error": "Error validating access token", "account": None}
