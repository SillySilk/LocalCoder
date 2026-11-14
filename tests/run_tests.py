"""Run the 4 practice tasks against local models in Claude Code and/or OpenCode.

Usage:
    python tests/run_tests.py devstral-64k qwen3-coder-64k
    python tests/run_tests.py devstral-64k --tools claude

Each run gets a fresh copy of tests/practice in a temp folder, so runs never
affect each other. Results are appended to tests/RESULTS.md.
"""

import argparse
import datetime
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRACTICE = HERE / "practice"
RESULTS = HERE / "RESULTS.md"
TIMEOUT_S = 20 * 60

TASKS = {
    "1-explain": "Read inventory.py and explain in 3 short bullet points what each "
    "function does. Do not change any files.",
    "2-fix-bug": "The unit tests fail. Run `python -m unittest -q`, find the bug, "
    "fix it, and re-run the tests until they pass.",
    "3-add-function": "Add a function `restock(items, name, amount)` to inventory.py "
    "that increases the qty of the item with that name by amount and returns the "
    "updated item (raise KeyError if no item has that name). Add a unit test for "
    "it to test_inventory.py.",
    "4-rename": "Rename the function `low_stock` to `needs_reorder` everywhere in "
    "this project (definition, imports, calls and tests).",
}


def py(work, code):
    r = subprocess.run([sys.executable, "-c", code], cwd=work, capture_output=True, text=True)
    return r.returncode == 0


def check(task, work, output):
    src = "".join(p.read_text() for p in work.glob("*.py"))
    if task == "1-explain":
        unchanged = (work / "inventory.py").read_text() == (PRACTICE / "inventory.py").read_text()
        low = output.lower()
        return unchanged and "total_value" in low and "low_stock" in low
    if task == "2-fix-bug":
        r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=work, capture_output=True)
        return r.returncode == 0
    if task == "3-add-function":
        ok = py(work, "from inventory import restock\n"
                      "i=[{'name':'a','price':1,'qty':1}]\n"
                      "assert restock(i,'a',4)['qty']==5\n"
                      "try:\n restock(i,'zz',1); raise SystemExit(1)\n"
                      "except KeyError: pass")
        return ok and "restock" in (work / "test_inventory.py").read_text()
    if task == "4-rename":
        ok = py(work, "from inventory import needs_reorder\n"
                      "import report\n"
                      "assert needs_reorder([{'name':'x','price':1,'qty':1}])==['x']\n"
                      "assert 'Reorder: x' in report.build_report([{'name':'x','price':1,'qty':1}])")
        return ok and "low_stock" not in src
    raise ValueError(task)


ROOT = HERE.parent


def agent_cmd(tool, model, prompt, work):
    """Go through lc_launch.py, exactly like LocalCoder.bat / george do."""
    base = [sys.executable, str(ROOT / "lc_launch.py"), str(work),
            "--model", model, "--tool", tool, "--yes", "--"]
    if tool == "claude":
        return base + ["-p", prompt, "--permission-mode", "acceptEdits",
                       "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash(python:*),PowerShell(python:*)"]
    return base + ["run", prompt]


def run_one(tool, model, task):
    work = Path(tempfile.mkdtemp(prefix=f"lc-{task}-"))
    shutil.copytree(PRACTICE, work, dirs_exist_ok=True)
    env = None
    start = time.time()
    try:
        r = subprocess.run(agent_cmd(tool, model, TASKS[task], work), cwd=work, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT_S)
        output = r.stdout + r.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or "") if isinstance(e.stdout, str) else ""
        timed_out = True
    secs = time.time() - start
    passed = (not timed_out) and check(task, work, output)
    (HERE / "logs").mkdir(exist_ok=True)
    (HERE / "logs" / f"{tool}-{model.replace(':', '_')}-{task}.log").write_text(output, encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    status = "TIMEOUT" if timed_out else ("PASS" if passed else "FAIL")
    return status, secs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--tools", default="claude,opencode")
    ap.add_argument("--tasks", default=",".join(TASKS))
    a = ap.parse_args()

    if not RESULTS.exists():
        RESULTS.write_text("# Test results\n\n| Date | Tool | Model | Task | Result | Time |\n"
                           "|---|---|---|---|---|---|\n", encoding="utf-8")
    for model in a.models:
        for tool in a.tools.split(","):
            for task in a.tasks.split(","):
                status, secs = run_one(tool, model, task)
                line = (f"| {datetime.date.today()} | {tool} | {model} | {task} | "
                        f"{status} | {secs/60:.1f} min |")
                print(line, flush=True)
                with RESULTS.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")


if __name__ == "__main__":
    main()
