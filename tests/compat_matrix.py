"""Compatibility sweep: does LocalCoder work with this model at all?

For each model in the list, ONE AT A TIME (to keep disk use low):
  download -> let lc_launch make its big-memory version -> run the practice
  tasks in Claude Code and OpenCode -> record -> delete the model.

These are plumbing checks (tool calls parse, edits land, nothing crashes),
not a judgement of how good the model is.

Usage:
    python tests/compat_matrix.py                 # whole list
    python tests/compat_matrix.py qwen3:8b ...    # just these
    python tests/compat_matrix.py --keep          # don't delete afterwards
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import lc_launch  # noqa: E402
import run_tests  # noqa: E402

OUT = HERE / "COMPAT.md"

# family, why it's in the list
MODELS = [
    ("qwen3:8b", "Qwen3, Q4_K_M, thinking"),
    ("qwen3:8b-q8_0", "Qwen3, Q8_0 (light compression)"),
    ("hf.co/unsloth/Qwen3-8B-GGUF:Q3_K_M", "Qwen3, Q3_K_M from Hugging Face"),
    ("hf.co/unsloth/Qwen3-8B-GGUF:Q2_K", "Qwen3, Q2_K (heaviest compression)"),
    ("llama3.1:8b", "Llama 3.1, Q4_K_M"),
    ("mistral-nemo:12b", "Mistral, Q4_0"),
    ("granite3.3:8b", "IBM Granite, Q4_K_M"),
    ("phi4-mini:3.8b", "Microsoft Phi-4 mini, Q4_K_M"),
    ("gpt-oss:20b", "OpenAI gpt-oss, MXFP4, thinking"),
    ("deepseek-r1:8b", "DeepSeek-R1 distill, thinking"),
    ("gemma3:12b", "Gemma 3 (expected: no tool use)"),
]


def sh(cmd, timeout=None):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def record(line):
    if not OUT.exists():
        OUT.write_text("# Compatibility sweep\n\nPlumbing checks only (tool calls work, edits land, "
                       "no crashes), not model quality. Tasks: explain / fix-bug / add-function / rename.\n\n"
                       "| Date | Model | Notes | Quant | Tools | Thinks | Claude Code | OpenCode |\n"
                       "|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
    with OUT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def test_model(name, note, keep):
    today = datetime.date.today()
    print(f"\n=== {name}: downloading", flush=True)
    code, out = sh(["ollama", "pull", name], timeout=3 * 3600)
    if code != 0:
        record(f"| {today} | `{name}` | {note} | | | | download failed: {out.splitlines()[-1][:80]} | |")
        return
    made = []
    try:
        f = lc_launch.model_facts(name)
        if not f["tools"]:
            record(f"| {today} | `{name}` | {note} | {f['quant']} | no | {'yes' if f['thinking'] else 'no'} "
                   f"| skipped (no tool use; launcher warns) | skipped |")
            return
        g = lc_launch.prepare(f, auto_yes=True)
        if g["name"] != f["name"]:
            made.append(g["name"])
        results = {}
        for tool in ("claude", "opencode"):
            cells = []
            for task in run_tests.TASKS:
                status, secs = run_tests.run_one(tool, g["name"], task)
                cells.append(f"{task.split('-', 1)[1]} {status}")
                print(f"  {tool} {task}: {status} ({secs / 60:.1f} min)", flush=True)
            results[tool] = ", ".join(cells)
        record(f"| {today} | `{name}` | {note} | {f['quant']} | yes | {'yes' if f['thinking'] else 'no'} "
               f"| {results['claude']} | {results['opencode']} |")
    finally:
        if not keep:
            for m in made + [name]:
                sh(["ollama", "rm", m])
            print(f"=== {name}: removed", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    lc_launch.start_ollama()
    todo = [(m, n) for m, n in MODELS if not a.models or m in a.models]
    todo += [(m, "") for m in a.models if m not in dict(MODELS)]
    for name, note in todo:
        test_model(name, note, a.keep)


if __name__ == "__main__":
    main()
