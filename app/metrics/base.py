"""Shared contract for every metrics source — the seeded demo data, an AM's
manual entry, and the Instagram connector. app/metrics/sync.py writes
whatever a provider returns into posts/post_snapshots the SAME way
regardless of which one produced it; only the resulting `source` label on
each snapshot differs, which is what app/rules/detectors.py's rule_5/rule_12
and app/rules/engine.py's data_notes read to know what they can trust.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PostMetrics:
    """One provider's latest read of one post. None on a field means "this
    source doesn't carry that figure" — never a silent 0 (see app/schema.sql's
    comment on post_snapshots.reach for why that distinction matters)."""
    ig_media_id: str | None
    reach: int | None            # None on every public-tier read; a real figure on branded content
    likes: int | None
    comments_count: int | None
    saves: int | None
    shares: int | None
    still_live: bool
    caption: str | None
    posted_at: str | None        # ISO datetime; None if the provider can't say
    permalink: str | None
    source: str                  # 'branded_content' | 'public' | 'am_entered'


class NotConfigured(Exception):
    """Raised when a provider has no credentials configured — app/metrics/
    sync.py catches this and reports 'not_configured' rather than crashing,
    the same shape app/ai/provider.py's call_ai already uses when
    OPENROUTER_API_KEY is unset (there it's a quiet None; here it's an
    explicit exception because a sync run needs to SAY why nothing happened,
    not just silently produce zero updates)."""


class MetricsProvider:
    """Base class. A provider that has nothing for a given call (rather than
    being entirely unconfigured) returns an empty list / None — the caller
    treats a missing read as 'leave this post's data as it was,' not as a
    new flag-worthy gap.

    fetch_creator_media returns ALL of a creator's available recent media in
    one call, not one lookup per deliverable — both real Instagram tiers
    (app/metrics/instagram.py) naturally return a creator's media as a list,
    and a creator with a 3-deliverable package would otherwise cost 3
    redundant calls for data a single fetch already contains.
    app/metrics/sync.py does the matching from that list onto this
    campaign's specific deliverables."""

    name: str = "unknown"

    def fetch_creator_media(self, creator_ig_user_id: str | None, creator_handle: str) -> list[PostMetrics]:
        """Every recent media item this provider can see for one creator.
        Stories are never included by any tier — see PostMetrics' module
        docstring and docs/meta-setup.md's capability table."""
        return []

    def resolve_creator(self, handle: str) -> dict | None:
        """Pre-signing research: {followers, media_count, avg_engagement_rate,
        recent_captions}, or None if this provider can't look the handle up."""
        return None
