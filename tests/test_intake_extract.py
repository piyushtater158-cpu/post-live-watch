"""Verifies app/ai/templates.py:parse_deal_brief_fallback — the AI-off path
for deal intake. Deliberately worse than the AI path, but must still produce
a usable draft for common phrasings, and must NEVER invent avg_reach/
avg_engagement_rate (app/ai/provider.py's prompt forbids this for the AI
path; this is the fallback's own regression guard for the same rule)."""

from app.ai.templates import parse_deal_brief_fallback

CAMPAIGN = {
    "required_tag": "@glowleaf", "required_hashtag": "#GlowWithGlowLeaf",
    "required_disclosure": "#ad|paid partnership", "requires_link_sticker": 1,
}

CANONICAL_BRIEF = (
    "Signed Priya for 2 reels + 1 story, barter deal worth ₹5k product, no reach guarantee, "
    "she's skipping our campaign hashtag due to an exclusivity clause, due in 3 days"
)


def _parse(text, current_day=1, known_handles=None):
    return parse_deal_brief_fallback(text, CAMPAIGN, current_day, 7, known_handles or [])


def test_canonical_barter_brief():
    draft = _parse(CANONICAL_BRIEF)
    formats = [d["format"] for d in draft["deliverables"]]
    assert formats == ["reel", "reel", "story"]
    for d in draft["deliverables"]:
        assert d["deal_type"] == "barter"
        assert d["fee"] is None
        assert d["barter_value"] == 5000
        assert d["min_reach"] is None
        assert d["min_reach_explicitly_none"] is True
        assert d["required_hashtag"] == ""
        assert "exclusivity" in d["waived_notes"]["required_hashtag"].lower()
        assert d["due_in_days"] == 3
    # Regression guard: never invent a performance figure.
    assert "avg_reach" not in draft["creator"]
    assert "avg_engagement_rate" not in draft["creator"]


def test_handle_extracted_from_at_mention():
    draft = _parse("Renewing @glow_with_meera for one more reel, ₹55k, 40k min reach")
    assert draft["creator"]["handle"] == "glow_with_meera"
    d = draft["deliverables"][0]
    assert d["fee"] == 55000
    assert d["min_reach"] == 40000
    assert d["min_reach_explicitly_none"] is False


def test_handle_guessed_from_name_when_no_at_mention():
    draft = _parse("Signed Priya for 1 reel, ₹10k")
    assert draft["creator"]["handle"] == "priya"
    assert "handle_note" in draft["creator"]


def test_affiliate_deal_type_detected():
    draft = _parse("Booked @casualcosmetics for 1 reel via affiliate commission, no min reach")
    assert draft["deliverables"][0]["deal_type"] == "affiliate"
    assert draft["deliverables"][0]["fee"] is None


def test_paid_deal_fee_extraction():
    draft = _parse("Signed @glowgirlpriya for 1 carousel, fee rs 25000, min reach 15000")
    d = draft["deliverables"][0]
    assert d["deal_type"] == "paid"
    assert d["fee"] == 25000
    assert d["min_reach"] == 15000


def test_link_sticker_waiver_detected():
    draft = _parse("Signed @priya for 1 story, no link sticker, ₹8k")
    assert draft["deliverables"][0]["requires_link_sticker"] is False


def test_no_reach_mention_leaves_blank_not_explicit():
    draft = _parse("Signed @priya for 1 reel, ₹10k")
    d = draft["deliverables"][0]
    assert d["min_reach"] is None
    assert d["min_reach_explicitly_none"] is False


def test_unrecognized_format_falls_through_to_none():
    draft = _parse("Signed @priya for 1 post, ₹10k")
    assert draft["deliverables"][0]["format"] is None


def test_due_by_day_absolute():
    draft = _parse("Signed @priya for 1 reel, ₹10k, due by day 5")
    assert draft["deliverables"][0]["due_day"] == 5


def test_no_deliverables_mentioned_yields_one_placeholder_block():
    draft = _parse("Signed @priya, ₹10k")
    assert len(draft["deliverables"]) == 1
    assert draft["deliverables"][0]["format"] is None
