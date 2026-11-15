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
