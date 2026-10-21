"""The public (business_discovery) Instagram metrics tier returns likes and
comments but never reach. app/rules/detectors.py's rule_5 (Underperforming)
and rule_12 (Viral winner) must skip cleanly on a NULL reach rather than
treating it as 0 — a 0 would fire rule_5 falsely and permanently silence
rule_12. app/rules/engine.py's data_notes must say why, instead of leaving an
unexplained gap in the queue."""

from __future__ import annotations

import pytest

from app.rules.engine import evaluate_post

UNDERPERFORMING_POST_ID = 8  # fires rule 5 on the seeded data (tests/test_rules.py)
VIRAL_POST_ID = 19  # fires rule 12 on the seeded data


def _latest_snapshot_id(conn, post_id: int) -> int:
    return conn.execute(
        "SELECT id FROM post_snapshots WHERE post_id = ? ORDER BY day_number DESC LIMIT 1", (post_id,)
    ).fetchone()["id"]


@pytest.fixture
def null_reach(conn):
    """Nulls the latest snapshot's reach for both posts (simulating the public
    metrics tier), yields, then restores the original seeded values — these
    posts are load-bearing for tests/test_rules.py's full-campaign assertion."""
    targets = {UNDERPERFORMING_POST_ID: _latest_snapshot_id(conn, UNDERPERFORMING_POST_ID),
               VIRAL_POST_ID: _latest_snapshot_id(conn, VIRAL_POST_ID)}
    originals = {
        pid: conn.execute("SELECT reach, source FROM post_snapshots WHERE id = ?", (sid,)).fetchone()
        for pid, sid in targets.items()
    }
    for sid in targets.values():
        conn.execute("UPDATE post_snapshots SET reach = NULL, source = 'public' WHERE id = ?", (sid,))
    conn.commit()
    yield targets
    for pid, sid in targets.items():
        conn.execute(
            "UPDATE post_snapshots SET reach = ?, source = ? WHERE id = ?",
            (originals[pid]["reach"], originals[pid]["source"], sid),
        )
    conn.commit()


def test_rule_5_does_not_fire_on_unknown_reach(conn, null_reach):
    result = evaluate_post(conn, UNDERPERFORMING_POST_ID, current_day=7)
    assert 5 not in {f["rule_id"] for f in result["flags"]}


def test_rule_12_does_not_fire_on_unknown_reach(conn, null_reach):
    result = evaluate_post(conn, VIRAL_POST_ID, current_day=7)
    assert 12 not in {f["rule_id"] for f in result["opportunities"]}


def test_data_note_explains_the_gap(conn, null_reach):
    for post_id in null_reach:
        result = evaluate_post(conn, post_id, current_day=7)
        notes = result["data_notes"]
        assert len(notes) == 1
        assert notes[0]["type"] == "reach_unavailable"
        assert notes[0]["source"] == "public"
        assert "reach" in notes[0]["note"].lower()


def test_no_data_note_when_reach_is_known(conn):
    """The negative case: a healthy snapshot with a real reach figure gets no
    data note at all — this is not a blanket disclaimer on every post."""
    result = evaluate_post(conn, UNDERPERFORMING_POST_ID, current_day=7)
    assert result["data_notes"] == []


def test_no_data_note_when_not_yet_posted(conn):
    """A deliverable with no snapshot at all (never posted) is rule_1's concern,
    not a data-availability note — the two must not be conflated."""
    result = evaluate_post(conn, 2, current_day=2)  # "not_posted" scenario, before rule_1's grace period
    assert result["data_notes"] == []
