"""The OpenRouter account has no paid budget: these pin that call_ai only ever
sends free model ids, always with a zero max_price, in groups of at most 3,
and that caching and rate-limit cooldown keep it inside the free quota."""

import time

import pytest

from app.ai import provider


class FakeResponse:
    def __init__(self, status_code=200, content="ok", error=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content
        self._error = error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._error is not None:
            return {"error": {"message": self._error}}
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.fixture
def ai_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODELS", raising=False)
    monkeypatch.setattr(provider, "_cooldown_until", 0.0)
    monkeypatch.setattr(provider, "_cache", {})
    monkeypatch.setattr(provider, "_inflight", {})
    sent = []

    def install(*responses):
        queue = list(responses)

        def fake_post(url, headers, json, timeout):
            sent.append(json)
            return queue.pop(0) if queue else FakeResponse()

        monkeypatch.setattr(provider.httpx, "post", fake_post)
        return sent

    return install


def test_paid_models_in_config_are_dropped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "openai/gpt-4o-mini, google/gemma-4-31b-it:free,anthropic/claude-x, openrouter/free")
    assert provider.free_models() == ["google/gemma-4-31b-it:free", "openrouter/free"]


def test_all_paid_config_means_no_call(ai_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "openai/gpt-4o-mini")
    sent = ai_env()
    assert provider.call_ai("sys", "user") is None
    assert sent == []


def test_default_list_is_all_free():
    assert provider.DEFAULT_FREE_MODELS
    assert all(provider.is_free_model(m) for m in provider.DEFAULT_FREE_MODELS)


def test_request_shape_is_free_only_with_zero_price_cap(ai_env):
    sent = ai_env(FakeResponse(content="hello"))
    assert provider.call_ai("sys", "user") == "hello"
    body = sent[0]
    assert "model" not in body
    assert len(body["models"]) <= provider.MODELS_PER_REQUEST
    assert all(provider.is_free_model(m) for m in body["models"])
    assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0}
    assert body["reasoning"] == {"enabled": False}


def test_falls_through_to_next_group_on_failure(ai_env):
    sent = ai_env(FakeResponse(status_code=503), FakeResponse(content="from group two"))
    assert provider.call_ai("sys", "user") == "from group two"
    assert sent[0]["models"] == list(provider.DEFAULT_FREE_MODELS[:3])
    assert sent[1]["models"] == list(provider.DEFAULT_FREE_MODELS[3:6])


def test_empty_content_counts_as_failure(ai_env):
    ai_env(FakeResponse(content=""), FakeResponse(content=""))
    assert provider.call_ai("sys", "user") is None


def test_identical_prompts_are_served_from_cache(ai_env):
    sent = ai_env(FakeResponse(content="cached answer"))
    assert provider.call_ai("sys", "same prompt") == "cached answer"
    assert provider.call_ai("sys", "same prompt") == "cached answer"
    assert len(sent) == 1


def test_account_rate_limit_pauses_all_calls(ai_env):
    sent = ai_env(FakeResponse(status_code=429, error="Rate limit exceeded: free-models-per-day"))
    assert provider.call_ai("sys", "first") is None
    assert provider._cooldown_until > time.time()
    assert provider.call_ai("sys", "second") is None
    assert len(sent) == 1


def test_upstream_429_tries_next_group_without_cooldown(ai_env):
    sent = ai_env(FakeResponse(status_code=429, error="Provider returned error"), FakeResponse(content="ok2"))
    assert provider.call_ai("sys", "user") == "ok2"
    assert provider._cooldown_until == 0.0
    assert len(sent) == 2
