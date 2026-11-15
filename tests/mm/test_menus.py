import os
import subprocess
from pathlib import Path
import sys

import mm
from conftest import ROOT


def feed(monkeypatch, answers):
    it = iter(answers)

    def fake_input(prompt=""):
        a = next(it)
        if isinstance(a, BaseException):
            raise a
        return a

    monkeypatch.setattr("builtins.input", fake_input)


def test_ask_number_reasks(monkeypatch):
    feed(monkeypatch, ["x", "9", "", "2"])
    assert mm.ask_number("Pick", 3, None) == 2


def test_ask_number_default(monkeypatch):
    feed(monkeypatch, [""])
    assert mm.ask_number("Pick", 3, 1) == 1
    feed(monkeypatch, ["0"])
    assert mm.ask_number("Pick", 3, 1) is None


def test_ask_yes(monkeypatch):
    feed(monkeypatch, ["maybe", "Y"])
    assert mm.ask_yes("Sure?") is True
    feed(monkeypatch, [""])
    assert mm.ask_yes("Sure?") is False


def test_parse_picks():
    assert mm.parse_picks("1, 3", 4) == [1, 3]
    assert mm.parse_picks("2", 4) == [2]
    assert mm.parse_picks("5", 4) is None
    assert mm.parse_picks("a", 4) is None


def test_ctrl_c_on_main_menu_exits(monkeypatch):
    feed(monkeypatch, [KeyboardInterrupt()])
    mm.main()  # returns, no traceback


def test_ctrl_c_in_a_screen_goes_back(monkeypatch):
    feed(monkeypatch, ["3", KeyboardInterrupt(), "0"])
    mm.main()


def test_launcher_runs():
    r = subprocess.run(["cmd", "/c", str(ROOT / "ModelManager.bat")], cwd=ROOT, input="0\n",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "===== Model Manager =====" in r.stdout


def test_ask_ignores_invisible_start(monkeypatch):
    feed(monkeypatch, ["﻿0"])
    assert mm.ask_number("Pick", 3, None) is None


def test_my_models_prints_in_old_windows_encoding(tiny_model):
    r = subprocess.run([sys.executable, "mm.py"], cwd=ROOT, input=b"1\n\n0\n", capture_output=True,
                       timeout=60, env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    assert b"Traceback" not in r.stderr


def test_search_hides_models_that_cannot_run(monkeypatch):
    big = [{"quant": "Q4_K_M", "size": 18 * 10**9, "split": False}]
    ok = [{"quant": "Q3_K_M", "size": 13 * 10**9, "split": False},
          {"quant": "Q4_K_M", "size": 16.5 * 10**9, "split": False}]
    results = [{"repo": "a/too-big"}, {"repo": "b/tight-ok"}]
    shown = mm.runnable_results(results, {"a/too-big": big, "b/tight-ok": ok}, 16 * 1024**3)
    assert [r["repo"] for r in shown] == ["b/tight-ok"]
    assert shown[0]["best"]["quant"] == "Q3_K_M"  # largest that fits; 16.5 GB is only "tight"


def test_search_finds_tiny_and_marks_best(monkeypatch, capsys):
    mm.VRAM = 16380 * 1024**2
    feed(monkeypatch, ["SmolLM2-135M-Instruct", "0"])
    mm.search_screen()
    out = capsys.readouterr().out
    assert "bartowski/SmolLM2-135M-Instruct-GGUF" in out and "best fit" in out


def test_hidden_count_only_counts_too_big(monkeypatch, capsys):
    mm.VRAM = 16380 * 1024**2
    found = [{"repo": f"r/{i}", "downloads": 1, "updated": "2026-01-01", "gated": False} for i in range(25)]
    sizes = {f"r/{i}": [{"quant": "Q4_K_M", "size": (5 if i < 22 else 30) * 10**9, "split": False, "files": ["x"]}]
             for i in range(25)}
    monkeypatch.setattr(mm, "search", lambda w, limit=40: found)
    monkeypatch.setattr(mm, "_sizes_for", lambda repos: sizes)
    feed(monkeypatch, ["x", "0"])
    mm.search_screen()
    out = capsys.readouterr().out
    assert "3 hidden" in out and "2 more" in out


def test_ask_number_rejects_superscript(monkeypatch):
    feed(monkeypatch, ["²", "1"])
    assert mm.ask_number("Pick", 3, None) == 1


def test_ctrl_c_during_startup(monkeypatch):
    def stop():
        raise KeyboardInterrupt
    monkeypatch.setattr(mm, "start_ollama", stop)
    mm.main()


def test_fallback_checks_downloads_space(monkeypatch, capsys):
    from lc_ollama import OllamaError
    called = []

    def fail(*a):
        raise OllamaError("server busy")

    monkeypatch.setattr(mm, "have", lambda n: False)
    monkeypatch.setattr(mm, "pull", fail)
    monkeypatch.setattr(mm, "free_space", lambda p: 0 if "Downloads" in str(p) else 10**12)
    monkeypatch.setattr(mm, "download_file", lambda *a: called.append("download"))
    monkeypatch.setattr(mm, "import_gguf", lambda *a: called.append("import"))
    feed(monkeypatch, ["y"])
    mm.download_model("hf.co/u/r:Q4", 5 * 10**9, hf=("u/r", ["r-Q4.gguf"]))
    assert called == [] and "Not enough disk space" in capsys.readouterr().out


def _delete_screen_output(monkeypatch, capsys, shared_bytes):
    monkeypatch.setattr(mm, "installed", lambda: [{"name": "a:latest", "size": 10}])
    monkeypatch.setattr(mm, "delete_plan", lambda names: {"freed": 10, "shared_with": ["b:latest"],
                                                          "shared_bytes": shared_bytes})
    feed(monkeypatch, ["1", "n"])
    mm.delete_screen()
    return capsys.readouterr().out


def test_shared_note_only_when_it_matters(monkeypatch, capsys):
    assert "share" not in _delete_screen_output(monkeypatch, capsys, 50_000)
    assert "share 2.0 GB with" in _delete_screen_output(monkeypatch, capsys, 2 * 10**9)


def test_nonstandard_size_name_is_refused_by_ollama():
    """Real check of the message the automatic switch relies on."""
    import pytest as _pt
    from lc_ollama import OllamaError, pull
    with _pt.raises(OllamaError, match="not a valid quantization scheme"):
        pull("hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K", lambda *a: None)


def test_nonstandard_size_name_goes_straight_to_direct(monkeypatch, capsys):
    from lc_ollama import OllamaError
    got = []

    def refuse(*a):
        raise OllamaError('pull model manifest: 400: {"error":"The specified tag is not a valid '
                          'quantization scheme. Please use another tag or \\"latest\\""}')

    monkeypatch.setattr(mm, "have", lambda n: False)
    monkeypatch.setattr(mm, "pull", refuse)
    monkeypatch.setattr(mm, "free_space", lambda p: 10**12)
    monkeypatch.setattr(mm, "download_file", lambda *a: got.append("download") or Path("C:/x/m-Q4_K.gguf"))
    monkeypatch.setattr(mm, "free_name", lambda n: n)
    monkeypatch.setattr(mm, "import_gguf", lambda *a: got.append("import") or "m-q4_k:latest")
    monkeypatch.setattr(mm, "tool_check", lambda *a: got.append("check"))
    feed(monkeypatch, [])  # no questions: switching to the direct download is automatic here
    mm.download_model("hf.co/u/r:Q4_K", 5 * 10**9, hf=("u/r", ["m-Q4_K.gguf"]))
    assert got == ["download", "import", "check"]
    assert "downloading the file directly" in capsys.readouterr().out
