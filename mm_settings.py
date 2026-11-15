"""Ollama settings: where models are saved, default memory size, and how
long models stay loaded.

Found on Ollama 0.40.16: the Ollama app keeps its own settings in
%LOCALAPPDATA%\\Ollama\\db.sqlite (what its Settings screen changes) and
passes them to Ollama when it starts, overriding Windows user settings for
the models folder. So the models folder and memory size are written there
(with Ollama closed), and "stay loaded" (not an app setting) is a Windows
user setting. Every change is checked against what Ollama reports it started
with."""

import ctypes
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

from lc_ollama import ollama_up
from mm_fit import free_space, human
from mm_store import APP_DB, app_setting, user_env

try:
    import winreg
except ImportError:  # not Windows
    winreg = None

KEYS = {"models_folder": "OLLAMA_MODELS", "memory": "OLLAMA_CONTEXT_LENGTH",
        "stay_loaded": "OLLAMA_KEEP_ALIVE"}
APP_COLUMNS = {"models_folder": "models", "memory": "context_length"}
DEFAULT_MODELS = Path.home() / ".ollama" / "models"
DEFAULT_STAY = "5m"
APP_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
SERVER_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"

MEMORY_CHOICES = [("4k", "4096"), ("8k", "8192"), ("16k", "16384"), ("32k", "32768"),
                  ("64k", "65536"), ("128k", "131072")]
STAY_CHOICES = [("5 min", "5m"), ("30 min", "30m"), ("2 hours", "2h"), ("forever", "-1")]


class SettingsError(Exception):
    """A settings failure described in plain words."""


def read():
    ctx = app_setting("context_length")
    return {
        "models_folder": app_setting("models") or user_env("OLLAMA_MODELS") or str(DEFAULT_MODELS),
        "memory": str(ctx) if ctx else user_env("OLLAMA_CONTEXT_LENGTH"),
        "stay_loaded": user_env("OLLAMA_KEEP_ALIVE"),
    }


def _write_env(name, value):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS) as k:
        if value is None:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x2, 5000,
                                             ctypes.byref(result))


def _write_app(column, value):
    if not APP_DB.exists():
        raise SettingsError("The Ollama app's settings file was not found. Open the Ollama app once, then try again.")
    con = sqlite3.connect(APP_DB)
    try:
        with con:
            con.execute(f"UPDATE settings SET {column} = ? WHERE id = 1", (value,))
    finally:
        con.close()


def write(key, value):
    """Save one setting. Ollama must be closed for app settings."""
    if key == "models_folder":
        _write_app("models", value or str(DEFAULT_MODELS))
    elif key == "memory":
        _write_app("context_length", int(value or 0))
    elif key == "stay_loaded":
        _write_env(KEYS[key], value)
    else:
        raise KeyError(key)


def stop_ollama():
    subprocess.run(["taskkill", "/IM", "ollama app.exe", "/F"], capture_output=True)
    subprocess.run(["taskkill", "/IM", "ollama.exe", "/F"], capture_output=True)
    for _ in range(30):
        if not ollama_up():
            time.sleep(1)  # let it release its files
            return
        time.sleep(0.5)
    raise SettingsError("Ollama would not close. Close it from the tray icon and try again.")


def start_ollama_fresh():
    """Start the Ollama app with the current Windows user settings (this
    program's own copy of them is from when it started)."""
    if not APP_EXE.exists():
        raise SettingsError(f"The Ollama app was not found at {APP_EXE}.")
    env = dict(os.environ)
    for name in KEYS.values():
        value = user_env(name)
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    subprocess.Popen([str(APP_EXE)], env=env)
    for _ in range(60):
        if ollama_up():
            return
        time.sleep(0.5)
    raise SettingsError("Ollama did not start again. Open the Ollama app from the Start menu.")


def restart_ollama():
    stop_ollama()
    start_ollama_fresh()


_ENTRY = re.compile(r"([A-Z][A-Z0-9_]+):(.*?)(?= [A-Z][A-Z0-9_]+:|$)")


