"""Instagram metrics connector — two tiers, degrading per creator:

1. Branded content (Partnership Ads Advertisable Content API). Returns media
   where OUR brand is tagged as a paid partner, WITH organic insights —
   reach, likes, comments, views, shares, saves — included directly in the
   same response (no separate per-media insights call). This is the only
   tier that ever carries reach.
   Endpoint: GET /{business_id}/partnership-ads-advertisable-content
   Needs: a Meta Business-type app, a Business Portfolio, an Admin system
   user token, and App Review on instagram_branded_content_ads_brand.

2. Public (business_discovery). Any public professional account's recent
   media: caption, like_count, comments_count, timestamp, permalink — NEVER
   reach, and NEVER Stories (Instagram does not expose another account's
   Stories through any public API). Needs only instagram_basic.
   Endpoint: GET /{our_ig_user_id}?fields=business_discovery.username(...)

Neither tier can see comment TEXT on someone else's post, or Story insights —
see docs/meta-setup.md's capability table. Those stay on the manual path
(app/metrics/manual.py) permanently, not just until a better token exists.

Raises NotConfigured when the required META_* env vars are absent, exactly
like app/ai/provider.py's call_ai returning None when OPENROUTER_API_KEY is
unset — app/metrics/sync.py catches it and reports 'not_configured' rather
than crashing. The one HTTP seam (_get) is what tests/fixtures/meta/'s
fixtures replace via monkeypatching, following tests/test_ai_fallback.py's
pattern for the AI layer.

Field shapes below are Meta's documented schema as of Oct 2026 — no Meta app
exists yet to verify them against a live token (see docs/meta-setup.md). The
matching heuristic in app/metrics/sync.py is best-effort for exactly that
reason: it tolerates an unmatched item rather than guessing.
"""

from __future__ import annotations

import os

import httpx

from .base import MetricsProvider, NotConfigured, PostMetrics

GRAPH_VERSION_DEFAULT = "v21.0"
REQUEST_TIMEOUT = 15.0

# organic_insights' field names, verified against Meta's Partnership Ads
# Advertisable Content API docs (Oct 2026) — likes/comments/views/reach/
# shares/interaction/saves, each a nullable int.
_BRANDED_CONTENT_FIELDS = "content_id,caption,permalink,creation_time,media_type,organic_insights"
_PUBLIC_MEDIA_FIELDS = "caption,like_count,comments_count,timestamp,permalink,media_type,id"


class InstagramProvider(MetricsProvider):
    name = "instagram"

    def __init__(self) -> None:
        self.business_id = os.environ.get("META_BUSINESS_ID")
        self.ig_business_id = os.environ.get("META_IG_BUSINESS_ID")
        self.token = os.environ.get("META_SYSTEM_USER_TOKEN")
        self.graph_version = os.environ.get("META_GRAPH_VERSION") or GRAPH_VERSION_DEFAULT
        if not (self.business_id and self.ig_business_id and self.token):
            raise NotConfigured(
                "META_BUSINESS_ID / META_IG_BUSINESS_ID / META_SYSTEM_USER_TOKEN not set — see docs/meta-setup.md"
            )
        self._base_url = f"https://graph.facebook.com/{self.graph_version}"

    def _get(self, path: str, params: dict) -> dict:
        """The one HTTP seam — tests monkeypatch this method directly rather
        than mocking httpx, same isolation app/ai/provider.py's call_ai gets
        from _request."""
        resp = httpx.get(f"{self._base_url}/{path}", params={**params, "access_token": self.token},
                          timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def _branded_content_media(self, creator_ig_user_id: str) -> list[PostMetrics]:
        data = self._get(
            f"{self.business_id}/partnership-ads-advertisable-content",
            {"ig_user_id": self.ig_business_id, "ad_partner_ig_user_ids": f'["{creator_ig_user_id}"]',
             "fields": _BRANDED_CONTENT_FIELDS, "limit": 50},
        )
        out = []
        for item in data.get("data", []):
            insights = item.get("organic_insights") or {}
            out.append(PostMetrics(
                ig_media_id=item.get("content_id"),
                reach=insights.get("reach"),
                likes=insights.get("likes"),
                comments_count=insights.get("comments"),
                saves=insights.get("saves"),
                shares=insights.get("shares"),
                still_live=True,
                caption=item.get("caption"),
                posted_at=item.get("creation_time"),
                permalink=item.get("permalink"),
                source="branded_content",
            ))
        return out

    def _public_media(self, creator_handle: str) -> list[PostMetrics]:
        data = self._get(
            str(self.ig_business_id),
            {"fields": f"business_discovery.username({creator_handle})"
                       f"{{followers_count,media_count,media.limit(50){{{_PUBLIC_MEDIA_FIELDS}}}}}"},
        )
        discovery = data.get("business_discovery") or {}
        items = (discovery.get("media") or {}).get("data", [])
        out = []
        for item in items:
            out.append(PostMetrics(
                ig_media_id=item.get("id"),
                reach=None,  # the public tier never returns reach — see this module's docstring
                likes=item.get("like_count"),
                comments_count=item.get("comments_count"),
                saves=None, shares=None,
                still_live=True,
                caption=item.get("caption"),
                posted_at=item.get("timestamp"),
                permalink=item.get("permalink"),
                source="public",
            ))
        return out

    def fetch_creator_media(self, creator_ig_user_id: str | None, creator_handle: str) -> list[PostMetrics]:
        """Branded content first (it carries reach); if that call fails or
        this creator's IG id isn't resolved yet, fall back to public —
        exactly the capability degrade this module's docstring describes.
        A creator with NEITHER (unresolved handle, no API access at all)
        yields an empty list; app/metrics/sync.py records that as 'no
        update,' not as an error."""
        out: list[PostMetrics] = []
        if creator_ig_user_id:
            try:
                out = self._branded_content_media(creator_ig_user_id)
            except Exception:
                out = []  # network/permission/rate-limit error — fall through to public
        if not out:
            try:
                out = self._public_media(creator_handle)
            except Exception:
                out = []
        return out

    def resolve_creator(self, handle: str) -> dict | None:
        """Pre-signing research: followers + a measured engagement rate from
        recent media, to replace app/intake.py's follower-count estimate.
        Only the public tier is needed here — a creator being researched
        hasn't signed anything yet, so there's no branded-content tag to
        read."""
        try:
            data = self._get(
                str(self.ig_business_id),
                {"fields": f"business_discovery.username({handle})"
                           f"{{followers_count,media_count,media.limit(25){{like_count,comments_count,caption}}}}"},
            )
        except Exception:
            return None
        discovery = data.get("business_discovery")
        if not discovery:
            return None
        followers = discovery.get("followers_count") or 0
        media_items = (discovery.get("media") or {}).get("data", [])
        if followers > 0 and media_items:
            avg_engagement_rate = sum(
                (m.get("like_count") or 0) + (m.get("comments_count") or 0) for m in media_items
            ) / len(media_items) / followers
        else:
            avg_engagement_rate = None
        return {
            "followers": followers,
            "media_count": discovery.get("media_count"),
            "avg_engagement_rate": avg_engagement_rate,
            "recent_captions": [m.get("caption") for m in media_items if m.get("caption")],
        }
