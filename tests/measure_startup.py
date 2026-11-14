"""Measure how much of the model's memory Claude Code uses before any real work.

Usage:
    python tests/measure_startup.py <model> [--lean]

Goes through the LocalCoder relay like LocalCoder.bat does. --lean also applies
the trimmed plugin list (claude-settings.json).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--lean", action="store_true")
    a = ap.parse_args()

    env = dict(os.environ)
    for k in ("OPUS", "SONNET", "HAIKU", "FABLE"):
        env[f"ANTHROPIC_DEFAULT_{k}_MODEL"] = a.model
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = a.model
    env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "8192"
    env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = "32768" if "-32k" in a.model else "65536"

    extra = ["-p", "Reply with the single word: ready", "--output-format", "stream-json", "--verbose"]
    if a.lean:
        extra += ["--settings", str(ROOT / "claude-settings.json")]
    sys.path.insert(0, str(ROOT / "tests"))
    from run_tests import RELAY_PORT, ensure_relay
    ensure_relay()
    env["OLLAMA_HOST"] = f"127.0.0.1:{RELAY_PORT}"

    work = tempfile.mkdtemp(prefix="lc-measure-")
    r = subprocess.run(["ollama", "launch", "claude", "--model", a.model, "--yes", "--", *extra],
                       cwd=work, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    init = result = None
    for line in r.stdout.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") == "system" and msg.get("subtype") == "init":
            init = msg
        if msg.get("type") == "result":
            result = msg
    if not init or not result:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("Could not read Claude Code output")

    u = result.get("usage", {})
    total = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    print(f"mode:        {'lean' if a.lean else 'full'}")
    print(f"tools:       {len(init.get('tools', []))}")
    print(f"mcp servers: {[s.get('name') for s in init.get('mcp_servers', [])]}")
    print(f"plugins:     {[p.get('name') for p in init.get('plugins', [])]}")
    print(f"skills:      {len(init.get('skills', []))}")
    print(f"start-up tokens used: {total}")
    print(f"reply:       {result.get('result', '').strip()[:80]}")


if __name__ == "__main__":
    main()
