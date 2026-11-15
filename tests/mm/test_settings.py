import os
import tempfile
from pathlib import Path

import pytest

import mm_settings
from lc_ollama import installed
from mm_settings import apply, duration_seconds, move_models, read, server_config


def test_duration_seconds():
    assert duration_seconds("30m") == 1800
    assert duration_seconds("30m0s") == 1800
    assert duration_seconds("2h0m0s") == 7200
    assert duration_seconds("5m0s") == 300
    assert duration_seconds("-1") < 0
    assert duration_seconds("2562047h47m16.854775807s") > 10**9  # how Go prints "forever"


def test_apply_stay_loaded():
    saved = read()["stay_loaded"]
    try:
        assert apply("stay_loaded", "30m") is True
        assert duration_seconds(server_config(0)["OLLAMA_KEEP_ALIVE"]) == 1800
    finally:
        assert apply("stay_loaded", saved) is True


def test_apply_memory():
    saved = read()["memory"]
    try:
        assert apply("memory", "16384") is True
        assert server_config(0)["OLLAMA_CONTEXT_LENGTH"] == "16384"
    finally:
        assert apply("memory", saved) is True


def test_apply_models_folder():
    saved = read()["models_folder"]
    count = len(installed())
    probe = Path(tempfile.mkdtemp(prefix="mm-models-"))
    try:
        assert apply("models_folder", str(probe)) is True
        assert installed() == []
    finally:
        assert apply("models_folder", saved) is True
    assert len(installed()) == count


def test_move_models_refuses_when_full(tmp_path, monkeypatch):
    src = tmp_path / "src"
    (src / "blobs").mkdir(parents=True)
    (src / "blobs" / "a").write_bytes(b"x" * 100)
    monkeypatch.setattr(mm_settings, "free_space", lambda p: 0)
    monkeypatch.setattr(mm_settings, "same_drive", lambda a, b: False)  # a move to another drive copies
    with pytest.raises(mm_settings.SettingsError, match="not enough space"):
        move_models(src, tmp_path / "dst", lambda d, t: None)
    assert (src / "blobs" / "a").exists()


def test_move_models_moves(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "blobs").mkdir(parents=True)
    (src / "manifests" / "x").mkdir(parents=True)
    (src / "blobs" / "a").write_bytes(b"x" * 100)
    (src / "manifests" / "x" / "m").write_text("{}")
    move_models(src, dst, lambda d, t: None)
    assert (dst / "blobs" / "a").read_bytes() == b"x" * 100
    assert (dst / "manifests" / "x" / "m").exists()
    assert not (src / "blobs").exists()
