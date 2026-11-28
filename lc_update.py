"""Version and update checks for the tools LocalCoder depends on.

Claude Code and OpenCode change often, and an update can change behaviour
LocalCoder relies on. (The engine itself belongs to Engine Manager, which
handles its own updates.) This module answers two questions:
  - is a newer version available?
  - is what's installed newer than what LocalCoder was last tested with
    (tested-versions.json)?
and can run the updaters (`lc_launch.py --update`).
"""

import json
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTED_FILE = ROOT / "tested-versions.json"
TOOLS = ("claude", "opencode")
SOURCES = {
    "claude": "https://registry.npmjs.org/@anthropic-ai/claude-code/latest",
    "opencode": "https://registry.npmjs.org/opencode-ai/latest",
}


def parse(text):
    """First x.y.z in `text` as a tuple of ints, or None."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups(default="0"))


def _last_line(text):
    lines = [re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", ln).strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    return lines[-1] if lines else ""


def _vstr(text):
    v = parse(text)
    return ".".join(map(str, v)) if v else None


def _run(cmd, cwd=None):
    import shutil
    exe = shutil.which(cmd[0])  # resolves .cmd/.bat wrappers (e.g. npm's opencode.CMD) on Windows
    if exe:
        cmd = [exe] + list(cmd[1:])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=cwd,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "LocalCoder-update-check"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _is_git_clone():
    return (ROOT / ".git").exists()


def _git_head():
    if not _is_git_clone():
        return None
    code, out = _run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT)
    return out if code == 0 else None


def _git_remote_head():
    if not _is_git_clone():
        return None
    code, out = _run(["git", "ls-remote", "origin", "HEAD"], cwd=ROOT)
    return out.split()[0][:7] if code == 0 and out else None


def _git_has(commit):
    """True if `commit` is already part of this copy's history (so this copy is
    up to date with it, or ahead of it)."""
    code, _ = _run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT)
    return code == 0


def installed():
    """Installed versions; None for anything not installed."""
    out = {}
    for tool in TOOLS:
        code, text = _run([tool, "--version"])
        out[tool] = _vstr(text) if code == 0 else None
    out["localcoder"] = _git_head()
    return out


def latest(fetch=_http_json, git_remote=_git_remote_head):
    """Newest published versions; None where the check couldn't be made."""
    out = {}
    for tool, url in SOURCES.items():
        try:
            d = fetch(url)
            out[tool] = _vstr(d.get("version") or d.get("tag_name"))
        except (OSError, ValueError, AttributeError):
            out[tool] = None
    out["localcoder"] = git_remote()
    return out


def tested():
    try:
        return json.loads(TESTED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_tested(versions, date):
    """Called by the test kit after a passing run."""
    data = {t: versions.get(t) for t in TOOLS}
    data["date"] = str(date)
    TESTED_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def rows(have, newest, tested_with, git_has=_git_has):
    """(name, status, detail) rows for lc_launch --check. Never "fail"."""
    out = []
    for tool in TOOLS:
        if tool not in have or have[tool] is None:
            continue
        v, n, t = have[tool], newest.get(tool), tested_with.get(tool)
        notes = []
        if n is None:
            notes.append("couldn't check for updates")
        elif parse(n) and parse(v) and parse(n) > parse(v):
            notes.append(f"update available: {v} → {n} (run --update)")
        if parse(t) and parse(v) and parse(v) > parse(t):
            notes.append(f"{v} is not yet tested with LocalCoder (last tested {t})")
        status = "warn" if any("update available" in x or "not yet tested" in x for x in notes) else "ok"
        out.append((f"{tool} version", status, "; ".join(notes) or f"{v}, up to date"))
    if have.get("localcoder"):
        v, n = have["localcoder"], newest.get("localcoder")
        if n is None:
            out.append(("localcoder version", "ok", f"{v} (couldn't check GitHub)"))
        elif n != v and not git_has(n):
            out.append(("localcoder version", "warn", f"{v}; GitHub has {n} (run --update)"))
        elif n != v:
            out.append(("localcoder version", "ok", f"{v}, ahead of GitHub ({n})"))
        else:
            out.append(("localcoder version", "ok", f"{v}, up to date"))
    return out


def _update_localcoder():
    if not _is_git_clone():
        return True, "not a git clone; download the latest from GitHub to update"
    code, out = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT)
    if out:
        return False, "has local changes; not pulling"
    code, out = _run(["git", "pull", "--ff-only"], cwd=ROOT)
    return code == 0, _last_line(out) or ("ok" if code == 0 else "pull failed")


def run_updates():
    """Update everything installed. Returns (name, ok, detail) rows."""
    have = installed()
    results = []
    for tool, cmd in (("claude", ["claude", "update"]), ("opencode", ["opencode", "upgrade"])):
        if have.get(tool) is None:
            continue
        code, out = _run(cmd)
        results.append((tool, code == 0, _last_line(out) or ("done" if code == 0 else "failed")))
    results.append(("localcoder", *_update_localcoder()))
    return results
