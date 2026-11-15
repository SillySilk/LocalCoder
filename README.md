# LocalCoder

Run **Claude Code (or OpenCode) on local open-source models** through [Ollama](https://ollama.com). You keep Claude Code's tools, hooks, skills and CLAUDE.md, but the thinking happens on your own machine:

- **No usage limits.** Run as long as you like; nothing is metered.
- **Your model, your choice.** Pick a different model each time you start, to match the job: a coding model for code, a writing model (including uncensored ones) for fiction, a strong reasoning model for research. LocalCoder doesn't favour any of them.
- **Private.** Prompts and files stay on your machine.

Regular `claude` is unaffected. The local settings only apply inside the LocalCoder window.

## Use it
1. Double-click `George.bat` (or drag a project folder onto it). After running `install-command.bat` once, you can also type `george` in any terminal to start in the folder you're in.
2. Pick a model. LocalCoder asks Ollama what each model can do: models ready for agent work are listed first, and models that can't use tools are marked. If the model's memory (context) is too small, it offers to make a 64k version on the spot. That takes seconds and almost no disk space, because it reuses the same model files.
3. Pick a tool: **1 = Claude Code** or **2 = OpenCode**.

`lc_launch.py` does the work; the `.bat` just calls it. For scripts: `python lc_launch.py <folder> --model <name> --tool claude|opencode --yes [-- extra tool args]`.

Switching models is just closing the window and starting again with a different pick.

## Model Manager
A companion app for Ollama chores, so you never need to type Ollama commands. Double-click `ModelManager.bat`, or run `install-command.bat models ModelManager.bat` once and then type `models` in any terminal.

- **My models**: size, whether George can use it, memory size, whether it fits your graphics card, and whether it's loaded now. George's `-64k` versions are listed under the model they came from.
- **Search Hugging Face and download**: type a few words, pick a model, then pick a size. Models with no size your graphics card can run are hidden, and each result shows its best fit. Sizes are labelled *fits* or *tight*; sizes that are too big are tucked behind a "show more" choice. If Ollama can't download it, the app offers to download the file directly and import it.
- **Download by name**: paste a name from [ollama.com/search?c=tools](https://ollama.com/search?c=tools), or an `hf.co/...` link.
- **Import a .gguf file**: picks from your LM Studio and Downloads folders, or paste a path.
- After every download or import it checks whether George can use the model. If not, it copies the chat format from an installed model of the same kind that can.
- **Delete** shows how much disk space comes back, and warns when other models share the same files.
- **Unload** frees graphics memory.
- **Settings**: where models are saved (offers to move them), default memory size, and how long models stay loaded. The app restarts Ollama and checks that the change took. The models folder and memory size are saved in the Ollama app's own settings, because those win over Windows settings.

Tests: `python -m pytest tests/mm` (needs Ollama running and internet; downloads a 105 MB test model and deletes it afterwards; briefly restarts Ollama).

## Requirements
- Windows, [Ollama](https://ollama.com) 0.40 or newer, Python 3, and Claude Code and/or OpenCode installed.
- A model that supports **tool use** (`ollama show <model>` lists `tools` under Capabilities). Without it the model can't act as an agent.
- Enough memory for the model plus at least 32k of context; 64k is better (see below).

## Add a model
1. Either `ollama pull <model>` from the Ollama library, or download a `.gguf` (e.g. from Hugging Face).
   `ollama pull hf.co/...` sometimes fails on Hugging Face's download servers; a browser, LM Studio or `curl -L` works instead.
2. Start LocalCoder and pick it. The launcher creates the big-memory version for you when needed.
3. If you imported a `.gguf` by hand (`ollama create` with `FROM <file>.gguf`) and it shows "NO TOOL USE", Ollama didn't recognise its chat format. Copy `modelfiles\example-64k.Modelfile`, point `FROM` at the file, and set `RENDERER`/`PARSER` (or `TEMPLATE`) to match the model family; `ollama show <official-model-of-that-family> --modelfile` shows the right ones. Pulling with `ollama pull hf.co/<user>/<repo>:<quant>` usually avoids this.

The example Modelfile is set up for a Qwen3-Coder-family model (the one this was first tested with: an abliterated Qwen3-Coder-30B-A3B). Swap in whatever fits the work.

## Plugins and the relay
- **Relay (`lc_proxy.py`).** Claude Code sends the skill list, the names of extra tools and plugin start-up notes in a block that Ollama silently drops (about 10k tokens; found on Ollama 0.40.16). Without it the local model never sees your skills or extra tools. The launcher starts a small relay on port 11435 that moves that block where Ollama keeps it. It runs in a minimised "LocalCoder relay" window and can be left open. Set `LC_RELAY_LOG` to a file path to record what passes through it.
- **Trimmed plugin list (`claude-settings.json`).** Every plugin adds text the model must read before each task, and local models have far less memory than Claude. This file (passed with `--settings`, LocalCoder only) switches off heavy plugins and keeps a few useful ones. Edit it to match the plugins you have; names you don't have are ignored. In testing, trimming cut start-up from ~29k to ~22.7k tokens.
- **claude.ai connectors** (Gmail, Drive, Calendar…) don't work here. They need a Claude login, which the local setup replaces.
- `python tests\measure_startup.py <model> [--lean]` shows how many tokens Claude Code uses before doing any work.

## Why these settings
- **Claude Code needs about 23k tokens just to start a task** with a trimmed plugin list, so models need at least 32k of memory (`num_ctx`), and 64k is better.
- The launcher sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` so Claude Code knows the model's real memory size and compacts in time, instead of assuming a huge window and overflowing.
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192`: the default of 32k would eat half the memory.
- Every Claude model slot (opus/sonnet/haiku/subagents) points at the local model, so nothing tries to reach Anthropic.

## Test it
`python tests\run_tests.py <model> [--tools claude,opencode]` runs 4 small coding tasks (explain, fix a bug, add a function, rename) on a fresh copy of `tests\practice`. Results are appended to `tests\RESULTS.md`; full logs go to `tests\logs\` (not saved to git). The tasks are coding tasks, so they measure tool use and editing, not writing or research quality.

## Compatibility
`python tests\compat_matrix.py` downloads models one at a time, runs the practice tasks in both tools, records the result in `tests\COMPAT.md`, and deletes the model before the next one. It checks that a model works with LocalCoder, not how good it is.

## Known issues
- Some models occasionally write a tool call as plain text instead of a real tool call; the agent then stops early. Seen with Qwen3-Coder in OpenCode.
- Claude Code occasionally crashes at start-up with `I.name.startsWith` before sending any request (about 1 run in 20 in testing). Starting again works.
- Claude Code prints `unrecognized_model` for local model names. It's harmless.
