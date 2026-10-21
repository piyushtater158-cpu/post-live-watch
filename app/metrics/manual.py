"""Manual metrics entry: the AM types or pastes a creator's current numbers
(reach, likes, comments, saves, shares) straight into a per-deliverable form.
Writes a normal post_snapshots row labelled 'am_entered' — the same table and
the same rules-engine read path every other source uses, just with a human
instead of an API behind it.

ManualProvider itself is a deliberate no-op on the fetch side (see
app/metrics/seeded.py's identical reasoning): there is nothing to sync on a
schedule for a campaign an AM is typing numbers into by hand. The real work
here is record_manual_snapshot, called directly by the /deliverables/{id}/
metrics route rather than through app/metrics/sync.py's provider interface.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .base import MetricsProvider


class ManualProvider(MetricsProvider):
    name = "manual"


def record_manual_snapshot(
    conn: sqlite3.Connection, post_id: int, day_number: int,
    reach: int | None, likes: int, comments_count: int,
    saves: int | None = None, shares: int | None = None, still_live: bool = True,
) -> int:
    """Upserts one (post_id, day_number) snapshot row — re-entering the same
    day overwrites rather than duplicates, matching app/metrics/sync.py's own
    upsert discipline for the Instagram tiers."""
    existing = conn.execute(
        "SELECT id FROM post_snapshots WHERE post_id = ? AND day_number = ?", (post_id, day_number),
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        conn.execute(
            "UPDATE post_snapshots SET reach = ?, likes = ?, comments_count = ?, saves = ?, shares = ?, "
            "still_live = ?, source = 'am_entered', fetched_at = ? WHERE id = ?",
            (reach, likes, comments_count, saves, shares, int(still_live), now, existing["id"]),
        )
        snapshot_id = existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO post_snapshots (post_id, day_number, reach, likes, comments_count, saves, shares, "
            "still_live, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'am_entered', ?)",
            (post_id, day_number, reach, likes, comments_count, saves, shares, int(still_live), now),
        )
        snapshot_id = cur.lastrowid
    conn.commit()
    return snapshot_id
