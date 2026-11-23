# LocalCoder (George)

Run **Claude Code (or OpenCode) on local open-source models** through the shared AI engine run by [Engine Manager](https://github.com/SillySilk/EngineManager) (`C:\AI\EngineManager`). You keep Claude Code's tools, hooks, skills and CLAUDE.md, but the thinking happens on your own machine:

- **No usage limits.** Run as long as you like; nothing is metered.
- **Your model, your choice.** Pick a different model each time you start, to match the job. Press Enter for the default model (set in Engine Manager; currently Ternary Bonsai 27B uncensored).
- **Private.** Prompts and files stay on your machine.

Regular `claude` is unaffected. The local settings only apply inside the George window.

## Use it
1. Double-click `George.bat` (or drag a project folder onto it). After running `install-command.bat` once, you can also type `george` in any terminal to start in the folder you're in.
2. Pick a model (Enter = the default). If the engine isn't running, George starts it.
3. Pick a tool: **1 = Claude Code** or **2 = OpenCode**.

`lc_launch.py` does the work; the `.bat` just calls it. For scripts: `python lc_launch.py <folder> --model <name> --tool claude|opencode --yes [-- extra tool args]`. `--yes` with no `--model` uses the default model.

Switching models is just closing the window and starting again with a different pick. The engine keeps the model loaded until George's window closes (unless another George window uses it).

## Models
Models are managed in **Engine Manager**: `ModelManager.bat` (or the `models` command, if you made it with `install-command.bat models ModelManager.bat`) opens its page. Download, delete, set each model's memory size, and pick the default there.

## Requirements
- Windows, Python 3, Engine Manager with the Prism llama.cpp engine, and Claude Code and/or OpenCode.
- A model that can use tools, with at least 32k of memory; 64k is better (see below).

## The relay
- **Relay (`lc_proxy.py`).** Claude Code sends the skill list, the names of extra tools and plugin start-up notes as "system" messages in the middle of the conversation. Most models' chat formats reject those ("System message must be at the beginning"). The launcher starts a small relay on port 11435 that turns them into normal text the model can read. It runs in a minimised "LocalCoder relay" window and can be left open. It keeps a short log in `logs\relay.log`. Set `LC_RELAY_LOG` to a file path to also record everything that passes through it (large).
- **Trimmed plugin list (`claude-settings.json`).** Every plugin adds text the model must read before each task. This file (LocalCoder only) switches off heavy plugins. In testing, trimming cut start-up from ~29k to ~22.7k tokens.
- **claude.ai connectors** (Gmail, Drive, Calendar…) don't work here.

## Why these settings
- **Claude Code needs about 23k tokens just to start a task**, so models need at least 32k of memory, and 64k is better.
- The launcher sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` to the model's memory size so Claude Code compacts in time.
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192`: the default of 32k would eat half the memory.
- Every Claude model slot (opus/sonnet/haiku/subagents) points at the local model, so nothing tries to reach Anthropic.

## Tests
- `python -m pytest tests/unit`: quick checks; never loads a model.
- `python tests\run_tests.py <model> [--tools claude,opencode]` runs 4 small coding tasks on a real model. Results go to `tests\RESULTS.md`. Uses graphics memory.
- `python tests\measure_startup.py <model> [--lean]` shows how many tokens Claude Code uses before doing any work.

## Known issues
- The first reply of a session is slow (~30 s for Bonsai) while the model reads Claude Code's start-up text; later replies reuse it.
- Some models occasionally write a tool call as plain text instead of a real tool call; the agent then stops early.
- Claude Code prints `unrecognized_model` for local model names. It's harmless.
