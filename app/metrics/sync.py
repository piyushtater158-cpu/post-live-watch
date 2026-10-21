"""sync_campaign: pulls each provider's latest read of a campaign's posts and
writes it into posts/post_snapshots — the single place that turns a
MetricsProvider's output into real rows, regardless of which provider ran.

Matching a fetched media item to a deliverable: first by posts.ig_media_id
if a previous sync already resolved it, otherwise by nearest posted-time to
the deliverable's promised_date among that creator's UNMATCHED media this
run. Format (reel/carousel/story) is NOT used to narrow the match — Instagram's
media_type doesn't map cleanly onto this app's format vocabulary, and Stories
never appear in either Instagram tier's results at all, so a story
deliverable is skipped before matching is even attempted. An item that can't
be confidently matched is recorded, never guessed onto the wrong deliverable
(see fetch_runs.errors).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.db import get_campaign_day

from .base import MetricsProvider, NotConfigured, PostMetrics


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _creator_deliverable_rows(conn: sqlite3.Connection, campaign_id: int, creator_id: int) -> list[dict]:
    return [
        dict(r) for r in conn.execute(
            "SELECT d.id AS deliverable_id, d.format, d.promised_date, p.id AS post_id, "
            "p.ig_media_id, p.posted_at, p.original_caption "
            "FROM deliverables d JOIN posts p ON p.deliverable_id = d.id "
            "WHERE d.campaign_id = ? AND d.creator_id = ? ORDER BY d.promised_date",
            (campaign_id, creator_id),
        ).fetchall()
    ]


def _upsert_snapshot(conn: sqlite3.Connection, post_id: int, day_number: int, metrics: PostMetrics,
                      fetched_at: str) -> None:
    existing = conn.execute(
        "SELECT id FROM post_snapshots WHERE post_id = ? AND day_number = ?", (post_id, day_number),
    ).fetchone()
    values = (metrics.reach, metrics.likes, metrics.comments_count, metrics.saves, metrics.shares,
              int(metrics.still_live), metrics.source, fetched_at)
    if existing:
        conn.execute(
            "UPDATE post_snapshots SET reach = ?, likes = ?, comments_count = ?, saves = ?, shares = ?, "
            "still_live = ?, source = ?, fetched_at = ? WHERE id = ?",
            (*values, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO post_snapshots (post_id, day_number, reach, likes, comments_count, saves, shares, "
            "still_live, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (post_id, day_number, *values),
        )


def _carry_forward_disappearance(conn: sqlite3.Connection, post_id: int, day_number: int) -> None:
    """A previously-matched media item vanished from this run's fetch —
    rule_8 (Deleted or archived early) reads a still_live transition, so this
    writes still_live=0 at today's day, carrying the last known numbers
    forward rather than inventing a fresh reading for a post that produced
    none this run. Upserts rather than skip-if-exists: a second sync on the
    SAME day_number (e.g. someone hits 'sync now' twice) must still catch
    the disappearance, not silently leave today's still-live=1 row from the
    earlier run standing."""
    last = conn.execute(
        "SELECT reach, likes, comments_count, saves, shares, source FROM post_snapshots "
        "WHERE post_id = ? ORDER BY day_number DESC LIMIT 1", (post_id,),
    ).fetchone()
    if last is None:
        return
    existing_today = conn.execute(
        "SELECT id FROM post_snapshots WHERE post_id = ? AND day_number = ?", (post_id, day_number),
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if existing_today:
        conn.execute(
            "UPDATE post_snapshots SET reach = ?, likes = ?, comments_count = ?, saves = ?, shares = ?, "
            "still_live = 0, source = ?, fetched_at = ? WHERE id = ?",
            (last["reach"], last["likes"], last["comments_count"], last["saves"], last["shares"],
             last["source"], now, existing_today["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO post_snapshots (post_id, day_number, reach, likes, comments_count, saves, shares, "
            "still_live, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (post_id, day_number, last["reach"], last["likes"], last["comments_count"], last["saves"],
             last["shares"], last["source"], now),
        )


def sync_campaign(conn: sqlite3.Connection, campaign_id: int, provider: MetricsProvider) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    provider_name = getattr(provider, "name", "unknown")
    errors: list[dict] = []
    posts_attempted = 0
    posts_updated = 0

    try:
        day_number = get_campaign_day(conn, campaign_id)
        creators = [
            dict(r) for r in conn.execute(
                "SELECT DISTINCT c.id, c.handle, c.ig_user_id FROM creators c "
                "JOIN deliverables d ON d.creator_id = c.id WHERE d.campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        ]

        for creator in creators:
            deliverables = [d for d in _creator_deliverable_rows(conn, campaign_id, creator["id"])
                             if d["format"] != "story"]  # Stories are invisible to every Instagram tier
            if not deliverables:
                continue
            posts_attempted += len(deliverables)

            try:
                media_items = provider.fetch_creator_media(creator["ig_user_id"], creator["handle"])
            except Exception as exc:
                errors.append({"creator_handle": creator["handle"], "message": str(exc)})
                continue

            media_by_id = {m.ig_media_id: m for m in media_items if m.ig_media_id}
            unmatched_deliverables = []
            matched_media_ids: set[str] = set()

            # Pass 1: a deliverable already resolved to a specific media id in a previous sync.
            for d in deliverables:
                if d["ig_media_id"] and d["ig_media_id"] in media_by_id:
                    item = media_by_id[d["ig_media_id"]]
                    matched_media_ids.add(item.ig_media_id)
                    _apply_match(conn, d, item, day_number, started_at)
                    posts_updated += 1
                else:
                    unmatched_deliverables.append(d)

            # Pass 2: nearest posted-time match among this run's still-unmatched media.
            remaining_media = [m for m in media_items if m.ig_media_id not in matched_media_ids]
            for d in unmatched_deliverables:
                promised = _parse_dt(d["promised_date"])
                best, best_gap = None, None
                for item in remaining_media:
                    item_dt = _parse_dt(item.posted_at)
                    if item_dt is None or promised is None:
                        continue
                    gap = abs((item_dt - promised).total_seconds())
                    if best_gap is None or gap < best_gap:
                        best, best_gap = item, gap
                if best is not None:
                    remaining_media.remove(best)
                    _apply_match(conn, d, best, day_number, started_at)
                    posts_updated += 1

            # Media this creator has that matched no deliverable at all — recorded, not guessed.
            for item in remaining_media:
                errors.append({"creator_handle": creator["handle"], "ig_media_id": item.ig_media_id,
                                "message": "fetched media did not match any deliverable in this campaign"})

            # A deliverable whose previously-known media id vanished from this run's results.
            for d in deliverables:
                if d["ig_media_id"] and d["ig_media_id"] not in media_by_id and d["ig_media_id"] not in matched_media_ids:
                    _carry_forward_disappearance(conn, d["post_id"], day_number)

        conn.commit()
        status = "ok" if not errors else ("partial" if posts_updated else "error")

    except NotConfigured as exc:
        conn.rollback()
        return _write_fetch_run(conn, campaign_id, provider_name, started_at, 0, 0, "not_configured", [str(exc)])
    except Exception as exc:
        conn.rollback()
        return _write_fetch_run(conn, campaign_id, provider_name, started_at, posts_attempted, 0, "error", [str(exc)])

    return _write_fetch_run(conn, campaign_id, provider_name, started_at, posts_attempted, posts_updated, status, errors)


def _apply_match(conn: sqlite3.Connection, deliverable_row: dict, item: PostMetrics, day_number: int,
                  fetched_at: str) -> None:
    post_id = deliverable_row["post_id"]
    _upsert_snapshot(conn, post_id, day_number, item, fetched_at)

    caption_changed = deliverable_row["original_caption"] is not None and item.caption is not None \
        and item.caption != deliverable_row["original_caption"]
    conn.execute(
        "UPDATE posts SET ig_media_id = ?, last_fetched_at = ?, "
        "posted_at = COALESCE(posted_at, ?), permalink = COALESCE(?, permalink), "
        "original_caption = COALESCE(original_caption, ?), caption = ?, "
        "caption_edited_at = CASE WHEN ? THEN ? ELSE caption_edited_at END "
        "WHERE id = ?",
        (item.ig_media_id, fetched_at, item.posted_at, item.permalink, item.caption, item.caption,
         caption_changed, fetched_at, post_id),
    )


def run_sync(conn: sqlite3.Connection, campaign_id: int) -> dict:
    """Dispatches on campaigns.metrics_provider and constructs the matching
    provider — the one entry point app/main.py's and app/api.py's
    /campaigns/{id}/sync routes call, so they stay thin and never need to
    know which provider class exists for which name."""
    from app.intake import campaign_row  # local import avoids a module-load cycle with app.intake
    from .instagram import InstagramProvider

    campaign = campaign_row(conn, campaign_id)
    provider_name = campaign["metrics_provider"]
    started_at = datetime.now(timezone.utc).isoformat()

    if provider_name == "seeded":
        return _write_fetch_run(conn, campaign_id, "seeded", started_at, 0, 0, "not_applicable",
                                 ["Seeded campaigns don't sync — their data was loaded once at seed time."])
    if provider_name == "manual":
        return _write_fetch_run(conn, campaign_id, "manual", started_at, 0, 0, "not_applicable",
                                 ["This campaign is on manual metrics entry — use the per-deliverable form."])
    if provider_name != "instagram":
        return _write_fetch_run(conn, campaign_id, provider_name, started_at, 0, 0, "error",
                                 [f"Unknown metrics_provider '{provider_name}'."])

    try:
        provider = InstagramProvider()
    except NotConfigured as exc:
        return _write_fetch_run(conn, campaign_id, "instagram", started_at, 0, 0, "not_configured", [str(exc)])
    return sync_campaign(conn, campaign_id, provider)


def _write_fetch_run(conn: sqlite3.Connection, campaign_id: int, provider_name: str, started_at: str,
                      posts_attempted: int, posts_updated: int, status: str, errors: list) -> dict:
    finished_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO fetch_runs (campaign_id, provider, started_at, finished_at, posts_attempted, "
        "posts_updated, status, errors) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (campaign_id, provider_name, started_at, finished_at, posts_attempted, posts_updated, status,
         json.dumps(errors) if errors else None),
    )
    conn.commit()
    return {"campaign_id": campaign_id, "provider": provider_name, "status": status,
            "posts_attempted": posts_attempted, "posts_updated": posts_updated, "errors": errors}
