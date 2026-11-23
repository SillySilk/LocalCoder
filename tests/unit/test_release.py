import subprocess
import sys
import threading

import lc_launch


def test_closing_george_frees_the_model_unless_another_window_uses_it(tmp_path, monkeypatch):
    monkeypatch.setattr(lc_launch, "SESSIONS", tmp_path)
    freed = []
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lc_launch.register_session("m")
        (tmp_path / f"{other.pid}.model").write_text("m", encoding="utf-8")

        monkeypatch.setattr(lc_launch, "_released", threading.Lock())
        lc_launch.release_model("m", unload=freed.append)
        assert freed == []  # another George window still uses it

        other.kill()
        other.wait()
        lc_launch.register_session("m")
        monkeypatch.setattr(lc_launch, "_released", threading.Lock())
        lc_launch.release_model("m", unload=freed.append)
        assert freed == ["m"]
        assert not list(tmp_path.glob("*.model"))  # crashed window's file cleaned up too
    finally:
        other.kill()


def test_release_runs_once(tmp_path, monkeypatch):
    monkeypatch.setattr(lc_launch, "SESSIONS", tmp_path)
    monkeypatch.setattr(lc_launch, "_released", threading.Lock())
    freed = []
    lc_launch.release_model("m", unload=freed.append)
    lc_launch.release_model("m", unload=freed.append)
    assert freed == ["m"]
