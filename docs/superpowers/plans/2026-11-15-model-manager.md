# Model Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A menu-driven companion app to George that searches Hugging Face, downloads, imports, deletes and unloads Ollama models, and changes Ollama settings, all without the user typing Ollama commands.

**Architecture:** Small standard-library Python modules next to `lc_launch.py`: one shared Ollama module (moved out of George), one for Hugging Face, one for "will it fit / disk space", one for the tool check and fix, one for settings, and `mm.py` holding only menus. Everything talks to Ollama's local API and Hugging Face's public API.

**Tech Stack:** Python 3.14 standard library (`urllib`, `json`, `hashlib`, `winreg`, `ctypes`, `shutil`, `subprocess`), pytest for tests, Ollama 0.40.16 API, Hugging Face Hub API.

**Spec:** `docs/superpowers/specs/2026-11-15-model-manager-design.md`

## Global Constraints

- Windows, Ollama 0.40.16+, Python 3. Standard library only in the app (pytest only for tests).
- Talk to Ollama through `http://127.0.0.1:11434` (`LC_OLLAMA_URL` overrides, as George does), never by running `ollama` commands. Exception: starting/stopping the Ollama app itself.
- Real data only: no sample lists, placeholders or invented numbers. If a value can't be measured (e.g. no `nvidia-smi`), say "unknown" and skip what depends on it.
- Every failure is reported in plain words with what to do next. Nothing is deleted or moved without showing what and asking `y`.
- Plain words in all user-facing text: "memory" not "context", "can George use it" not "capabilities", "graphics memory" not "VRAM".
- Launcher `.bat` in the project root `C:\AI\LocalCoder`. Typed command name: `models`.
- Tests run against the real local Ollama and real Hugging Face, using `hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M` (105,454,432 bytes). Tests delete every model they create.
- George must keep working after every task: `python lc_launch.py --help` exits 0.

## Review Focus

