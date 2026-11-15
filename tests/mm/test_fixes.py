"""Tests for the final-review fixes."""

import os
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


# Found while renaming the folder: Ollama started from a project folder keeps it locked
def test_ollama_is_started_from_home(monkeypatch):
    import lc_ollama
    seen, hidden = [], []

    class FakePopen:
        def __init__(self, args, **kw):
            seen.append(kw.get("cwd"))
            if "ollama app" in str(args[0]):
                hidden.append("--hide" in args)

    ups = iter([False, True])
    monkeypatch.setattr(lc_ollama, "ollama_up", lambda: next(ups))
    monkeypatch.setattr(lc_ollama.subprocess, "Popen", FakePopen)
    lc_ollama.start_ollama()
    ups2 = iter([True])
    monkeypatch.setattr(mm_settings, "ollama_up", lambda: next(ups2))
    monkeypatch.setattr(mm_settings.subprocess, "Popen", FakePopen)
    mm_settings.start_ollama_fresh()
    assert seen == [str(Path.home()), str(Path.home())]
    assert hidden and all(hidden)  # tray only, no window popping up


# Polish Task 5
def test_same_volume_letter_case():
    assert mm_settings.same_volume(Path("c:/Windows"), Path("C:/Users/new-folder")) is True
    if Path("D:/").exists():
        assert mm_settings.same_volume(Path("C:/Windows"), Path("D:/new-folder")) is False


def test_same_drive_move_needs_no_space(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "blobs").mkdir(parents=True)
    (src / "blobs" / "a").write_bytes(b"x" * 100)
    monkeypatch.setattr(mm_settings, "free_space", lambda p: 0)
    move_models(src, dst, lambda d, t: None)
    assert (dst / "blobs" / "a").exists()


def test_read_order(monkeypatch):
    import mm_store
    monkeypatch.setattr(mm_store, "app_setting", lambda c: None)
    monkeypatch.setattr(mm_settings, "app_setting", lambda c: None)
    monkeypatch.setattr(mm_store, "user_env", lambda k: None)
    monkeypatch.setattr(mm_store, "system_env", lambda k: "D:\m" if k == "OLLAMA_MODELS" else None)
    assert mm_settings.read()["models_folder"] == "D:\m"
    assert str(mm_store.models_dir()) == "D:\m"
    monkeypatch.setattr(mm_store, "app_setting", lambda c: "E:\n" if c == "models" else None)
    assert mm_settings.read()["models_folder"] == "E:\n"


def test_app_setting_odd_path(tmp_path, monkeypatch):
    import shutil
    import mm_store
    real = mm_store.app_setting("models")
    odd = tmp_path / "a#b"
    odd.mkdir()
    shutil.copy(mm_store.APP_DB, odd / "db.sqlite")
    monkeypatch.setattr(mm_store, "APP_DB", odd / "db.sqlite")
    assert mm_store.app_setting("models") == real


# Polish final review
def test_throttle_shows_each_step():
    from mm_import import Throttle
    calls = []
    t = Throttle(lambda step, d, tot: calls.append(step), every_bytes=1 << 20)
    for step in ("Checking file", "Copying into Ollama"):
        for i in range(1, 101):
            t(step, i * (1 << 20) // 2, 50 * (1 << 20))
    assert calls.count("Copying into Ollama") > 10


@pytest.mark.skipif(not Path("D:/").exists(), reason="needs a second drive")
def test_same_volume_sees_through_junctions(tmp_path):
    import shutil
    import subprocess
    import uuid
    target = Path("D:/") / f"mm-junction-test-{uuid.uuid4().hex[:8]}"
    target.mkdir()
    link = tmp_path / "link"
    try:
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
        assert mm_settings.same_volume(tmp_path, tmp_path / "new") is True
        assert mm_settings.same_volume(link, tmp_path / "new") is False
    finally:
        if link.exists():
            os.rmdir(link)
        shutil.rmtree(target)


def test_restart_keeps_all_users_setting(monkeypatch):
    seen = {}

    class FakePopen:
        def __init__(self, args, env=None, **kw):
            seen.update(env or {})

    monkeypatch.setattr(mm_settings, "user_env", lambda k: None)
    monkeypatch.setattr(mm_settings.mm_store, "system_env", lambda k: "D:\m" if k == "OLLAMA_MODELS" else None)
    monkeypatch.setattr(mm_settings.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(mm_settings, "ollama_up", lambda: True)
    mm_settings.start_ollama_fresh()
    assert seen.get("OLLAMA_MODELS") == "D:\m"
