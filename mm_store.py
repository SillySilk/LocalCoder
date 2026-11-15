"""Where Ollama keeps models on disk, and what deleting some would free."""

import json
import os
import sqlite3
from pathlib import Path

from lc_ollama import canonical, installed

try:
    import winreg
except ImportError:  # not Windows
    winreg = None


def user_env(key):
    """A Windows user setting (HKCU\\Environment), or None."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, key)[0] or None
    except OSError:
        return None


APP_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "db.sqlite"


def app_setting(column):
    """A value from the Ollama app's own settings (what its Settings screen
    changes), or None. The app passes these to Ollama when it starts, and they
    win over Windows user settings."""
    if not APP_DB.exists():
        return None
    try:
        con = sqlite3.connect(APP_DB.as_uri() + "?mode=ro", uri=True)
        try:
            row = con.execute(f"SELECT {column} FROM settings WHERE id = 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def system_env(key):
    """A Windows setting for all users on this PC, or None."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as k:
            return winreg.QueryValueEx(k, key)[0] or None
    except OSError:
        return None


def models_folder():
    """Where Ollama keeps models, in the order Ollama itself uses: the Ollama
    app's setting, then this user's Windows setting, then the all-users one,
    then the default."""
    return (app_setting("models") or user_env("OLLAMA_MODELS") or system_env("OLLAMA_MODELS")
            or str(Path.home() / ".ollama" / "models"))


def models_dir():
    return Path(models_folder())


def manifest_candidates(name):
    """Where a model's manifest can be. Ollama 0.40 writes new models under
    manifests-v2 (library host ollama.com) and keeps older ones under
    manifests (library host registry.ollama.ai)."""
    repo, tag = canonical(name).rsplit(":", 1)
    parts = repo.split("/")
    if len(parts) > 1 and "." in parts[0]:  # has a host, e.g. hf.co
        return [models_dir().joinpath(d, *parts, tag) for d in ("manifests-v2", "manifests")]
    rest = (["library"] if len(parts) == 1 else []) + parts
    return [models_dir().joinpath("manifests-v2", "ollama.com", *rest, tag),
            models_dir().joinpath("manifests", "registry.ollama.ai", *rest, tag)]


def manifest_path(name):
    cands = manifest_candidates(name)
    return next((p for p in cands if p.exists()), cands[0])


def layers(name):
    m = json.loads(manifest_path(name).read_text(encoding="utf-8"))
    out = {m["config"]["digest"]: m["config"]["size"]}
    out.update({layer["digest"]: layer["size"] for layer in m.get("layers", [])})
    return out


def delete_plan(names):
    targets = {canonical(n) for n in names}
    mine = {}
    for n in targets:
        mine.update(layers(n))
    others = {}
    for m in installed():
        other = canonical(m["name"])
        if other in targets:
            continue
        try:
            shared = layers(other).keys() & mine.keys()
        except OSError:
            continue
        if shared:
            others[other] = shared
    still_used = set().union(*others.values()) if others else set()
    freed = sum(size for d, size in mine.items() if d not in still_used)
    shared = sum(size for d, size in mine.items() if d in still_used)
    return {"freed": freed, "shared_with": sorted(others), "shared_bytes": shared}
