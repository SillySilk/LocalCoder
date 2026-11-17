import subprocess
import sys
import threading

import lc_launch
import lc_ollama


def _loaded(name):
    return lc_ollama.canonical(name) in {lc_ollama.canonical(m["name"]) for m in lc_ollama.running()}


def _load(name):
    lc_ollama.call("/api/generate", {"model": name, "keep_alive": "10m"}, timeout=300)


def test_closing_george_frees_the_model_unless_another_window_uses_it(tiny_model, tmp_path, monkeypatch):
    monkeypatch.setattr(lc_launch, "SESSIONS", tmp_path)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _load(tiny_model)
        lc_launch.register_session(tiny_model)
        (tmp_path / f"{other.pid}.model").write_text(tiny_model, encoding="utf-8")

        monkeypatch.setattr(lc_launch, "_released", threading.Lock())
        lc_launch.release_model(tiny_model)
        assert _loaded(tiny_model), "unloaded while another George window still uses it"
        assert not (tmp_path / f"{lc_launch.os.getpid()}.model").exists()

        other.kill()
        other.wait()
        monkeypatch.setattr(lc_launch, "_released", threading.Lock())
        lc_launch.release_model(tiny_model)
        assert not _loaded(tiny_model), "model still loaded after the last George window closed"
        assert not (tmp_path / f"{other.pid}.model").exists(), "crashed window's file not cleaned up"
    finally:
        other.kill()
        lc_ollama.unload(tiny_model)
