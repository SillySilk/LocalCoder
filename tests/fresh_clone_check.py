"""Prove LocalCoder works from a fresh download, with no Claude login.

Clones the repo into a temp folder and, from the clone:
  1. runs `lc_launch.py --check`
  2. runs one practice task in Claude Code (skipped with --no-model), with
     CLAUDE_CONFIG_DIR pointing at a new empty folder, so there is no saved
     Claude login, no user plugins and no user settings.
Then checks the clone has no stray changes.

Usage:
    python tests/fresh_clone_check.py [--source URL_OR_PATH] [--branch B]
                                      [--model NAME | --no-model]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_SOURCE = "https://github.com/SillySilk/LocalCoder"


def run(cmd, **kw):
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    print((r.stdout + r.stderr).strip()[-3000:], flush=True)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--branch")
    ap.add_argument("--model", default="qwen3-coder-uncensored-64k")
    ap.add_argument("--no-model", action="store_true")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="lc-fresh-"))
    clone = tmp / "LocalCoder"
    failures = []
    try:
        cmd = ["git", "clone", "-q", a.source, str(clone)]
        if a.branch:
            cmd[3:3] = ["-b", a.branch]
        if run(cmd) != 0:
            sys.exit("clone failed")

        if run([sys.executable, str(clone / "lc_launch.py"), "--check"], cwd=clone) != 0:
            failures.append("--check failed")

        if not a.no_model:
            env = dict(os.environ)
            empty_config = tmp / "empty-claude-config"
            empty_config.mkdir()
            env["CLAUDE_CONFIG_DIR"] = str(empty_config)
            code = run([sys.executable, str(clone / "tests" / "run_tests.py"), a.model,
                        "--tools", "claude", "--tasks", "1-explain"], cwd=clone, env=env)
            results = (clone / "tests" / "RESULTS.md").read_text(encoding="utf-8")
            if code != 0 or "| PASS |" not in results.splitlines()[-1]:
                failures.append("practice task did not pass without a Claude login")

        status = subprocess.run(["git", "status", "--porcelain", "--", ".", ":!tests/RESULTS.md"],
                                cwd=clone, capture_output=True, text=True).stdout.strip()
        if status:
            failures.append(f"clone has stray changes:\n{status}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nFRESH CLONE CHECK FAILED:\n- " + "\n- ".join(failures))
        sys.exit(1)
    print("\nFresh clone check passed.")


if __name__ == "__main__":
    main()
