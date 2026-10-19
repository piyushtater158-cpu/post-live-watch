"""Resolves one deliverable's effective terms against the campaign brief.

The campaign brief (campaigns.required_disclosure/required_tag/required_hashtag/
requires_link_sticker) is a DEFAULT, not a law — real creator deals negotiate
requirements away, pay in different ways (cash, barter, affiliate, bonus), and
this is the one place that reconciles the two. Every detector in detectors.py
reads only the resolved result (via PostContext); none of them know a
negotiation happened. That keeps the rules engine pure and keeps this the
single transparent place contract logic lives — the same instinct
config/thresholds.yaml follows for rule numbers.

NULL on a deliverable override column means "inherit the campaign default".
Empty string on required_tag/required_hashtag means "waived — not required
at all", which is different from NULL and must be preserved (COALESCE alone
cannot express it, since SQL COALESCE treats '' as a value, not as NULL --
this module does the waiving logic explicitly, see _resolve_text below).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ResolvedTerms:
    required_disclosure: list[str]       # accepted tokens, lowercase; empty list = waived
    required_tag: str                    # '' = waived
    required_hashtag: str                # '' = waived
    requires_link_sticker: bool
    is_story: bool
    min_reach: int | None                # None = no reach guarantee in this deal
    deal_type: str
    contract_notes: list[dict] = field(default_factory=list)  # [{"requirement": ..., "note": ...}]


def _resolve_text(override: str | None, default: str) -> str:
    """NULL -> inherit the default. Any string (including '') -> use it as-is,
    so an explicit '' deliverable override reliably means "waived"."""
    return default if override is None else override


def resolve_terms(deliverable_row: dict, campaign_row: dict) -> ResolvedTerms:
    fmt = deliverable_row["format"]
    is_story = fmt == "story"
    notes: list[dict] = []

    disclosure_raw = _resolve_text(deliverable_row.get("required_disclosure"), campaign_row["required_disclosure"])
    required_disclosure = [tok.strip().lower() for tok in disclosure_raw.split("|") if tok.strip()]

    required_tag = _resolve_text(deliverable_row.get("required_tag"), campaign_row["required_tag"])
    required_hashtag = _resolve_text(deliverable_row.get("required_hashtag"), campaign_row["required_hashtag"])

    link_override = deliverable_row.get("requires_link_sticker")
    if link_override is None:
        # No explicit override: link stickers are a Story-only IG feature, so
        # only stories inherit the campaign's requires_link_sticker default.
        # This is a structural fact about the format, not a negotiated term —
        # it does NOT get a contract note (every reel/carousel would carry one
        # otherwise, and that's noise, not a deal detail worth surfacing).
        requires_link_sticker = bool(campaign_row["requires_link_sticker"]) and is_story
    else:
        requires_link_sticker = bool(link_override)
        if not is_story and link_override:
            # An explicit override DID negotiate a link sticker onto a non-
            # story format — unusual enough to be worth a note.
            notes.append({"requirement": "Link sticker", "note": f"Explicitly required for this {fmt} deal."})

    waived_raw = deliverable_row.get("waived_notes")
    waived = json.loads(waived_raw) if waived_raw else {}
    label_for = {
        "required_disclosure": "Disclosure",
        "required_tag": "Brand tag",
        "required_hashtag": "Hashtag",
        "requires_link_sticker": "Link sticker",
    }
    for key, reason in waived.items():
        notes.append({"requirement": label_for.get(key, key), "note": reason})

    # Generic fallback note for a waived tag/hashtag — only when no explicit
    # waived_notes reason was already given above, so the two never duplicate.
    if required_tag == "" and "required_tag" not in waived:
        notes.append({"requirement": "Brand tag", "note": "Not required for this deal."})
    if required_hashtag == "" and "required_hashtag" not in waived:
        notes.append({"requirement": "Hashtag", "note": "Not required for this deal."})

    min_reach = deliverable_row.get("min_reach")
    if min_reach is None:
        notes.append({"requirement": "Reach guarantee", "note": "No minimum reach was negotiated for this deal."})

    return ResolvedTerms(
        required_disclosure=required_disclosure,
        required_tag=required_tag,
        required_hashtag=required_hashtag,
        requires_link_sticker=requires_link_sticker,
        is_story=is_story,
        min_reach=min_reach,
        deal_type=deliverable_row.get("deal_type") or "paid",
        contract_notes=notes,
    )
