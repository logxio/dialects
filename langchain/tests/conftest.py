import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "fixtures"))

from server import FixtureServer  # noqa: E402


@pytest.fixture(scope="session")
def base_url():
    with FixtureServer() as server:
        yield server.base_url
