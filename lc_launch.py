"""LocalCoder launcher: pick any Ollama model, check it can work as an agent,
make sure it has enough memory (context), then start Claude Code or OpenCode.

Usage:
    python lc_launch.py [project_folder] [--model NAME] [--tool claude|opencode]
                        [--yes] [-- extra args for the tool]

Everything is read from Ollama itself (/api/tags, /api/show), so no naming
convention is needed: tool support and context size come from the model.
"""

import argparse
import os
import subprocess
import socket
import sys
import threading
import time
import urllib.error
from pathlib import Path

from lc_ollama import OllamaError, api, model_facts, start_ollama, unload

ROOT = Path(__file__).resolve().parent
RELAY_PORT = 11435
MIN_CTX = 32768        # Claude Code needs ~23k just to start a task
WANT_CTX = 65536       # comfortable default for agent work
started_relays = []    # relay processes this launcher started
SESSIONS = ROOT / "logs" / "sessions"   # one file per open George window: the model it uses


# ---------- Ollama helpers ----------

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


# ---------- keeping the model loaded ----------
# Ollama is set to keep models loaded until told otherwise (Model Manager:
# stay loaded = forever), so a pause never forces a slow reload and re-read.
# George frees the model when it closes, unless another George window is
# still using it.

def _alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True).stdout
    return str(pid) in out


def other_sessions_using(model, me=None):
    me = me or os.getpid()
    users = 0
    for f in (SESSIONS.glob("*.model") if SESSIONS.exists() else []):
        try:
            pid = int(f.stem)
        except ValueError:
            continue
        if pid == me:
            continue
        if not _alive(pid):
            f.unlink(missing_ok=True)  # left behind by a window that crashed
        elif f.read_text(encoding="utf-8").strip() == model:
            users += 1
    return users


def register_session(model):
    SESSIONS.mkdir(parents=True, exist_ok=True)
    (SESSIONS / f"{os.getpid()}.model").write_text(model, encoding="utf-8")


_released = threading.Lock()


def release_model(model):
    """Forget this window and free the model if no other George window uses it."""
    if not _released.acquire(blocking=False):
        return  # already done (normal exit and window close can both call this)
    (SESSIONS / f"{os.getpid()}.model").unlink(missing_ok=True)
    if other_sessions_using(model):
        return
    try:
        unload(model)
    except OllamaError:
        pass  # Ollama already gone: nothing is loaded


def on_window_close(model):
    """Free the model when the George window is closed with its X button too."""
    if os.name != "nt":
        return
    import ctypes
    HANDLER = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

    def handler(event):
        if event in (2, 5, 6):  # window closed, log off, shut down
            release_model(model)
        return False
    on_window_close.keep = HANDLER(handler)  # must outlive this function
    ctypes.windll.kernel32.SetConsoleCtrlHandler(on_window_close.keep, True)


# ---------- relay ----------

def relay_up(port=RELAY_PORT):
    """True if something is accepting connections on the relay port.
    Checks the port only, so a stopped Ollama doesn't look like a dead relay."""
    try:
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
        return True
    except OSError:
        return False


def start_relay(port=RELAY_PORT):
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    kw = {"creationflags": flags} if flags else {}
    if flags:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7  # minimised, not focused
        kw["startupinfo"] = si
    proc = subprocess.Popen([sys.executable, str(ROOT / "lc_proxy.py"), str(port)], **kw)
    started_relays.append(proc)
    return proc


def ensure_relay(port=RELAY_PORT):
    """Start the relay if it isn't running. Returns False if it won't come up."""
    if relay_up(port):
        return True
    start_relay(port)
    for _ in range(30):
        time.sleep(0.5)
        if relay_up(port):
            return True
    return False


def watch_relay(port=RELAY_PORT, every=2.0):
    """Restart the relay whenever it stops (window closed, crash) while the
    tool is running, so Claude Code's retries reconnect instead of failing.
    Set the returned event to stop watching."""
    stop = threading.Event()

    def loop():
        while not stop.wait(every):
            if not relay_up(port):
                ensure_relay(port)
    threading.Thread(target=loop, daemon=True).start()
    return stop


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
    a = ap.parse_args(argv)

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
    if tool == "claude":
        for k in ("OPUS", "SONNET", "HAIKU", "FABLE"):
            env[f"ANTHROPIC_DEFAULT_{k}_MODEL"] = f["name"]
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = f["name"]
        ctx = f["num_ctx"] or MIN_CTX
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(ctx)
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(min(8192, ctx // 8))
        if not ensure_relay():
            sys.exit("The LocalCoder relay did not start.")
        watch_relay()
        env["OLLAMA_HOST"] = f"127.0.0.1:{RELAY_PORT}"
        extra = ["--settings", str(ROOT / "claude-settings.json")] + extra
    if extra:
        cmd += ["--"] + extra

    print(f"\nLaunching {tool} with {f['name']} in \"{folder}\"\n")
    register_session(f["name"])
    on_window_close(f["name"])
    code = 130
    try:
        code = subprocess.call(cmd, cwd=folder, env=env)
    except KeyboardInterrupt:
        pass
    finally:
        release_model(f["name"])
    sys.exit(code)


if __name__ == "__main__":
    main()
