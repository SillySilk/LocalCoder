"""Import .gguf files into Ollama, and give models tool use when Ollama
didn't recognise their chat format."""

import hashlib
import urllib.error
import urllib.request
from pathlib import Path

import lc_ollama
from lc_ollama import OllamaError, call, canonical, facts, installed

# Probed on Ollama 0.40.16: /api/create accepts "renderer" and "parser" and
# /api/show returns them (e.g. qwen3-coder models), so both are copied.
COPY_KEYS = ("template", "renderer", "parser")


def find_ggufs():
    found = []
    for root in (Path.home() / ".lmstudio" / "models", Path.home() / "Downloads"):
        if root.is_dir():
            found += [p for p in root.rglob("*.gguf") if not p.name.lower().startswith("mmproj")]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def clean_path(text):
    return Path(text.strip().strip('"').strip("'"))


def suggest_name(path):
    return Path(path).stem.lower().replace(" ", "-")


def blob_digest(path, on_progress=None):
    h = hashlib.sha256()
    total = Path(path).stat().st_size
    done = 0
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
            done += len(chunk)
            if on_progress:
                on_progress("Checking file", done, total)
    return f"sha256:{h.hexdigest()}"


class Throttle:
    """Pass progress on only every `every_bytes`, and always at the end,
    so a big import doesn't spend minutes redrawing the progress line."""

    def __init__(self, on_progress, every_bytes=64 << 20):
        self.cb, self.every, self.last, self.step = on_progress, every_bytes, None, None

    def __call__(self, step, done, total):
        if step != self.step:  # a new step starts counting from zero again
            self.step, self.last = step, None
        if self.last is None or done - self.last >= self.every or done >= total:
            self.last = done
            self.cb(step, done, total)


class _Reader:
    def __init__(self, f, total, on_progress):
        self.f, self.total, self.done, self.cb = f, total, 0, on_progress

    def read(self, n=-1):
        chunk = self.f.read(n if n and n > 0 else 8 << 20)
        self.done += len(chunk)
        self.cb("Copying into Ollama", self.done, self.total)
        return chunk


def _upload(path, digest, on_progress):
    url = f"{lc_ollama.OLLAMA}/api/blobs/{digest}"
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30)
        return  # Ollama already has it
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise OllamaError(f"Ollama said {e.code} {e.reason}") from None
    except urllib.error.URLError:
        raise OllamaError("Could not reach Ollama. Open the Ollama app and try again.") from None
    size = Path(path).stat().st_size
    with open(path, "rb") as f:
        req = urllib.request.Request(url, data=_Reader(f, size, on_progress), method="POST",
                                     headers={"Content-Length": str(size)})
        try:
            urllib.request.urlopen(req, timeout=3600)
        except urllib.error.HTTPError as e:
            raise OllamaError(f"Ollama would not take the file: {e.code} {e.reason}") from None


def import_gguf(path, name, on_progress):
    """on_progress(step, done, total). Returns the model's full name."""
    path = Path(path)
    if not path.is_file():
        raise OllamaError(f"File not found: {path}")
    on_progress = Throttle(on_progress)
    digest = blob_digest(path, on_progress)
    _upload(path, digest, on_progress)
    on_progress("Creating the model", 0, 0)
    call("/api/create", {"model": name, "files": {path.name: digest}, "stream": False}, timeout=600)
    return canonical(name)


def fix_tools(name):
    """Give `name` tool use by copying the chat format from an installed model
    of the same architecture that has it. Returns the donor's name, `name`
    itself if it already had tool use, or None if no donor exists."""
    mine = facts(name)
    if mine["tools"]:
        return name
    me = canonical(name)
    for m in installed():
        other = canonical(m["name"])
        if other == me:
            continue
        try:
            f = facts(other)
        except (OllamaError, OSError, ValueError):
            continue
        # Same architecture is not enough (many families report "llama");
        # the tokenizer must match too, or the copied format uses tokens the model lacks.
        if not (f["tools"] and f["arch"] == mine["arch"] and mine["tokenizer"]
                and f["tokenizer"] == mine["tokenizer"]):
            continue
        show = call("/api/show", {"model": other})
        body = {"model": name, "from": name, "stream": False}
        body.update({k: show[k] for k in COPY_KEYS if show.get(k)})
        call("/api/create", body, timeout=600)
        if facts(name)["tools"]:
            return other
    return None


def missing_family_hint(name):
    arch = facts(name)["arch"] or "unknown"
    return (f"No installed model of the same kind ({arch}) has tool use to copy from. "
            f"Download an official {arch} model with tool use from "
            "https://ollama.com/search?c=tools, then run the tool check again.")
