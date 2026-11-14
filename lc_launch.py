"""LocalCoder launcher: pick any Ollama model, check it can work as an agent,
make sure it has enough memory (context), then start Claude Code or OpenCode.

Usage:
    python lc_launch.py [project_folder] [--model NAME] [--tool claude|opencode]
                        [--yes] [-- extra args for the tool]

Everything is read from Ollama itself (/api/tags, /api/show), so no naming
convention is needed: tool support and context size come from the model.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLLAMA = os.environ.get("LC_OLLAMA_URL", "http://127.0.0.1:11434")
MIN_CTX = 32768        # Claude Code needs ~23k just to start a task
WANT_CTX = 65536       # comfortable default for agent work


# ---------- Ollama helpers ----------

def api(path, body=None, base=None, timeout=30):
    base = base or OLLAMA
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def ollama_up():
    try:
        api("/api/version", timeout=3)
        return True
    except OSError:
        return False


def ollama_start_command(platform=sys.platform):
    """How to start Ollama in the background on this kind of computer."""
    if platform == "win32":
        exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
        return [str(exe)] if exe.exists() else ["ollama", "serve"]
    if platform == "darwin":
        return ["open", "-a", "Ollama"]
    return ["ollama", "serve"]


def start_ollama():
    if ollama_up():
        return
    print("Starting Ollama...")
    try:
        subprocess.Popen(ollama_start_command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **relay_popen_kwargs())
    except OSError:
        pass
    for _ in range(30):
        if ollama_up():
            return
        time.sleep(1)
    sys.exit("Ollama did not start. Open the Ollama app and try again.")


def model_facts(name):
    """What LocalCoder needs to know about one installed model."""
    d = api("/api/show", {"model": name})
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
    }


def list_models():
    names = [m["name"] for m in api("/api/tags").get("models", [])]
    facts = []
    for n in names:
        try:
            f = model_facts(n)
        except (OSError, ValueError):
            continue
        if not f["embedding_only"]:
            facts.append(f)
    # agent-ready first (tools + enough context), then tools, then the rest
    def rank(f):
        ready = f["tools"] and (f["num_ctx"] or 0) >= MIN_CTX
        return (not ready, not f["tools"], f["name"])
    return sorted(facts, key=rank)


def describe(f):
    bits = [f"{f['size']} {f['quant']}".strip()]
    bits.append(f"{(f['num_ctx'] or 0) // 1024}k memory" if f["num_ctx"] else "default memory")
    if f["thinking"]:
        bits.append("thinks")
    if not f["tools"]:
        bits.append("NO TOOL USE")
    return ", ".join(b for b in bits if b)


def variant_name(name, ctx):
    base = name[:-len(":latest")] if name.endswith(":latest") else name
    return f"{base.replace(':', '-').replace('/', '-')}-{ctx // 1024}k"


def make_variant(f, ctx):
    """Create <model>-NNk: same model files, just a bigger context. Takes seconds."""
    new = variant_name(f["name"], ctx)
    print(f"Creating {new} (same model, {ctx // 1024}k memory)...")
    try:
        r = api("/api/create", {"model": new, "from": f["name"], "stream": False,
                                "parameters": {"num_ctx": ctx}}, timeout=600)
    except urllib.error.HTTPError as e:
        sys.exit(f"Could not create {new}: {e.read().decode(errors='replace')}")
    if r.get("status") != "success":
        sys.exit(f"Could not create {new}: {r}")
    made = model_facts(new)
    if made["tools"] != f["tools"]:
        sys.exit(f"{new} lost tool support when copied; please report this.")
    return made


# ---------- relay ----------

def relay_popen_kwargs(platform=sys.platform):
    """Background helper processes: no console window on Windows."""
    if platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def start_relay(upstream=None):
    """Start this session's relay on a free port; returns (process, port).

    The relay picks its own port (no clashes between windows) and exits by
    itself when this launcher process goes away, even if the window is closed.
    """
    cmd = [sys.executable, str(ROOT / "lc_proxy.py"), "0", upstream or OLLAMA,
           "--parent", str(os.getpid())]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            **relay_popen_kwargs())
    line = proc.stdout.readline().split()
    if len(line) != 2 or line[0] != "PORT":
        proc.kill()
        sys.exit("The LocalCoder relay did not start.")
    return proc, int(line[1])


# ---------- diagnostics ----------

MIN_OLLAMA = (0, 40)


def _version_tuple(v):
    out = []
    for part in v.split(".")[:2]:
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def run_checks():
    """Everything LocalCoder depends on, as (name, status, detail) rows.

    status is "ok", "warn" (works, but worth knowing) or "fail" (broken).
    """
    import shutil
    rows = []
    try:
        v = api("/api/version", timeout=5).get("version", "?")
    except OSError as e:
        return [("Ollama", "fail", f"not reachable at {OLLAMA} ({e})")]
    new_enough = _version_tuple(v) >= MIN_OLLAMA
    rows.append(("Ollama", "ok" if new_enough else "fail", v if new_enough else f"{v}; needs 0.40 or newer"))
    for exe in ("claude", "opencode"):
        path = shutil.which(exe)
        rows.append((exe, "ok" if path else "warn", path or "not installed (only needed to use it)"))
    try:
        proc, port = start_relay(OLLAMA)
        try:
            api("/api/version", base=f"http://127.0.0.1:{port}", timeout=5)
            rows.append(("relay", "ok", f"started on port {port}"))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
    except (OSError, SystemExit) as e:
        rows.append(("relay", "fail", f"did not start ({e})"))
    for m in api("/api/tags").get("models", []):
        try:
            f = model_facts(m["name"])
        except (OSError, ValueError) as e:
            rows.append((f"model {m['name']}", "warn", f"could not read ({e})"))
            continue
        if f["embedding_only"]:
            continue
        problems = []
        if not f["tools"]:
            problems.append("no tool use")
        if (f["num_ctx"] or 0) < MIN_CTX:
            have = f"{f['num_ctx'] // 1024}k" if f["num_ctx"] else "default"
            problems.append(f"{have} memory; launcher will offer a {WANT_CTX // 1024}k version")
        rows.append((f"model {f['name']}", "warn" if problems else "ok", "; ".join(problems) or describe(f)))
    return rows


def checks_passed(rows):
    return all(status != "fail" for _, status, _ in rows)


def print_checks(rows):
    width = max(len(r[0]) for r in rows)
    mark = {"ok": "OK  ", "warn": "note", "fail": "FAIL"}
    for name, status, detail in rows:
        print(f"  {mark[status]}  {name.ljust(width)}  {detail}")
    return checks_passed(rows)


# ---------- interaction ----------

def ask(prompt, default):
    try:
        v = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        v = ""
    return v or default


def choose_model(models):
    print("\n===== Pick a model =====")
    shown_rest = False
    for i, f in enumerate(models, 1):
        if not f["tools"] and not shown_rest:
            print("  --- can't use tools (chat only, won't work as an agent) ---")
            shown_rest = True
        print(f"  {i}) {f['name']}  ({describe(f)})")
    pick = ask("\nModel number", "1")
    try:
        return models[int(pick) - 1]
    except (ValueError, IndexError):
        sys.exit("Invalid choice.")


def prepare(f, auto_yes):
    """Make sure the model can act as an agent and has enough memory."""
    if not f["tools"]:
        print(f"\n{f['name']} doesn't support tool use, so it can't read or edit files as an agent.")
        if auto_yes or ask("Start anyway? (y/n)", "n").lower() != "y":
            sys.exit(1)
    ctx = f["num_ctx"] or 0
    if ctx >= MIN_CTX:
        return f
    cap = f["max_ctx"] or WANT_CTX
    target = min(WANT_CTX, cap)
    if target < MIN_CTX:
        print(f"\nWarning: {f['name']} can only hold {cap // 1024}k tokens; Claude Code needs ~23k to start.")
        target = cap
    have = variant_name(f["name"], target)
    names = {m["name"] for m in api("/api/tags").get("models", [])}
    if have in names or f"{have}:latest" in names:
        print(f"\nUsing {have} (the {target // 1024}k-memory version of {f['name']}).")
        return model_facts(have)
    print(f"\n{f['name']} is set to {'Ollama' + chr(39) + 's default' if not ctx else f'{ctx // 1024}k'} memory, "
          f"too little for agent work.")
    if auto_yes or ask(f"Make a {target // 1024}k version now? (y/n)", "y").lower() == "y":
        return make_variant(f, target)
    return f


def main():
    argv = sys.argv[1:]
    passthrough = []
    if "--" in argv:
        i = argv.index("--")
        argv, passthrough = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--model")
    ap.add_argument("--tool", choices=["claude", "opencode"])
    ap.add_argument("--yes", action="store_true", help="no questions; accept defaults")
    ap.add_argument("--check", action="store_true", help="check the setup and exit")
    a = ap.parse_args(argv)
    if a.check:
        sys.exit(0 if print_checks(run_checks()) else 1)

    folder = Path(a.folder or os.getcwd())
    if not folder.is_dir():
        sys.exit(f"Folder not found: {folder}")

    start_ollama()
    if a.model:
        try:
            f = model_facts(a.model)
        except urllib.error.HTTPError:
            sys.exit(f"Model not installed: {a.model}")
    else:
        models = list_models()
        if not models:
            sys.exit("No models installed. Get one with: ollama pull <model>  (see https://ollama.com/search?c=tools)")
        f = choose_model(models)
    f = prepare(f, a.yes)

    tool = a.tool
    if not tool:
        print("\n===== Pick a tool =====")
        print("  1) Claude Code  (keeps your hooks, skills, CLAUDE.md)")
        print("  2) OpenCode")
        tool = {"1": "claude", "2": "opencode"}.get(ask("Tool number", "1"))
        if not tool:
            sys.exit("Invalid choice.")

    env = dict(os.environ)
    # OpenCode trusts PWD over the real working folder; a stale PWD (e.g. from
    # Git Bash) makes it work in the wrong project.
    env["PWD"] = str(folder.resolve())
    cmd = ["ollama", "launch", tool, "--model", f["name"]]
    if a.yes:
        cmd.append("--yes")
    extra = list(passthrough)
    relay = None
    if tool == "claude":
        for k in ("OPUS", "SONNET", "HAIKU", "FABLE"):
            env[f"ANTHROPIC_DEFAULT_{k}_MODEL"] = f["name"]
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = f["name"]
        ctx = f["num_ctx"] or MIN_CTX
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(ctx)
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(min(8192, ctx // 8))
        relay, port = start_relay()
        env["OLLAMA_HOST"] = f"127.0.0.1:{port}"
        extra = ["--settings", str(ROOT / "claude-settings.json")] + extra
    if extra:
        cmd += ["--"] + extra

    print(f"\nLaunching {tool} with {f['name']} in \"{folder}\"\n")
    sys.exit(subprocess.call(cmd, cwd=folder, env=env))


if __name__ == "__main__":
    main()