def server_config(after):
    """What Ollama last reported it started with, from a start after `after`
    (seconds since 1970). Waits up to 30 seconds for that start."""
    deadline = time.time() + 30
    while True:
        lines = []
        if SERVER_LOG.exists():
            lines = [l for l in SERVER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                     if 'msg="server config"' in l]
        if lines:
            line = lines[-1]
            stamp = re.search(r"time=(\S+)", line)
            when = datetime.fromisoformat(stamp.group(1)).timestamp() if stamp else 0
            body = re.search(r'env="map\[(.*)\]"', line)
            if body and when >= after - 1:
                return {k: v.replace("\\\\", "\\") for k, v in _ENTRY.findall(body.group(1))}
        if time.time() > deadline:
            raise SettingsError("Could not tell whether Ollama picked up the change (no new start in its log).")
        time.sleep(0.5)


def duration_seconds(text):
    text = (text or "").strip()
    if text.startswith("-"):
        return -1
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    units = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}
    parts = re.findall(r"([\d.]+)(ms|h|m|s)", text)
    return sum(float(n) * units[u] for n, u in parts)


def _took(key, value, cfg):
    got = cfg.get(KEYS[key], "")
    if key == "models_folder":
        return Path(got) == Path(value or DEFAULT_MODELS)
    if key == "memory":
        return got == str(int(value or 0))
    want = duration_seconds(value or DEFAULT_STAY)
    have = duration_seconds(got)
    return have == want or (want < 0 and have > 10**9)  # Go prints "forever" as a huge time


def apply(key, value):
    """Save a setting, restart Ollama, and return True if Ollama is using it."""
    started = time.time()
    stop_ollama()
    try:
        write(key, value)
    finally:
        start_ollama_fresh()
    return _took(key, value, server_config(started))


def folder_size(folder):
    return sum(p.stat().st_size for p in Path(folder).rglob("*") if p.is_file())


MODEL_PARTS = ("blobs", "manifests", "manifests-v2")


def check_folder(folder):
    """A usable folder for models: a full path on a drive that exists."""
    folder = Path(folder)
    if not folder.is_absolute():
        raise SettingsError(f"Please type a full path, starting with a drive letter (e.g. D:\Ollama models), not {folder}.")
    if not Path(folder.anchor).exists():
        raise SettingsError(f"There's no drive {folder.drive} on this PC.")
    return folder


def _inside(child, parent):
    child, parent = Path(child).resolve(), Path(parent).resolve()
    return child == parent or parent in child.parents


def change_models_folder(src, dst, move, on_progress):
    """Check everything first, then (optionally) move the models and switch
    Ollama to dst. Returns True if Ollama is using dst."""
    dst = check_folder(dst)
    if move and _inside(dst, src):
        raise SettingsError("The new folder can't be inside the current models folder.")
    if not APP_DB.exists():
        raise SettingsError("The Ollama app's settings file was not found, so the folder can't be changed. "
                            "Open the Ollama app once, then try again.")
    if not APP_EXE.exists():
        raise SettingsError(f"The Ollama app was not found at {APP_EXE}.")
    if move:
        stop_ollama()
        try:
            move_models(src, dst, on_progress)
        finally:
            start_ollama_fresh()  # back on the old folder if the move failed
    dst.mkdir(parents=True, exist_ok=True)
    return apply("models_folder", str(dst))


def move_models(src, dst, on_progress):
    """Move Ollama's model files from src to dst. Ollama must be closed.
    on_progress(done_bytes, total_bytes)."""
    src, dst = Path(src), Path(dst)
    if _inside(dst, src):
        raise SettingsError("The new folder can't be inside the current models folder.")
    files = [p for part in MODEL_PARTS if (src / part).is_dir()
             for p in (src / part).rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    free = free_space(dst)
    if free < total:
        raise SettingsError(f"There's not enough space in {dst}: it needs {human(total)}, "
                            f"and {human(free)} is free.")
    done = moved = 0
    try:
        for p in files:
            target = dst / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            size = p.stat().st_size
            shutil.move(str(p), str(target))
            moved += 1
            done += size
            on_progress(done, total)
    except (KeyboardInterrupt, OSError) as e:
        why = "you stopped it" if isinstance(e, KeyboardInterrupt) else str(e)
        raise SettingsError(f"The move stopped partway ({why}): {moved} of {len(files)} files are now in "
                            f"{dst}, the rest are still in {src}. Ollama is still using {src}. "
                            "Run the same move again to finish it.") from None
    for part in MODEL_PARTS:
        if (src / part).is_dir():
            shutil.rmtree(src / part)
