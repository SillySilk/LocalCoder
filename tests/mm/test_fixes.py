"""Tests for the final-review fixes."""

from pathlib import Path

import pytest

import mm
import mm_import
import mm_settings
from mm_settings import SettingsError, check_folder, move_models


def feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


# Critical 1: destination inside the models folder
def test_move_refuses_destination_inside_models(tmp_path):
    src = tmp_path / "models"
    (src / "blobs").mkdir(parents=True)
    (src / "blobs" / "a").write_bytes(b"x" * 10)
    for dst in (src / "blobs" / "new", src / "inner"):
        with pytest.raises(SettingsError, match="inside"):
            move_models(src, dst, lambda d, t: None)
    assert (src / "blobs" / "a").read_bytes() == b"x" * 10


# Important 3: relative or missing-drive folders
def test_check_folder_needs_full_path(tmp_path):
    with pytest.raises(SettingsError, match="full path"):
        check_folder(Path("models"))
    with pytest.raises(SettingsError, match="drive"):
        check_folder(Path("Q:/ollama-models"))
    assert check_folder(tmp_path / "new") == (tmp_path / "new")


# Important 4: nothing is stopped or moved when Ollama's settings file is missing
def test_change_models_folder_checks_before_moving(tmp_path, monkeypatch):
    src = tmp_path / "src"
    (src / "blobs").mkdir(parents=True)
    (src / "blobs" / "a").write_bytes(b"x")
    stops = []
    monkeypatch.setattr(mm_settings, "APP_DB", tmp_path / "missing.sqlite")
    monkeypatch.setattr(mm_settings, "stop_ollama", lambda: stops.append(1))
    with pytest.raises(SettingsError, match="settings file"):
        mm_settings.change_models_folder(src, tmp_path / "dst", True, lambda d, t: None)
    assert stops == []
    assert (src / "blobs" / "a").exists()


def test_interrupted_move_says_so(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "blobs").mkdir(parents=True)
    for n in "abc":
        (src / "blobs" / n).write_bytes(b"x")

    def boom(done, total):
        raise KeyboardInterrupt

    with pytest.raises(SettingsError, match="stopped partway"):
        move_models(src, dst, boom)


# Important 1: Enter keeps the model; models that were already there are never offered for deletion
def test_tool_check_enter_keeps(monkeypatch):
    deleted = []
    monkeypatch.setattr(mm, "fix_tools", lambda n: None)
    monkeypatch.setattr(mm, "missing_family_hint", lambda n: "hint")
    monkeypatch.setattr(mm, "delete", deleted.append)
    feed(monkeypatch, [""])
    mm.tool_check("x:latest", existed_before=False)
    assert deleted == []


def test_tool_check_never_offers_to_delete_existing(monkeypatch):
    deleted = []
    monkeypatch.setattr(mm, "fix_tools", lambda n: None)
    monkeypatch.setattr(mm, "missing_family_hint", lambda n: "hint")
    monkeypatch.setattr(mm, "delete", deleted.append)
    feed(monkeypatch, [])  # any question would raise StopIteration
    mm.tool_check("x:latest", existed_before=True)
    assert deleted == []


def test_import_asks_before_replacing(monkeypatch):
    monkeypatch.setattr(mm, "installed", lambda: [{"name": "taken:latest"}])
    feed(monkeypatch, ["n", "other"])
    assert mm.free_name("taken") == "other"
    feed(monkeypatch, ["y"])
    assert mm.free_name("taken") == "taken"


# Important 2: unexpected errors are a plain message, not a crash
def test_unexpected_error_is_plain(monkeypatch, capsys):
    monkeypatch.setattr(mm, "start_ollama", lambda: None)
    monkeypatch.setattr(mm, "graphics_memory", lambda: None)
    monkeypatch.setattr(mm, "header", lambda: "===== Model Manager =====")

    def broken():
        raise FileNotFoundError("manifest missing")

    monkeypatch.setitem(mm.SCREENS, 1, broken)
    monkeypatch.setattr(mm, "ERROR_LOG", Path(mm.__file__).parent / "tests" / "logs" / "mm-test-errors.log")
    feed(monkeypatch, ["1", "0"])
    mm.main()
    out = capsys.readouterr().out
    assert "Something went wrong" in out and "manifest missing" in out


# Important 5: only copy a chat format from a model with the same tokenizer
def test_fix_tools_needs_same_tokenizer(monkeypatch):
    facts = {
        "bad:latest": {"tools": False, "arch": "llama", "tokenizer": "smollm"},
        "llama31:latest": {"tools": True, "arch": "llama", "tokenizer": "llama-bpe"},
    }
    monkeypatch.setattr(mm_import, "facts", lambda n: facts[n])
    monkeypatch.setattr(mm_import, "installed", lambda: [{"name": n} for n in facts])
    created = []
    monkeypatch.setattr(mm_import, "call", lambda path, body=None, **k: created.append(body) or {})
    assert mm_import.fix_tools("bad:latest") is None
    assert created == []
