from __future__ import annotations

import sqlite3
from typing import Iterator

from app.db import get_connection


def get_db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
