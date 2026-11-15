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
