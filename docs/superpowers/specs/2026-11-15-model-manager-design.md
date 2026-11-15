# Model Manager: design

Date: 2026-11-15. Status: draft for approval.

## Why
George (LocalCoder) needs Ollama, but the user has never used Ollama. It runs in the background and is controlled by typed commands. The user is used to LM Studio, where downloading, loading and deleting models happen on a screen. Model Manager is a small companion app that does all the Ollama chores from plain numbered menus, so the user never has to learn Ollama commands.

## Goals
- Search Hugging Face for models and download one straight into Ollama, in the app (chosen: option A).
- Download by name (Ollama library name or `hf.co/...` link).
- Import a `.gguf` file already on disk (e.g. from LM Studio).
- List installed models with size, tool use (can George use it?), memory size, and whether loaded right now.
- Delete models; unload models to free graphics memory.
- Change Ollama settings: models folder, default memory size (context), how long models stay loaded.
- After any download or import, check tool use and fix "NO TOOL USE" automatically where possible.
- "Will it fit?" check against this PC's graphics card (RTX 4060 Ti, 16 GB) for search results and installed models.

## Non-goals
- Chatting with models (Ollama's own window does that; George does agent work).
- Searching the Ollama website (no official way to do it; rejected option B).
- Replacing George's model picker or its 64k-variant creation.

## Anti-goals
- Needing the user to type any Ollama command or understand its jargon.
- Silent failures: every failure says plainly what went wrong and what to do.
- Deleting anything without showing exactly what will go and asking first.

## Constraints
- Windows, Ollama 0.40.16+, Python 3 (3.14 installed). Standard library only, no extra add-ons, like George.
- Talks to Ollama through its local API (`http://127.0.0.1:11434`) like `lc_launch.py`, not by running `ollama` commands.
- Hugging Face public API for search and file sizes; no login required (gated models: say they need a login and skip).
- Real data only: no sample lists, no placeholders.
- Launcher `.bat` in the project root (`C:\AI\LocalCoder`), plus a typed command installed like `george`.

## Approaches considered
1. **Separate menu app in George's style (chosen).** Plain numbered menus, Python, standard library only, same folder as George. Simple and familiar, nothing new to install.
2. Menus added into George. One app, but clutters George's start-up, and the user asked for a companion.
3. Fancier screen (arrow keys, colours, panels). Nicer looking, but needs an add-on library and breaks more easily. Not worth it for a chores tool.

## Design

### Files
- `mm.py`: the app.
- `ModelManager.bat`: double-click launcher in the project root.
- `install-command.bat`: extended so it can also create the typed command for Model Manager (my call: command name `models`).
- George's shared Ollama helpers (`api`, `ollama_up`, `start_ollama`, `model_facts`) are reused, not copied; move them to a shared module if that's cleaner (builder's call).

### Main menu
```
===== Model Manager =====  (Ollama 0.40.16, 3 models, 16 GB graphics card)
  1) My models
  2) Search Hugging Face and download
  3) Download by name
  4) Import a .gguf file
  5) Delete a model
  6) Unload models (free graphics memory)
  7) Settings
  0) Quit
```
Every screen: numbered choices, Enter takes the shown default, `0` goes back. Plain words throughout ("memory" not "context", "can George use it" not "capabilities").

### 1) My models
Table: name, size on disk, tool use yes/no, memory size, fits graphics card / spills over, loaded now. George's `-64k` versions are shown next to the model they come from.

### 2) Search Hugging Face
- Type words ("qwen coder"). Search GGUF models, sorted by downloads; show top 20: name, downloads, last updated.
- Pick one: list its file sizes (quantisations) with size and a fit label: **fits** / **tight** / **too big, will be slow**. Mark the recommended one (largest that fits, my call).
- Download through Ollama (`hf.co/<user>/<repo>:<quant>`) with a progress bar.
- George's README says this sometimes fails on Hugging Face's servers. If it does, say so and offer to download the file directly (resumable) and then import it (step 4). Not silent: the user chooses.

### 3) Download by name
Paste a name (`qwen3:14b`) or `hf.co/...` link. Same progress bar and tool check. Link to `ollama.com/search?c=tools` is shown for browsing.

### 4) Import a .gguf
- Pick a file: the app lists `.gguf` files found in the LM Studio models folder (if present) and the Downloads folder, or paste a path.
- Ask for a short name (suggested from the file name).
- Upload to Ollama and create the model, then run the tool check.

### Tool check and fix (after 2, 3 and 4)
- Ask Ollama whether the new model has tool use.
- If not, and the model family is known (e.g. Qwen3, Llama, Granite), recreate it with the matching chat format taken from that family's official model, as the README describes. Report the result.
- If it can't be fixed: say George can't use it as an agent, and offer to keep it (chat only) or delete it.

### 5) Delete
Pick one or more models. Show what goes and how much disk space comes back. If other models share the same files (George's `-64k` versions), say so: space only comes back when all of them are deleted. Confirm with `y`.

### 6) Unload
Show loaded models and how much graphics memory each uses; unload one or all.

### 7) Settings
- Models folder, default memory size, how long models stay loaded (e.g. 5 min, 30 min, forever).
- Saved as Windows user settings that Ollama reads on start, then the app restarts Ollama and confirms the change took.
- Changing the models folder offers to move existing models there first, showing the space needed. Ask before moving.

### Errors
- Ollama not running: start it (as George does); if that fails, say so plainly.
- No internet / Hugging Face down: say so; local features still work.
- Not enough disk space: checked before downloading, with the amount needed.

## Testing
- Automated tests against the real local Ollama and real Hugging Face, using a tiny real model (e.g. a ~100 MB GGUF) for download, import, tool check and delete. No fake data.
- Fit labels tested against the measured graphics card.

## Left to the builder
- Exact fit maths (file size plus memory overhead for the chosen context).
- Family to chat-format mapping for the auto-fix.
- Whether shared helpers move to a common module.
- Command name `models` and file names are my calls; the user can rename them.
