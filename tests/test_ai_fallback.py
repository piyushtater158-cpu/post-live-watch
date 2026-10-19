"""No OPENROUTER_API_KEY is set in the test environment, so every AI task
must fall back to its template cleanly — this is the 'AI off still works
end-to-end' requirement from the brief."""

import os

from app.ai import provider


def test_call_ai_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert provider.call_ai("sys", "user") is None


def test_underperform_explanation_falls_back(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = provider.explain_underperformance(True, "handle", 5000, 10000, 9000, "skincare", "reel")
    assert "handle" in text
    assert "5000" in text


def test_sentiment_falls_back_to_keyword_mode(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = provider.classify_sentiment(True, [{"text": "this gave me a rash"}])
    assert "keyword" in result["summary"].lower()


def test_nudge_message_falls_back(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    text = provider.generate_nudge_message(True, "handle", "Missing disclosure", "no #ad tag")
    assert "handle" in text


def test_ai_disabled_skips_the_call_entirely(monkeypatch):
    called = {"hit": False}

    def fake_call(*a, **k):
        called["hit"] = True
        return "should not happen"

    monkeypatch.setattr(provider, "call_ai", fake_call)
    text = provider.explain_underperformance(False, "handle", 5000, 10000, 9000, "skincare", "reel")
    assert called["hit"] is False
    assert "handle" in text


_CAMPAIGN = {
    "required_tag": "@glowleaf", "required_hashtag": "#GlowWithGlowLeaf",
    "required_disclosure": "#ad|paid partnership", "requires_link_sticker": 1,
}


def test_parse_deal_brief_falls_back(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    draft = provider.parse_deal_brief(True, "Signed @priya for 1 reel, ₹10k, 20k min reach",
                                       _CAMPAIGN, current_day=1, duration_days=7, known_handles=["glow_with_meera"])
    assert draft["source"] == "template"
    assert draft["creator"]["handle"] == "priya"
    assert draft["deliverables"][0]["fee"] == 10000


def test_parse_deal_brief_ai_disabled_skips_call(monkeypatch):
    called = {"hit": False}

    def fake_call(*a, **k):
        called["hit"] = True
        return "should not happen"

    monkeypatch.setattr(provider, "call_ai", fake_call)
    draft = provider.parse_deal_brief(False, "Signed @priya for 1 reel, ₹10k",
                                       _CAMPAIGN, current_day=1, duration_days=7, known_handles=[])
    assert called["hit"] is False
    assert draft["source"] == "template"
