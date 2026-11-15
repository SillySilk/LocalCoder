import os
import subprocess
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
