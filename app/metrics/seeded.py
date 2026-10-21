"""The default provider for the demo campaign: scripts/seed.py already wrote
every post_snapshots row directly, so there is nothing to fetch. Exists so
campaigns.metrics_provider='seeded' has a named class to map to, matching
app/metrics/manual.py's role for 'manual' — both are deliberate no-ops on the
MetricsProvider interface; app/metrics/base.py's defaults already do this,
these subclasses just name it."""

from __future__ import annotations

from .base import MetricsProvider


class SeededProvider(MetricsProvider):
    name = "seeded"
