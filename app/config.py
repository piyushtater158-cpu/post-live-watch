"""Loads the single editable thresholds file. Nothing here hardcodes a number
that belongs in config/thresholds.yaml."""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "thresholds.yaml"


@functools.lru_cache(maxsize=1)
def load_thresholds() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def reload_thresholds() -> dict:
    """Clears the cache and reloads — used by tests and by an admin 'reload config' action."""
    load_thresholds.cache_clear()
    return load_thresholds()
