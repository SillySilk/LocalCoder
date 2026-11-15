import subprocess
import sys
import time

import pytest

import lc_ollama
from lc_ollama import OllamaError, call, canonical, installed, pull, running, unload
from conftest import ROOT


def test_canonical():
    assert canonical("a") == "a:latest"
    assert canonical("a:8b") == "a:8b"
    assert canonical("hf.co/u/r:Q4_K_M") == "hf.co/u/r:Q4_K_M"


def test_pull_reports_progress(tiny_model):
    assert canonical(tiny_model) in [m["name"] for m in installed()]
    seen = []
    pull(tiny_model, lambda status, done, total: seen.append((status, done, total)))
    assert seen[-1][0] == "success"
    assert any(total > 0 for _, _, total in seen)


def test_unload(tiny_model):
    call("/api/generate", {"model": tiny_model, "prompt": "hi", "stream": False}, timeout=120)
    assert tiny_model in [m["name"] for m in running()]
    unload(tiny_model)
    deadline = time.time() + 10
    while time.time() < deadline and tiny_model in [m["name"] for m in running()]:
        time.sleep(0.5)
    assert tiny_model not in [m["name"] for m in running()]


def test_call_bad_model_raises():
    with pytest.raises(OllamaError, match="not found"):
        call("/api/show", {"model": "no-such-model-mm"})


def test_george_still_starts():
    r = subprocess.run([sys.executable, "lc_launch.py", "--help"], cwd=ROOT,
                       capture_output=True)
    assert r.returncode == 0


def test_call_restarts_once(monkeypatch):
    starts = []
    monkeypatch.setattr(lc_ollama, "OLLAMA", "http://127.0.0.1:1")
    monkeypatch.setattr(lc_ollama, "start_ollama", lambda: starts.append(1))
    with pytest.raises(OllamaError, match="Ollama stopped"):
        call("/api/version")
    assert len(starts) == 1
