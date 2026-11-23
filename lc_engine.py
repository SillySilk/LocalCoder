"""George's link to the shared AI engine run by Engine Manager.

Engine Manager (C:\\AI\\EngineManager, or LC_ENGINE_MANAGER) owns the engine,
its model list and its settings. George only reads them, starts the engine
when it isn't running, and frees the model when it's done.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

MANAGER = Path(os.environ.get("LC_ENGINE_MANAGER") or r"C:\AI\EngineManager")
sys.path.insert(0, str(MANAGER))

try:
    import em_engine as eng  # noqa: E402
except ImportError:
    sys.exit(f"Engine Manager not found at {MANAGER}. Set LC_ENGINE_MANAGER to its folder.")

EngineError = eng.EngineError


def settings():
    return eng.load_settings()


def url(path=""):
    return eng.engine_url(None, path)


def start_engine(wait=90):
    """Make sure the engine is running. Starts Engine Manager quietly if needed,
    so its page is available too."""
    if eng.running():
        return
    pyw = Path(sys.executable).with_name("pythonw.exe")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(MANAGER / "engine_manager.py"), "--background"],
                     cwd=str(MANAGER), creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if eng.running():
            return
        time.sleep(0.5)
    sys.exit(f"The engine didn't start. Open Engine Manager to see why (log: {eng.LOG_FILE}).")


def models():
    """[{name, size, ctx, vision, default}] from the engine's list, default first."""
    s = settings()
    disk = {d["name"]: d for d in eng.scan(s["models_dir"])}
    out = []
    for m in eng.engine_models(s):
        d = disk.get(m["id"], {})
        out.append({
            "name": m["id"],
            "size": d.get("size", 0),
            "ctx": int((s["models"].get(m["id"]) or {}).get("ctx") or s["default_ctx"]),
            "vision": "image" in ((m.get("architecture") or {}).get("input_modalities") or []),
            "default": m["id"] == s["default_model"],
            "state": (m.get("status") or {}).get("value", "unloaded"),
        })
    return sorted(out, key=lambda f: (not f["default"], f["name"].lower()))


def find(name):
    for f in models():
        if f["name"] == name:
            return f
    return None


def unload(name):
    try:
        eng.unload(name)
    except EngineError:
        pass  # engine gone or model already unloaded
