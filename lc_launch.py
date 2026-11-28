"""LocalCoder launcher: pick a model from the shared engine (Engine Manager),
then start Claude Code or OpenCode on it.

Usage:
    python lc_launch.py [project_folder] [--model NAME] [--tool claude|opencode]
                        [--yes] [-- extra args for the tool]
    python lc_launch.py --check     check the setup and exit
    python lc_launch.py --update    update Claude Code, OpenCode and LocalCoder, then check

The model list, memory sizes and the default model come from Engine Manager.
Enter at the model prompt picks the default model.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import lc_engine

ROOT = Path(__file__).resolve().parent
MIN_CTX = 32768        # Claude Code needs ~23k just to start a task
SESSIONS = ROOT / "logs" / "sessions"   # one file per open George window: the model it uses


def describe(f):
    bits = []
    if f["size"]:
        bits.append(f"{f['size'] / 10**9:.1f} GB")
    bits.append(f"{f['ctx'] // 1024}k memory")
    if f["vision"]:
        bits.append("reads images")
    if f["state"] in ("loaded", "loading", "sleeping"):
        bits.append("loaded now")
    return ", ".join(bits)


# ---------- keeping the model loaded ----------
# The engine keeps a model loaded until told otherwise, so a pause never forces
# a slow reload and re-read. George frees the model when it closes, unless
# another George window is still using it.

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


def release_model(model, unload=None):
    """Forget this window and free the model if no other George window uses it."""
    if not _released.acquire(blocking=False):
        return  # already done (normal exit and window close can both call this)
    (SESSIONS / f"{os.getpid()}.model").unlink(missing_ok=True)
    if other_sessions_using(model):
        return
    (unload or lc_engine.unload)(model)


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

def relay_popen_kwargs(platform=sys.platform):
    """Background helper processes: no console window on Windows."""
    if platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def start_relay(upstream, port=0):
    """Start this session's relay; returns (process, port).

    Port 0 lets the relay pick a free port and report it, so windows never
    clash and nothing else on a fixed port can block George. The relay exits by
    itself once this launcher is gone, even if its window is closed.
    """
    cmd = [sys.executable, str(ROOT / "lc_proxy.py"), str(port), upstream, "--parent", str(os.getpid())]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            **relay_popen_kwargs())
    line = proc.stdout.readline().split()
    if len(line) != 2 or line[0] != "PORT":
        proc.kill()
        raise OSError("the relay did not start")
    return proc, int(line[1])


def keep_relay_running(proc, port, upstream, every=2.0):
    """Restart this session's relay on the same port if it stops (a crash), so
    Claude Code's retries reconnect instead of failing. Returns (stop event,
    list holding the current process)."""
    current = [proc]
    stop = threading.Event()

    def loop():
        while not stop.wait(every):
            if current[0].poll() is not None:
                try:
                    current[0] = start_relay(upstream, port)[0]
                except OSError:
                    pass  # port briefly busy; try again next round
    threading.Thread(target=loop, daemon=True).start()
    return stop, current


# ---------- diagnostics ----------

def run_checks(include_updates=True):
    """Everything George depends on, as (name, status, detail) rows.

    status is "ok", "warn" (works, but worth knowing) or "fail" (broken).
    """
    rows = []
    try:
        lc_engine.start_engine()
        models = lc_engine.models()
        rows.append(("engine", "ok", f"Engine Manager at {lc_engine.url()}"))
    except (OSError, SystemExit, lc_engine.EngineError) as e:
        return [("engine", "fail", f"not reachable at {lc_engine.url()} ({e})")]
    for exe in ("claude", "opencode"):
        path = shutil.which(exe)
        rows.append((exe, "ok" if path else "warn", path or "not installed (only needed to use it)"))
    try:
        proc, port = start_relay(lc_engine.url())
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as r:
                r.read()
            rows.append(("relay", "ok", f"started on port {port} and reached the engine"))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
    except OSError as e:
        rows.append(("relay", "fail", f"did not work ({e})"))
    if not models:
        rows.append(("models", "warn", "none yet; download one in Engine Manager"))
    for f in models:
        if f["ctx"] < MIN_CTX:
            rows.append((f"model {f['name']}", "warn",
                         f"{f['ctx'] // 1024}k memory; Claude Code needs 32k or more (raise it in Engine Manager)"))
        else:
            rows.append((f"model {f['name']}", "ok", describe(f)))
    if include_updates:
        import lc_update
        rows += lc_update.rows(lc_update.installed(), lc_update.latest(), lc_update.tested())
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
    for i, f in enumerate(models, 1):
        star = "  * default" if f["default"] else ""
        print(f"  {i}) {f['name']}  ({describe(f)}){star}")
    print("  Manage models: Engine Manager (EngineManager.bat)")
    pick = ask("\nModel number", "1")
    try:
        return models[int(pick) - 1]
    except (ValueError, IndexError):
        sys.exit("Invalid choice.")


def check_memory(f):
    if f["ctx"] < MIN_CTX:
        print(f"\nWarning: {f['name']} is set to {f['ctx'] // 1024}k memory; Claude Code needs about 23k "
              f"just to start. Raise it in Engine Manager (Memory column).")


FORGE_PLUGIN = Path.home() / ".claude" / "plugins" / "cache" / "forge-neo" / "forge-neo"


def forge_server(env):
    """The Forge Neo image add-on, from the Claude Code plugin install. None if missing."""
    root = env.get("FORGE_NEO_ROOT")
    scripts = sorted(FORGE_PLUGIN.glob("*/server/forge_mcp.py"))
    if not root or not scripts:
        return None
    python = Path(root) / "venv" / "Scripts" / "python.exe"
    if not python.is_file():
        return None
    return {"type": "local", "command": [str(python), str(scripts[-1])],
            "environment": {"FORGE_NEO_ROOT": root}}


BOW_DIR = Path(os.environ.get("BOW_DIR") or r"C:\AI\Apps\agent Bow")
BOW_IDLE_SECS = 120   # AgentBow closes itself after this long unused; restarts on demand
BOW_EXE = BOW_DIR / "desktop" / "src-tauri" / "target" / "debug" / "bow-desktop.exe"


def bow_images_server():
    """AgentBow's image downloader as an add-on. It runs AgentBow on the shared
    engine, so it never starts a second copy of a model."""
    if not BOW_EXE.is_file():
        return None
    return {"type": "local", "command": ["node", str(ROOT / "addons" / "bow-images.mjs")],
            "environment": {"BOW_DIR": str(BOW_DIR), "ENGINE_URL": lc_engine.url(),
                            "BOW_IDLE_SECS": str(BOW_IDLE_SECS)}}


def opencode_addons(env):
    """Add-ons for OpenCode: web search, browser, GitHub, images.
    Returns (config pieces, list of warnings for add-ons that can't start)."""
    warnings = []
    servers = {"playwright": {"type": "local", "command": ["npx", "-y", "@playwright/mcp@latest"]}}
    cfg = {"mcp": {"servers": servers}}

    if env.get("FIRECRAWL_API_KEY"):
        cfg["websearch"] = {"provider": "firecrawl"}
        # Page reading that gets past sites which block plain requests.
        servers["firecrawl"] = {"type": "local", "command": ["npx", "-y", "firecrawl-mcp"]}
    else:
        warnings.append("Firecrawl search and page reading are off: FIRECRAWL_API_KEY is not set.")

    gh = shutil.which("gh")
    token = subprocess.run([gh, "auth", "token"], capture_output=True, text=True).stdout.strip() if gh else ""
    if token:
        env["GITHUB_TOKEN"] = token
        servers["github"] = {"type": "remote", "url": "https://api.githubcopilot.com/mcp/", "oauth": False,
                             "headers": {"Authorization": "Bearer {env:GITHUB_TOKEN}"}}
    else:
        warnings.append("GitHub add-on is off: sign in with 'gh auth login'.")

    bow = bow_images_server()
    if bow:
        servers["bow-images"] = bow
        # A helper that does image work in its own conversation, so downloads
        # and retries don't fill up the main chat.
        cfg["agents"] = {"images": {
            "description": "Image helper: finds, downloads, checks, de-duplicates and captions pictures "
                           "(training sets, reference images). Hand it any request to collect or curate images.",
            "mode": "subagent",
            "system": (ROOT / "images-agent.md").read_text(encoding="utf-8"),
            # It reads the same notes that say "hand image work to the images
            # helper"; without this it tries to hand the job to itself.
            "permissions": [{"action": "subagent", "resource": "*", "effect": "deny"}],
        }}
    else:
        warnings.append(f"Image download add-on is off: AgentBow is not built ({BOW_EXE}).")

    forge = forge_server(env)
    if forge:
        servers["forge-neo"] = forge
    else:
        warnings.append("Image add-on is off: Forge Neo not found (FORGE_NEO_ROOT or the Claude plugin).")
    return cfg, warnings


def opencode_config(model, ctx, addons=None):
    """OpenCode settings that point it at the engine's OpenAI-style endpoint.
    The limit lets OpenCode show the real fill level and shrink the chat before
    the engine runs out of room."""
    return json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "provider": {"engine": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Local engine",
            "options": {"baseURL": lc_engine.url("/v1"), "apiKey": "local"},
            "models": {model: {"name": model, "tools": True,
                               "limit": {"context": ctx, "output": min(8192, ctx // 8)}}},
        }},
        "model": f"engine/{model}",
        # Standing notes on this computer's shell and on downloading politely.
        "instructions": [str(ROOT / "opencode-notes.md")],
        **(addons or {}),
    })


def build_command(tool, f, folder, passthrough, env, relay_port=None):
    """The command line and environment for the chosen tool. Claude Code goes
    through this session's relay, on `relay_port`."""
    name = f["name"]
    if tool == "claude":
        if relay_port is None:
            raise ValueError("Claude Code needs the session's relay port")
        exe = shutil.which("claude") or "claude"
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{relay_port}"
        # A placeholder key keeps Claude Code off the claude.ai sign-in, whose
        # model policy rejects local models. Costs nothing: the relay ignores it.
        env["ANTHROPIC_AUTH_TOKEN"] = "local"
        env["ANTHROPIC_API_KEY"] = ""
        # The local relay can't run Anthropic's server-side auto-mode checks;
        # keep auto mode's checks in Claude Code (they go to the local model).
        env["CLAUDE_CODE_AUTO_MODE_SERVER"] = "0"
        env["ANTHROPIC_MODEL"] = name
        for k in ("OPUS", "SONNET", "HAIKU", "FABLE"):
            env[f"ANTHROPIC_DEFAULT_{k}_MODEL"] = name
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = name
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(f["ctx"])
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(min(8192, f["ctx"] // 8))
        return [exe, "--model", name, "--settings", str(ROOT / "claude-settings.json")] + passthrough
    exe = shutil.which("opencode") or "opencode"
    addons, warnings = opencode_addons(env)
    for w in warnings:
        print(f"Note: {w}")
    env["OPENCODE_CONFIG_CONTENT"] = opencode_config(name, f["ctx"], addons)
    # A private backend per window: it closes with the window. The shared
    # background service outlives windows and restarts their unfinished chats.
    return [exe, "--standalone", str(folder)] + passthrough


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
    ap.add_argument("--update", action="store_true",
                    help="update Claude Code, OpenCode and LocalCoder, then check")
    a = ap.parse_args(argv)
    if a.update:
        import lc_update
        print("Updating...")
        for name, ok, detail in lc_update.run_updates():
            print(f"  {'OK  ' if ok else 'FAIL'}  {name}: {detail}")
        print("\nChecking the setup after updating:")
        passed = print_checks(run_checks())
        print("\nTo confirm everything still works with a model, run:\n"
              "  python tests/run_tests.py <model> --tools claude --tasks 1-explain")
        sys.exit(0 if passed else 1)
    if a.check:
        sys.exit(0 if print_checks(run_checks()) else 1)

    folder = Path(a.folder or os.getcwd())
    if not folder.is_dir():
        sys.exit(f"Folder not found: {folder}")

    lc_engine.start_engine()
    models = lc_engine.models()
    if not models:
        sys.exit("No models yet. Open Engine Manager (EngineManager.bat) and download one.")
    if a.model:
        f = next((m for m in models if m["name"] == a.model), None)
        if not f:
            sys.exit(f"Model not found: {a.model}. Names are listed in Engine Manager.")
    elif a.yes:
        f = models[0]  # the default model sorts first
    else:
        f = choose_model(models)
    check_memory(f)

    tool = a.tool or ("claude" if a.yes else None)
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
    relay = None
    if tool == "claude":
        # The relay folds Claude Code's mid-conversation system messages into
        # user text; many models' chat formats reject them otherwise.
        upstream = lc_engine.url()
        try:
            proc, port = start_relay(upstream)
        except OSError:
            sys.exit("The LocalCoder relay did not start.")
        relay = keep_relay_running(proc, port, upstream)
    cmd = build_command(tool, f, folder, list(passthrough), env, relay_port=port if relay else None)

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
        if relay:
            stop, current = relay
            stop.set()
            current[0].terminate()
    sys.exit(code)


if __name__ == "__main__":
    main()
