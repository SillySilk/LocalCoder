import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import lc_ollama  # noqa: E402

TINY = "hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M"


@pytest.fixture(scope="session")
def tiny_model():
    lc_ollama.start_ollama()
    have = {m["name"] for m in lc_ollama.installed()}
    pulled = TINY not in have
    if pulled:
        lc_ollama.pull(TINY, lambda *a: None)
    yield TINY
    if pulled:
        lc_ollama.delete(TINY)


@pytest.fixture(autouse=True)
def _keep_test_relays_out_of_the_real_log(tmp_path, monkeypatch):
    """Relays started by tests write to a throwaway log, not logs/relay.log."""
    if not __import__("os").environ.get("LC_RELAY_EVENTS"):
        monkeypatch.setenv("LC_RELAY_EVENTS", str(tmp_path / "relay-test.log"))
