import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before app.db is first imported anywhere, so the test suite
# never touches the real seeded dashboard DB.
TEST_DB = Path(__file__).resolve().parent / "test_postlivewatch.db"
os.environ["POST_LIVE_WATCH_DB"] = str(TEST_DB)

import pytest  # noqa: E402

from app.db import get_connection  # noqa: E402
from scripts.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    seed(reset=True)
    yield TEST_DB
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture
def conn(seeded_db):
    c = get_connection()
    yield c
    c.close()
