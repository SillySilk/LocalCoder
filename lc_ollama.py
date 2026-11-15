"""Talking to Ollama's local API. Shared by George (lc_launch.py) and
Model Manager (mm.py)."""

import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA = os.environ.get("LC_OLLAMA_URL", "http://127.0.0.1:11434")


class OllamaError(Exception):
    """A failure described in plain words."""


def api(path, body=None, base=None, timeout=30, method=None):
    base = base or OLLAMA
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def ollama_up():
    try:
        api("/api/version", timeout=3)
        return True
    except OSError:
        return False


def start_ollama():
    if ollama_up():
        return
    exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
    print("Starting Ollama...")
    if exe.exists():
        os.startfile(str(exe))  # noqa: S606 - Windows only, launches the Ollama tray app
    else:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if ollama_up():
            return
        time.sleep(1)
    sys.exit("Ollama did not start. Open the Ollama app and try again.")


def _http_message(e):
    try:
        text = json.loads(e.read() or b"{}").get("error", "")
    except ValueError:
        text = ""
    return text or f"Ollama said {e.code} {e.reason}"


def _refused(e):
    return isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError)


def call(path, body=None, method=None, timeout=30):
    """Like api(), but restarts Ollama once if it has stopped, and turns
    errors into OllamaError with plain words."""
    for attempt in (1, 2):
        try:
            return api(path, body, base=OLLAMA, timeout=timeout, method=method)
        except urllib.error.HTTPError as e:
            raise OllamaError(_http_message(e)) from None
        except (urllib.error.URLError, ConnectionError) as e:
            if attempt == 2:
                raise OllamaError("Ollama stopped and could not be restarted. "
                                  "Open the Ollama app and try again.") from e
            print("Ollama stopped. Restarting it...")
            start_ollama()
    raise AssertionError("unreachable")


def model_facts(name):
    """What LocalCoder needs to know about one installed model."""
    return _facts(name, api("/api/show", {"model": name}))


def facts(name):
    """model_facts, but restarts Ollama if needed and raises OllamaError."""
    return _facts(name, call("/api/show", {"model": name}))


def _facts(name, d):
    caps = d.get("capabilities") or []
    num_ctx = None
    for line in (d.get("parameters") or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "num_ctx":
            num_ctx = int(parts[1])
    info = d.get("model_info") or {}
    arch = info.get("general.architecture", "")
    max_ctx = info.get(f"{arch}.context_length")
    det = d.get("details") or {}
    return {
        "name": name,
        "tools": "tools" in caps,
        "thinking": "thinking" in caps,
        "vision": "vision" in caps,
        "embedding_only": caps == ["embedding"],
        "num_ctx": num_ctx,
        "max_ctx": int(max_ctx) if max_ctx else None,
        "quant": det.get("quantization_level", ""),
        "size": det.get("parameter_size", ""),
        "family": det.get("family", ""),
        "arch": arch,
        "tokenizer": info.get("tokenizer.ggml.pre", ""),
    }


def installed():
    return call("/api/tags").get("models", [])


def canonical(name):
    """Ollama's full name for a model: adds :latest when no tag is given."""
    last = name.rsplit("/", 1)[-1]
    return name if ":" in last else f"{name}:latest"


def pull(name, on_progress):
    """Download a model, calling on_progress(status, completed, total)."""
    req = urllib.request.Request(OLLAMA + "/api/pull",
                                 data=json.dumps({"model": name, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        # Ollama can go quiet for minutes while it checks a big download.
        with urllib.request.urlopen(req, timeout=900) as resp:
            for line in resp:
                if not line.strip():
                    continue
                msg = json.loads(line)
                if "error" in msg:
                    raise OllamaError(msg["error"])
                on_progress(msg.get("status", ""), msg.get("completed", 0), msg.get("total", 0))
    except urllib.error.HTTPError as e:
        raise OllamaError(_http_message(e)) from None
    except urllib.error.URLError as e:
        raise OllamaError(f"Could not reach Ollama: {e.reason}") from None
    except (OSError, http.client.HTTPException) as e:
        raise OllamaError(f"The download stopped ({e.__class__.__name__}). "
                          "Try again; it carries on where it left off.") from None


def delete(name):
    call("/api/delete", {"model": name}, method="DELETE")


def running():
    return call("/api/ps").get("models", [])


def unload(name):
    call("/api/generate", {"model": name, "keep_alive": 0})
