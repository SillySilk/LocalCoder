"""Where Ollama keeps models on disk, and what deleting some would free."""

import json
import os
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


def models_dir():
    folder = user_env("OLLAMA_MODELS") or os.environ.get("OLLAMA_MODELS")
    return Path(folder) if folder else Path.home() / ".ollama" / "models"


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
    return {"freed": freed, "shared_with": sorted(others)}
