# LocalCoder

A second option alongside normal Claude Code: run **Claude Code (or OpenCode) on a local, uncensored model** through Ollama. It's for the occasional project Claude won't help with. Everyday work stays on regular `claude`.

## Use it
1. Type `george` in any terminal to work in the folder you're in, or double-click `LocalCoder.bat` (you can also drag a project folder onto it). The `george` command lives at `C:\Users\littl\.local\bin\george.cmd` and just calls the launcher.
2. Pick a model. Models ending in `-64k` are set up for long tasks.
3. Pick a tool: **1 = Claude Code** (your hooks, skills and CLAUDE.md all work) or **2 = OpenCode**.

These local settings only apply inside that window. A normal `claude` in any other terminal still uses real Claude.

## Current model
| Ollama name | What it is | Notes |
|---|---|---|
| `qwen3-coder-uncensored-64k` | Huihui Qwen3-Coder-30B-A3B, abliterated (uncensored), i1-Q4_K_M, 64k memory | ~25 GB when running. About 60% sits on the graphics card, the rest in system memory. Supports tools. |

Source: https://hf.co/mradermacher/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated-i1-GGUF (the downloaded .gguf was deleted after import; Ollama keeps its own copy, so re-download it only if you need to rebuild).

## Add a new model
1. Download the `.gguf` into `C:\AI\models\<author>\<model>\`.
   `ollama pull hf.co/...` can fail on Hugging Face's download servers. Use a browser, LM Studio or `curl -L` instead.
2. Copy `modelfiles\qwen3-coder-uncensored-64k.Modelfile` and change the `FROM` path.
   The `RENDERER` and `PARSER` lines must match the model family, otherwise tool use breaks. To see the right ones, run `ollama show <official-model> --modelfile`.
3. Run `ollama create <name>-64k -f modelfiles\<name>-64k.Modelfile`. It shows up in the launcher automatically.
4. Run `ollama show <name>-64k` and check that **tools** is listed under Capabilities. Without it the model can't act as an agent.

## Plugins and the relay
- **Relay (`lc_proxy.py`):** Claude Code sends your skill list, the names of extra tools and plugin start-up notes in a block that Ollama silently throws away (about 10k tokens; found 2026-11-14 on Ollama 0.40.16). The launcher starts a small relay on port 11435 that moves that block where Ollama keeps it. Without it the local model never sees your skills or extra tools. It runs in a minimised "LocalCoder relay" window and can be left open. To record what passes through it, start it with `LC_RELAY_LOG` set to a file path.
- **Trimmed plugin list (`claude-settings.json`):** LocalCoder turns off the heavy plugins (superpowers, creative-writing, frontend-design, context7, claude-md-management) and keeps code-review, feature-dev, Playwright and Forge Neo. That cuts start-up from ~29k to ~22.7k tokens. Edit the file to switch plugins on or off; it only affects LocalCoder, not normal `claude`.
- **claude.ai connectors** (Gmail, Drive, Calendar…) don't work here: they need your Claude login, which the local setup replaces.
- `python tests\measure_startup.py <model> [--lean]` shows how many tokens Claude Code uses before any work.

## Why these settings
- **Claude Code needs about 23k tokens just to start a task** with the trimmed plugin list (29k with everything on), measured from the Ollama log. Models need at least 32k of memory (`num_ctx`), and 64k is better.
- The launcher sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` so Claude Code knows the model's real memory size. Without it, Claude Code assumes 200k and would overflow.
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192`: the default of 32k would eat half the memory.
- Every Claude model slot (opus/sonnet/haiku/subagents) points at the local model, so nothing tries to reach Claude.

## Test it
`python tests\run_tests.py <model> [--tools claude,opencode]` runs 4 practice tasks: explain, fix a bug, add a function, rename. Each run gets a fresh copy of `tests\practice`. Results go to `tests\RESULTS.md`, and full logs to `tests\logs\` (not saved to git).
