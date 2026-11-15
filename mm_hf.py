"""Hugging Face: search for GGUF models, list their sizes, download files."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HF = "https://huggingface.co"
UA = {"User-Agent": "LocalCoder-ModelManager"}

QUANT = re.compile(r"(?<![A-Za-z0-9])(I?Q\d(?:_[A-Z0-9]+)*|F16|BF16|F32)(?=[-.])", re.I)
HELPERS = ("mtp-", "dflash-", "draft-")
SPLIT = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)


class HFError(Exception):
    """A Hugging Face failure described in plain words."""


def _open(url, headers=None, timeout=30):
    if isinstance(url, urllib.request.Request):
        req = url
        for k, v in {**UA, **(headers or {})}.items():
            req.add_header(k, v)
    else:
        req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        # Hugging Face answers 401 for missing repos too; only GatedRepo means a login helps.
        if e.headers.get("X-Error-Code") == "GatedRepo" or e.code == 403:
            raise HFError("needs a Hugging Face login") from None
        if e.code in (401, 404):
            raise HFError("not found (or private)") from None
        raise HFError(f"Hugging Face said {e.code} {e.reason}") from None
    except urllib.error.URLError:
        raise HFError("can't reach Hugging Face (check the internet connection)") from None


def _json(url):
    with _open(url) as r:
        return json.loads(r.read())


def search(words, limit=20):
    q = urllib.parse.urlencode([("search", words), ("filter", "gguf"), ("sort", "downloads"),
                                ("direction", "-1"), ("limit", limit), ("expand[]", "downloads"),
                                ("expand[]", "lastModified"), ("expand[]", "gated")])
    return [{"repo": m["id"], "downloads": m.get("downloads", 0),
             "updated": (m.get("lastModified") or "")[:10], "gated": bool(m.get("gated"))}
            for m in _json(f"{HF}/api/models?{q}")]


def quant_of(filename):
    name = Path(filename).name
    found = QUANT.findall(name)
    return found[-1].upper() if found else None


def quants(repo):
    tree = _json(f"{HF}/api/models/{repo}/tree/main?recursive=true")
    groups = {}
    for f in tree:
        path = f.get("path", "")
        if f.get("type") != "file" or not path.lower().endswith(".gguf"):
            continue
        base = Path(path).name.lower()
        # Helper files that sit next to a model and can't run on their own:
        # image readers (mmproj) and speed-up drafts (mtp, dflash, draft).
        if "mmproj" in base or base.startswith(HELPERS):
            continue
        q = quant_of(path)
        if not q:
            continue
        split = bool(SPLIT.search(path))
        key = (q, SPLIT.sub("", path) if split else path)
        g = groups.setdefault(key, {"quant": q, "files": [], "size": 0, "split": split})
        g["files"].append(path)
        g["size"] += (f.get("lfs") or {}).get("size") or f.get("size", 0)
    return sorted(groups.values(), key=lambda g: g["size"])


def ollama_name(repo, quant):
    return f"hf.co/{repo}:{quant}"


def download_file(repo, path, dest_dir, on_progress):
    """Download one file, carrying on from a .part file if one exists.
    on_progress(done_bytes, total_bytes)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / Path(path).name
    part = final.with_name(final.name + ".part")
    url = f"{HF}/{repo}/resolve/main/{urllib.parse.quote(path)}"
    have = part.stat().st_size if part.exists() else 0
    if have:
        with _open(urllib.request.Request(url, method="HEAD")) as r:
            size = int(r.headers.get("Content-Length", 0))
        if have == size:  # already complete: just finish it
            part.replace(final)
            return final
        if have > size:  # not this file; start over
            part.unlink()
            have = 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with _open(url, headers, timeout=60) as r:
        if have and r.status != 206:
            have = 0  # server ignored the range; start over
        total = have + int(r.headers.get("Content-Length", 0))
        with open(part, "ab" if have else "wb") as out:
            done = have
            on_progress(done, total)
            while chunk := r.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                on_progress(done, total)
    part.replace(final)
    return final
