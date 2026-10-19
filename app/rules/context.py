"""Loads everything a detector needs for one post, filtered to what would
actually be known as of `current_day` of the campaign — this is what makes
the day simulator work: advancing current_day reveals more snapshot/comment
rows and lets later-arriving flags fire."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .contract import resolve_terms


@dataclass
class PostContext:
    post_id: int
    deliverable_id: int
    campaign_start: datetime
    duration_days: int
    required_disclosure: list[str]  # resolved accepted tokens, lowercase; empty = waived
    required_tag: str               # resolved; '' = waived
    required_hashtag: str           # resolved; '' = waived
    banned_claims: list[str]
    creator_id: int
    creator_handle: str
    creator_avg_reach: float
    creator_avg_engagement_rate: float
    format: str
    fee: float | None
    promised_date: datetime
    min_reach: int | None           # None = no reach guarantee negotiated for this deal
    deal_type: str
    contract_notes: list[dict]      # waived/negotiated terms, surfaced on the flag card — never silent
    posted_at: datetime | None
    caption: str | None
    original_caption: str | None
    caption_edited_at: datetime | None
    link_sticker_present: bool
    requires_link_sticker: bool     # resolved; see app/rules/contract.py
    is_story: bool                  # derived from format, not posts.is_story (deprecated dual source)
    screenshot_uploaded: bool
    competitor_mentioned_day: int | None
    current_day: int
    snapshots: list[dict] = field(default_factory=list)   # filtered, day_number <= current_day, sorted asc
    comments: list[dict] = field(default_factory=list)    # filtered, day_number <= current_day

    @property
    def due_day(self) -> int:
        return (self.promised_date - self.campaign_start).days + 1

    @property
    def as_of(self) -> datetime:
        """End of `current_day` — the moment the dashboard is being viewed as of."""
        return self.campaign_start + timedelta(days=self.current_day)

    @property
    def latest_snapshot(self) -> dict | None:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def previous_snapshot(self) -> dict | None:
        return self.snapshots[-2] if len(self.snapshots) >= 2 else None


def load_post_context(conn: sqlite3.Connection, post_id: int, current_day: int) -> PostContext:
    row = conn.execute(
        "SELECT p.*, d.id AS deliverable_id, d.format, d.fee, d.promised_date, d.min_reach, d.creator_id, "
        "d.required_disclosure AS d_required_disclosure, d.required_tag AS d_required_tag, "
        "d.required_hashtag AS d_required_hashtag, d.requires_link_sticker AS d_requires_link_sticker, "
        "d.deal_type, d.waived_notes, "
        "c.handle AS creator_handle, c.avg_reach AS creator_avg_reach, "
        "c.avg_engagement_rate AS creator_avg_engagement_rate, "
        "camp.start_date, camp.duration_days, "
        "camp.required_disclosure AS camp_required_disclosure, camp.required_tag AS camp_required_tag, "
        "camp.required_hashtag AS camp_required_hashtag, camp.requires_link_sticker AS camp_requires_link_sticker, "
        "camp.banned_claims "
        "FROM posts p "
        "JOIN deliverables d ON d.id = p.deliverable_id "
        "JOIN creators c ON c.id = d.creator_id "
        "JOIN campaigns camp ON camp.id = d.campaign_id "
        "WHERE p.id = ?",
        (post_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no post with id {post_id}")

    import json as _json

    terms = resolve_terms(
        deliverable_row={
            "format": row["format"],
            "required_disclosure": row["d_required_disclosure"],
            "required_tag": row["d_required_tag"],
            "required_hashtag": row["d_required_hashtag"],
            "requires_link_sticker": row["d_requires_link_sticker"],
            "deal_type": row["deal_type"],
            "waived_notes": row["waived_notes"],
            "min_reach": row["min_reach"],
        },
        campaign_row={
            "required_disclosure": row["camp_required_disclosure"],
            "required_tag": row["camp_required_tag"],
            "required_hashtag": row["camp_required_hashtag"],
            "requires_link_sticker": row["camp_requires_link_sticker"],
        },
    )

    snapshots = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM post_snapshots WHERE post_id = ? AND day_number <= ? ORDER BY day_number ASC",
            (post_id, current_day),
        ).fetchall()
    ]
    comments = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM comments WHERE post_id = ? AND day_number <= ? ORDER BY day_number ASC",
            (post_id, current_day),
        ).fetchall()
    ]

    return PostContext(
        post_id=post_id,
        deliverable_id=row["deliverable_id"],
        campaign_start=datetime.fromisoformat(row["start_date"]),
        duration_days=row["duration_days"],
        required_disclosure=terms.required_disclosure,
        required_tag=terms.required_tag,
        required_hashtag=terms.required_hashtag,
        banned_claims=_json.loads(row["banned_claims"]),
        creator_id=row["creator_id"],
        creator_handle=row["creator_handle"],
        creator_avg_reach=row["creator_avg_reach"],
        creator_avg_engagement_rate=row["creator_avg_engagement_rate"],
        format=row["format"],
        fee=row["fee"],
        promised_date=datetime.fromisoformat(row["promised_date"]),
        min_reach=terms.min_reach,
        deal_type=terms.deal_type,
        contract_notes=terms.contract_notes,
        posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
        caption=row["caption"],
        original_caption=row["original_caption"],
        caption_edited_at=datetime.fromisoformat(row["caption_edited_at"]) if row["caption_edited_at"] else None,
        link_sticker_present=bool(row["link_sticker_present"]),
        requires_link_sticker=terms.requires_link_sticker,
        is_story=terms.is_story,
        screenshot_uploaded=bool(row["screenshot_uploaded"]),
        competitor_mentioned_day=row["competitor_mentioned_day"],
        current_day=current_day,
        snapshots=snapshots,
        comments=comments,
    )