1. **Names with and without `:latest`** (George's `granite3.3-8b-64k:latest`, typed as `granite3.3-8b-64k`): list, delete, unload and the shared-files check treat them as the same model. Test in Task 4.
2. **Split GGUF files** (`*-00001-of-00003.gguf`): grouped into one size choice with the total size, marked "comes in pieces, not supported yet" and not offered for download. Test in Task 2.
3. **Gated or missing Hugging Face repos** (HTTP 401/403/404): a plain message ("needs a Hugging Face login" / "not found"), back to the menu, no crash. Test in Task 2.
4. **Bad menu input** (letters, blank, out-of-range numbers, Ctrl+C, pasted paths wrapped in quotes): re-ask or go back, never a traceback; quotes stripped from paths. Test in Task 7.
5. **Ollama not running or stopping mid-session:** start it like George does; if a call fails with connection refused, say "Ollama stopped â€” restarting it" once, then report plainly if that fails. Test in Task 1.

---

### Task 1: Shared Ollama module

Move George's Ollama helpers into a shared module and add the operations Model Manager needs.

**Files:**
- Create: `lc_ollama.py`
- Modify: `lc_launch.py` (delete `OLLAMA`, `api`, `ollama_up`, `start_ollama`, `model_facts`; import them from `lc_ollama`)
- Create: `tests/mm/conftest.py`, `tests/mm/test_ollama.py`

**Interfaces:**
- Produces (in `lc_ollama.py`):
  - `OLLAMA: str`, `api(path, body=None, base=OLLAMA, timeout=30) -> dict` (unchanged), `ollama_up() -> bool`, `start_ollama() -> None`, `model_facts(name) -> dict` (unchanged keys).
  - `class OllamaError(Exception)`: carries a plain-words message.
  - `call(path, body=None, method=None, timeout=30) -> dict`: like `api` but on connection refused runs `start_ollama()` once and retries; HTTP errors become `OllamaError` with Ollama's `error` text.
  - `installed() -> list[dict]`: `/api/tags` models (`name`, `size`, `digest`, `modified_at`).
  - `canonical(name: str) -> str`: adds `:latest` when no tag.
  - `pull(name: str, on_progress: Callable[[str, int, int], None]) -> None`: streams `/api/pull`; calls `on_progress(status, completed, total)`; raises `OllamaError` on an `error` line.
  - `delete(name: str) -> None`: `DELETE /api/delete`.
  - `running() -> list[dict]`: `/api/ps` models (`name`, `size_vram`).
  - `unload(name: str) -> None`: `/api/generate` with `{"model": name, "keep_alive": 0}`.
- Produces (in `tests/mm/conftest.py`): `TINY = "hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M"`; session fixture `tiny_model` that pulls `TINY` if missing and yields its name, deleting it at session end only if this session pulled it.

- [ ] **Step 1: Write failing tests** in `tests/mm/test_ollama.py`:
  - `test_canonical`: `canonical("a") == "a:latest"`, `canonical("a:8b") == "a:8b"`, `canonical("hf.co/u/r:Q4_K_M") == "hf.co/u/r:Q4_K_M"`.
  - `test_pull_reports_progress(tiny_model)`: `canonical(tiny_model)` in `[m["name"] for m in installed()]` (pull happened in fixture; this test re-pulls and records `on_progress` calls; asserts at least one call with `total > 0` and the last status `== "success"`).
  - `test_unload(tiny_model)`: run one `/api/generate` with `{"model": tiny_model, "prompt": "hi", "stream": False}`; assert it's in `running()`; `unload(tiny_model)`; assert it's no longer in `running()` (poll up to 10 s).
  - `test_call_bad_model_raises`: `call("/api/show", {"model": "no-such-model-mm"})` raises `OllamaError` whose message contains `"not found"`.
  - `test_george_still_starts`: `subprocess.run([sys.executable, "lc_launch.py", "--help"]).returncode == 0`.
  - `test_call_restarts_once(monkeypatch)`: point `lc_ollama.OLLAMA` at `http://127.0.0.1:1` and replace `start_ollama` with a counter; `call("/api/version")` raises `OllamaError` containing `"Ollama stopped"` and the counter is exactly 1.
- [ ] **Step 2: Run** `python -m pytest tests/mm/test_ollama.py -v` from `C:\AI\LocalCoder`. Expected: FAIL, `ModuleNotFoundError: lc_ollama`.
- [ ] **Step 3: Create `lc_ollama.py`** with the moved helpers and the new functions above; update `lc_launch.py` imports. `pull` reads the response line by line (`for line in resp`), JSON per line.
- [ ] **Step 4: Run** the same command. Expected: 6 passed.
- [ ] **Step 5: Commit** `lc_ollama.py lc_launch.py tests/mm/` â€” "Move Ollama helpers to a shared module and add pull, delete, unload".

### Task 2: Hugging Face search and files

**Files:**
- Create: `mm_hf.py`, `tests/mm/test_hf.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (in `mm_hf.py`):
  - `class HFError(Exception)`: plain-words message ("needs a Hugging Face login", "not found", "can't reach Hugging Face").
  - `search(words: str, limit: int = 20) -> list[dict]`: `GET https://huggingface.co/api/models?search=<words>&filter=gguf&sort=downloads&direction=-1&limit=<limit>`; each item `{"repo", "downloads", "updated", "gated"}`.
  - `quant_of(filename: str) -> str | None`: quant label from a GGUF filename, upper-cased (`Q4_K_M`, `IQ3_XS`, `Q8_0`, `F16`, `BF16`, `Q4_0_4_4`), `None` if none.
  - `quants(repo: str) -> list[dict]`: from `GET https://huggingface.co/api/models/<repo>/tree/main?recursive=true`, `.gguf` files grouped by quant: `{"quant", "files": [paths], "size": total_bytes, "split": bool}`, sorted by size. Skip `mmproj` files.
  - `ollama_name(repo: str, quant: str) -> str`: `f"hf.co/{repo}:{quant}"`.
  - `download_file(repo, path, dest_dir, on_progress) -> Path`: `GET https://huggingface.co/<repo>/resolve/main/<path>`, writes `<dest_dir>/<basename>.part`, resumes with a `Range` header if `.part` exists, renames when complete.
  - HTTP 401/403 â†’ `HFError("needs a Hugging Face login")`; 404 â†’ `HFError("not found")`; `URLError` â†’ `HFError("can't reach Hugging Face")`.

- [ ] **Step 1: Write failing tests** in `tests/mm/test_hf.py`:
  - `test_search_finds_tiny`: `"bartowski/SmolLM2-135M-Instruct-GGUF"` in `[r["repo"] for r in search("SmolLM2-135M-Instruct")]`.
  - `test_quant_of`: `"SmolLM2-135M-Instruct-Q4_K_M.gguf" â†’ "Q4_K_M"`, `"x-IQ3_XS.gguf" â†’ "IQ3_XS"`, `"x-f16.gguf" â†’ "F16"`, `"x-Q4_0_4_4.gguf" â†’ "Q4_0_4_4"`, `"readme.gguf" â†’ None`.
  - `test_quants_sizes`: in `quants("bartowski/SmolLM2-135M-Instruct-GGUF")`, the `Q4_K_M` entry has `size == 105454432` and `split is False`.
  - `test_split_grouping`: `quants` on a real repo with split files (find one with `search` for a 70B GGUF, e.g. `bartowski/Llama-3.3-70B-Instruct-GGUF`, and confirm it has `-00001-of-` files before writing the assertion) has at least one entry with `split is True` and `size` equal to the sum of its files.
  - `test_missing_repo`: `quants("PanPDX/does-not-exist-mm")` raises `HFError` with `"not found"`.
  - `test_download_resumes(tmp_path)`: start `download_file` for the tiny Q4_K_M file, stop after ~10 MB by raising from `on_progress`; call again; final file size `== 105454432`; no `.part` left.
- [ ] **Step 2: Run** `python -m pytest tests/mm/test_hf.py -v`. Expected: FAIL, `ModuleNotFoundError: mm_hf`.
- [ ] **Step 3: Implement `mm_hf.py`** as above. Split detection: filename matches `-\d{5}-of-\d{5}\.gguf$`; group key is the quant plus the name without the split suffix.
- [ ] **Step 4: Run** the same command. Expected: 6 passed.
- [ ] **Step 5: Commit** `mm_hf.py tests/mm/test_hf.py` â€” "Add Hugging Face search, size list and resumable download".

### Task 3: Will it fit, and disk space

**Files:**
- Create: `mm_fit.py`, `tests/mm/test_fit.py`

**Interfaces:**
- Consumes: nothing.
- Produces (in `mm_fit.py`):
  - `graphics_memory() -> int | None`: bytes, from `nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits` (MiB Ã— 1024Â²), first GPU; `None` if `nvidia-smi` is missing or fails.
  - `fit_label(size: int, vram: int | None) -> str`: `"fits"` if `size <= 0.80 * vram`, `"tight"` if `size <= vram`, else `"too big, will be slow"`; `""` if `vram is None`.
  - `recommended(quants: list[dict], vram: int | None) -> str | None`: quant of the largest non-split entry with label `"fits"`; if none fits, the smallest non-split entry; `None` if `vram is None` or no non-split entries.
  - `free_space(folder: Path) -> int` (`shutil.disk_usage(...).free`), `human(n: int) -> str` (`"105 MB"`, `"4.9 GB"`, base 1000, one decimal for GB).

- [ ] **Step 1: Write failing tests:** `test_graphics_memory_measured`: on this PC returns `16380 * 1024**2` (skip if `shutil.which("nvidia-smi")` is None). `test_fit_label`: with `vram = 16 * 10**9`: `12e9 â†’ "fits"`, `14e9 â†’ "tight"`, `18e9 â†’ "too big, will be slow"`, `vram None â†’ ""`. `test_recommended`: with entries `Q4 (9e9)`, `Q6 (12e9)`, `Q8 (16.5e9)`, split `F16 (30e9)` and `vram 16e9` â†’ `"Q6"`; with `vram 4e9` â†’ `"Q4"`. `test_human`: `105454432 â†’ "105 MB"`, `4_900_000_000 â†’ "4.9 GB"`.
- [ ] **Step 2: Run** `python -m pytest tests/mm/test_fit.py -v`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement `mm_fit.py`.**
- [ ] **Step 4: Run** the same command. Expected: 4 passed.
- [ ] **Step 5: Commit** â€” "Add graphics-memory fit labels and disk space helpers".

### Task 4: Shared files and what a delete frees

**Files:**
- Create: `mm_store.py`, `tests/mm/test_store.py`

**Interfaces:**
- Consumes: `lc_ollama.canonical`, `lc_ollama.installed`, `lc_ollama.delete`, `lc_ollama.call` (Task 1); `tiny_model` fixture.
- Produces (in `mm_store.py`):
  - `models_dir() -> Path`: user env `OLLAMA_MODELS` (read from `HKCU\Environment` via `winreg`, then `os.environ`) else `~/.ollama/models`.
  - `manifest_path(name: str) -> Path`: under `models_dir()/manifests`: `hf.co/u/r:tag â†’ hf.co/u/r/tag`; `user/x:tag â†’ registry.ollama.ai/user/x/tag`; `x:tag â†’ registry.ollama.ai/library/x/tag`; untagged â†’ `latest`.
  - `layers(name: str) -> dict[str, int]`: digest â†’ size for `config` plus all `layers` in the manifest.
  - `delete_plan(names: list[str]) -> dict`: `{"freed": bytes only used by these models, "shared_with": sorted names of other installed models sharing any of their layers}`.

- [ ] **Step 1: Write failing tests:**
  - `test_manifest_path_forms`: the three forms above plus `"granite3.3-8b-64k"` â†’ `.../library/granite3.3-8b-64k/latest`.
  - `test_delete_plan_shared(tiny_model)`: create `mm-test-copy` with `call("/api/create", {"model": "mm-test-copy", "from": tiny_model, "parameters": {"num_ctx": 4096}, "stream": False})`; `delete_plan(["mm-test-copy"])["shared_with"]` contains `canonical(tiny_model)` and `freed` is under 1 MB; `delete_plan([tiny_model, "mm-test-copy"])["freed"] >= 105454432`. Delete `mm-test-copy` in `finally`.
  - `test_latest_and_bare_match(tiny_model)`: `delete_plan(["mm-test-copy"]) == delete_plan(["mm-test-copy:latest"])` (same setup).
- [ ] **Step 2: Run** `python -m pytest tests/mm/test_store.py -v`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement `mm_store.py`.** Read manifests from disk; run all names through `canonical` first.
- [ ] **Step 4: Run.** Expected: 3 passed.
- [ ] **Step 5: Commit** â€” "Work out disk space freed and shared files before deleting".

### Task 5: Import a .gguf, plus the tool check and fix

**Files:**
- Create: `mm_import.py`, `tests/mm/test_import.py`

**Interfaces:**
- Consumes: `lc_ollama.call`, `lc_ollama.model_facts`, `lc_ollama.installed` (Task 1); `mm_hf.download_file` (Task 2) in the test fixture.
- Produces (in `mm_import.py`):
  - `find_ggufs() -> list[Path]`: `.gguf` files (excluding `mmproj*`) under `~/.lmstudio/models` and `~/Downloads`, if those folders exist, newest first.
  - `clean_path(text: str) -> Path`: strips spaces and surrounding `"`/`'`.
  - `suggest_name(path: Path) -> str`: lowercase file stem, spaces â†’ `-`.
  - `import_gguf(path: Path, name: str, on_progress) -> str`: sha256 the file (progress), `HEAD /api/blobs/sha256:<hex>`; if missing, `POST` the file body there (streamed, progress); then `/api/create` `{"model": name, "files": {path.name: "sha256:<hex>"}, "stream": False}`; returns `canonical(name)`.
  - `fix_tools(name: str) -> str | None`: if `model_facts(name)["tools"]` is already true, returns `name`. Otherwise finds an installed model with the same `general.architecture` and `tools` true (a "donor"), recreates `name` from itself copying the donor's `template`, and `renderer`/`parser` when the donor's `/api/show` has them; returns the donor's name if the result now has tools, else `None`.
  - `missing_family_hint(name: str) -> str`: plain sentence naming the architecture and suggesting `ollama.com/search?c=tools` for an official model of that family.

- [ ] **Step 1: Probe** whether `/api/create` accepts `renderer` and `parser`: create a throwaway copy of `qwen3-coder-uncensored-64k` with `"renderer": "qwen3-coder", "parser": "qwen3-coder"` and check `/api/show` returns them; delete it. Record the result as a comment in `mm_import.py`. If not accepted, copy `template` only.
- [ ] **Step 2: Write failing tests** (session fixture `tiny_gguf` downloads the Q4_K_M file once to a temp dir with `download_file`):
  - `test_clean_path`: `clean_path('  "C:\\a b\\x.gguf" ')` == `Path("C:/a b/x.gguf")`.
  - `test_import_gguf(tiny_gguf)`: `import_gguf(tiny_gguf, "mm-test-import", cb)` returns `"mm-test-import:latest"`, which appears in `installed()`.
  - `test_fix_tools_copies_from_donor(tiny_gguf)`: create `mm-test-good` from the imported blob with `granite3.3:8b`'s `/api/show` `template` (has tool support); create `mm-test-bad` with `"template": "{{ .Prompt }}"`; assert `model_facts("mm-test-bad")["tools"] is False`; `fix_tools("mm-test-bad") == "mm-test-good:latest"`; now tools is True.
  - `test_fix_tools_no_donor(tiny_gguf)`: with `mm-test-good` deleted, `fix_tools("mm-test-bad") is None`.
  - All `mm-test-*` models deleted in fixture teardown.
- [ ] **Step 3: Run** `python -m pytest tests/mm/test_import.py -v`. Expected: FAIL, module missing.
- [ ] **Step 4: Implement `mm_import.py`.**
- [ ] **Step 5: Run.** Expected: 4 passed.
- [ ] **Step 6: Commit** â€” "Import .gguf files into Ollama and fix missing tool use".

### Task 6: Settings

**Files:**
- Create: `mm_settings.py`, `tests/mm/test_settings.py`

**Interfaces:**
- Consumes: `lc_ollama.start_ollama`, `lc_ollama.ollama_up` (Task 1); `mm_store.models_dir` (Task 4); `mm_fit.free_space` (Task 3).
- Produces (in `mm_settings.py`):
  - `KEYS = {"models_folder": "OLLAMA_MODELS", "memory": "OLLAMA_CONTEXT_LENGTH", "stay_loaded": "OLLAMA_KEEP_ALIVE"}`.
  - `read() -> dict[str, str | None]`: from `HKCU\Environment`.
  - `write(key: str, value: str | None) -> None`: sets or deletes the value, then broadcasts `WM_SETTINGCHANGE` (`SendMessageTimeoutW(HWND_BROADCAST, 0x1A, 0, "Environment", ...)`).
  - `restart_ollama() -> None`: `taskkill /IM "ollama app.exe" /F` and `taskkill /IM ollama.exe /F`, wait until `ollama_up()` is false, then start the Ollama app; the app is started with the updated environment (build `env` from `read()` merged onto `os.environ`, launch `ollama app.exe` with `subprocess.Popen(..., env=env)`).
  - `server_config(after: float) -> dict[str, str]`: the `env="map[...]"` from the newest `msg="server config"` line in `%LOCALAPPDATA%\Ollama\server.log` written after `after` (epoch seconds), parsed into a dict; waits up to 30 s.
  - `apply(key, value) -> bool`: `write`, `restart_ollama`, then True if `server_config(...)[KEYS[key]]` equals `value` (`OLLAMA_CONTEXT_LENGTH` unset shows `0`).
  - `move_models(src: Path, dst: Path, on_progress) -> None`: refuse with a plain message if `free_space(dst)` is less than the size of `src`; moves `blobs` and `manifests` into `dst`. Caller stops Ollama first.
- Menu choices (used in Task 7): memory `4k, 8k, 16k, 32k, 64k, 128k` â†’ `4096â€¦131072`; stay loaded `5 min, 30 min, 2 hours, forever` â†’ `5m, 30m, 2h, -1`.

- [ ] **Step 1: Write failing tests:**
  - `test_apply_keep_alive`: save `read()["stay_loaded"]`; `apply("stay_loaded", "30m") is True`; restore the saved value with `apply` in `finally`.
  - `test_server_config_parses`: after the apply above, the parsed dict has key `OLLAMA_KEEP_ALIVE`.
  - `test_move_models_refuses_when_full(tmp_path)`: monkeypatch `mm_settings.free_space` to return 0 and assert `move_models` raises with `"not enough space"` and nothing moved.
  - `test_move_models_moves(tmp_path)`: real files in `tmp_path/src/blobs` and `src/manifests`; after `move_models`, they exist under `dst` and not under `src`.
- [ ] **Step 2: Run** `python -m pytest tests/mm/test_settings.py -v`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement `mm_settings.py`.**
- [ ] **Step 4: Run.** Expected: 4 passed. Ollama is running afterwards with the original keep-alive.
- [ ] **Step 5: Commit** â€” "Change Ollama settings and restart it to apply them".

### Task 7: Menus, launcher and command

**Files:**
- Create: `mm.py`, `ModelManager.bat`, `tests/mm/test_menus.py`
- Modify: `install-command.bat` (second optional argument: target launcher), `README.md` (new "Model Manager" section)

**Interfaces:**
- Consumes: everything above.
- Produces: `mm.py` with `main()`, plus `ask_number(prompt: str, count: int, default: int | None) -> int | None` (re-asks on letters/out-of-range, returns `None` for `0`, the default on blank) and `ask_yes(prompt: str) -> bool`; `Ctrl+C` on any screen returns to the main menu, and on the main menu exits cleanly.

Screens follow the spec section "Design" exactly (main menu text verbatim, including the header line with Ollama version, model count and graphics memory). Specifics:
- **My models:** columns name, size (`human`), can George use it (yes/no), memory (`num_ctx` as `64k` or `default`), fit (`fit_label`), loaded now. A `-64k` model is listed directly under the model it was made from.
- **Search:** results numbered with downloads and updated date; choosing one lists `quants` with size, fit label, `(recommended)` on `recommended(...)`, split ones shown as "comes in pieces, not supported yet" and not selectable. Disk check before download (`free_space(models_dir()) >= size`, else say how much is needed). Download with `pull(ollama_name(...))`. If `pull` fails, show the error and offer `ask_yes("Download the file directly instead, then import it?")` â†’ `download_file` to `~/Downloads` then `import_gguf`.
- **Download by name:** paste a name; shows `https://ollama.com/search?c=tools` for browsing.
- **Import:** numbered list from `find_ggufs()` plus "paste a path"; name from `suggest_name`, editable.
- **After 2, 3, 4:** `fix_tools`; report "George can use it", "Fixed it using <donor>'s chat format", or `missing_family_hint` with `ask_yes("Keep it for chat only?")` (no â†’ delete).
- **Delete:** multi-pick (`1,3`), show names, `delete_plan` freed space and shared-with note, `ask_yes`.
- **Unload:** `running()` with graphics memory each, unload one or all.
- **Settings:** current values from `read()`; models folder change offers `move_models` (stops Ollama first) then `apply`; report whether the change took.
- **Progress:** one line, rewritten in place: `Downloading  45% [#########...........]  4.1 GB / 9.0 GB`.

`ModelManager.bat`: same shape as `LocalCoder.bat` (Python check, then `python "%~dp0mm.py"`, `pause` on error). `install-command.bat models ModelManager.bat` creates `models.cmd`; with no second argument it keeps today's behaviour.

- [ ] **Step 1: Write failing tests** in `tests/mm/test_menus.py` (feed input with `monkeypatch.setattr("builtins.input", ...)`):
  - `test_ask_number_reasks`: inputs `["x", "9", "", "2"]` with `count=3, default=None` â†’ returns `2`, no exception.
  - `test_ask_number_default`: input `[""]` with `default=1` â†’ `1`; input `["0"]` â†’ `None`.
  - `test_ctrl_c_on_main_menu_exits`: input raising `KeyboardInterrupt` â†’ `main()` returns without a traceback.
  - `test_launcher_runs`: `subprocess.run(["cmd", "/c", "ModelManager.bat"], input="0\n", text=True, timeout=60)` exits 0 and its output contains `"===== Model Manager ====="`.
- [ ] **Step 2: Run** `python -m pytest tests/mm/test_menus.py -v`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement `mm.py`, `ModelManager.bat`, the `install-command.bat` change, and the README section** (what it does, how to start it, `install-command.bat models ModelManager.bat`).
- [ ] **Step 4: Run** the full suite: `python -m pytest tests/mm -v`. Expected: all pass.
- [ ] **Step 5: Hand check** in a visible window: run `ModelManager.bat`, open each menu with the tiny model installed, search "SmolLM2 135M", download Q4_K_M, confirm the tool check message, unload, delete. Then run `install-command.bat models ModelManager.bat` and confirm `models` opens it from a new terminal.
- [ ] **Step 6: Commit** â€” "Add Model Manager menus, launcher and models command".
