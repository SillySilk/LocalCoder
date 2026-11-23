import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

@pytest.fixture(autouse=True)
def _keep_test_relays_out_of_the_real_log(tmp_path, monkeypatch):
    """Relays started by tests write to a throwaway log, not logs/relay.log."""
    if not __import__("os").environ.get("LC_RELAY_EVENTS"):
        monkeypatch.setenv("LC_RELAY_EVENTS", str(tmp_path / "relay-test.log"))
