import os
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parent

sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(REPO_ROOT / "fixtures"))

from server import FixtureServer  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def plugin_cwd():
    """Dify resolves every manifest path against the process cwd."""
    previous = Path.cwd()
    os.chdir(PLUGIN_ROOT)
    yield PLUGIN_ROOT
    os.chdir(previous)


@pytest.fixture(scope="session")
def base_url():
    with FixtureServer() as server:
        yield server.base_url
