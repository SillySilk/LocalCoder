# Model Manager Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the eleven minor problems the Model Manager final review deferred, plus one stale launcher comment.

**Architecture:** Small, local changes in the existing modules (`mm.py`, `mm_hf.py`, `mm_store.py`, `mm_settings.py`, `mm_import.py`, `lc_ollama.py`, `install-command.bat`). No new files except tests.

**Tech Stack:** Python 3.14 standard library, pytest, Ollama 0.40.16 API, Hugging Face API.

**Spec:** `docs/superpowers/specs/2026-11-15-model-manager-design.md` (behaviour), plus the deferred-minor list from the 2026-11-15 final review, copied into each task below.

## Global Constraints

- Everything in the Model Manager spec's Global Constraints still holds: standard library only, real data only, plain words, nothing deleted or moved without asking.
- Tests run against real Ollama and Hugging Face where a real case exists; fake data only for cases that can't be produced safely (full disks, locked files).
- `python -m pytest tests/mm -q` stays green after every task, and `python lc_launch.py --help` exits 0.

## Review Focus

1. A pull tag with a prefix (`hf.co/unsloth/...:UD-Q4_K_XL`) must still download through Ollama. Test in Task 4.
2. Same-drive detection on paths with different letter case (`c:\x` vs `C:\y`). Test in Task 5.
3. A `.part` file larger than the real file (a different file was swapped in on the server) restarts cleanly. Test in Task 2.
4. Unloading a model that unloads itself between listing and the click doesn't report an error. Test in Task 3.
5. A system-wide `OLLAMA_MODELS` and an app setting both present: the app setting wins, matching what Ollama does. Test in Task 5.

---

### Task 1: Input and start-up

**Files:** Modify `mm.py`, `install-command.bat`. Test `tests/mm/test_menus.py`.

- [ ] **Step 1: Failing tests:** `test_ask_number_rejects_superscript`: inputs `["²", "1"]` → `1`, no exception. `test_ctrl_c_during_startup`: monkeypatch `mm.start_ollama` to raise `KeyboardInterrupt`; `mm.main()` returns without raising.
- [ ] **Step 2: Run** `python -m pytest tests/mm/test_menus.py -q`. Expected: 2 failed.
- [ ] **Step 3: Implement:** `ask_number` uses `text.isdecimal()` and `text.isascii()`. In `main()`, wrap `start_ollama()` and `graphics_memory()` so `KeyboardInterrupt`/`EOFError` returns quietly. In `install-command.bat`, the generated comment reads `REM Opens %TARGET% in %~dp0` (no "LocalCoder").
- [ ] **Step 4: Run** the same. Expected: all pass.
- [ ] **Step 5: Commit** — "Reject non-ASCII digits and allow Ctrl+C at start-up".

### Task 2: Downloads and imports

**Files:** Modify `mm_hf.py`, `mm.py`, `mm_import.py`. Test `tests/mm/test_hf.py`, `tests/mm/test_import.py`, `tests/mm/test_menus.py`.

**Interfaces:** Produces `mm_import.Throttle(on_progress, every_bytes=64 << 20)`: callable with `(step, done, total)` that forwards only when `done` has advanced `every_bytes` since the last forward, or `done == total`.

- [ ] **Step 1: Failing tests:**
  - `test_complete_part_file_finishes(tmp_path)`: download the tiny Q4_K_M file fully, rename it to `.part`; `download_file` returns the final path with size 105454432 and no HTTP 416 error.
  - `test_oversized_part_restarts(tmp_path)`: write a 200 MB `.part` (bigger than the real file); `download_file` ends with the right size.
  - `test_throttle`: feeding 1,000 calls of 8 KB each (8 MB total, `total` = 8 MB) through `Throttle(cb, every_bytes=1 << 20)` makes `cb` run 8 or 9 times, and the last call has `done == total`.
  - `test_fallback_checks_downloads_space(monkeypatch)`: with `free_space` returning 0 for the Downloads folder, the direct-download fallback in `download_model` prints "Not enough disk space" and calls neither `download_file` nor `import_gguf`.
- [ ] **Step 2: Run** the three test files. Expected: 4 failed.
- [ ] **Step 3: Implement:**
  - `download_file`: before asking for a range, `HEAD` the file to learn its size. If `.part` is the full size, rename it and return. If it's bigger, delete it and start over.
  - `import_gguf` and `_upload` wrap `on_progress` in `Throttle`.
  - `download_model` fallback: needs `size` free in `~/Downloads` **and** `size` free in `models_dir()`. If they're on the same drive, it needs `2 × size` free there.
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit** — "Finish complete downloads, throttle import progress, check download space".

### Task 3: Delete note and unload all

**Files:** Modify `mm_store.py`, `mm.py`, `lc_ollama.py`. Test `tests/mm/test_store.py`, `tests/mm/test_ollama.py`, `tests/mm/test_menus.py`.

**Interfaces:** `delete_plan` also returns `"shared_bytes": int` (bytes of these models that other models still use). `lc_ollama.unload(name)` picks the right call by model type.

- [ ] **Step 1: Failing tests:**
  - `test_shared_bytes(tiny_model)`: `delete_plan([tiny_model])["shared_bytes"] >= 105_000_000` while `mm-test-copy` exists.
  - `test_shared_note_only_when_it_matters(monkeypatch, capsys)`: with `delete_plan` returning `shared_bytes` 50_000 the delete screen prints no "share files" line. With 2 GB it prints "share 2.0 GB with".
  - `test_unload_embedding_model`: pull `all-minilm` (45 MB, embedding only), load it with `/api/embed`, `unload("all-minilm")`, and it's gone from `running()`. Delete it in teardown if this test pulled it.
  - `test_unload_already_gone`: `unload("mm-not-loaded")` on a model not in `running()` raises nothing.
- [ ] **Step 2: Run.** Expected: 4 failed.
- [ ] **Step 3: Implement:**
  - The shared note shows only when `shared_bytes >= 100 MB`, worded: "These share {human(shared_bytes)} with: …".
  - `unload`: if `facts(name)["embedding_only"]`, use `/api/embed` with `{"model": name, "input": "", "keep_alive": 0}`; otherwise the current call. A model that isn't installed or loaded returns quietly.
  - Unload-all keeps going past a failure, and lists any it couldn't unload at the end.
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit** — "Show shared space on delete and unload embedding models".

### Task 4: Duplicate size rows

**Files:** Modify `mm_hf.py`. Test `tests/mm/test_hf.py`.

- [ ] **Step 1: Find a real repo** with both `Q4_K_XL` and `UD-Q4_K_XL` files (search `unsloth` repos via `quants`). Record it in the test.
- [ ] **Step 2: Failing tests:**
  - `test_quant_of_keeps_ud_prefix`: `quant_of("Model-UD-Q4_K_XL.gguf") == "UD-Q4_K_XL"`.
  - `test_no_duplicate_labels(<repo>)`: `quants(<repo>)` labels are all different.
  - `test_ud_tag_pulls`: `pull` of the smallest `UD-` size from a small real unsloth repo (≤ 1 GB, found in Step 1) succeeds, then delete it.
- [ ] **Step 3: Run.** Expected: failures on the first two (the pull may pass already).
- [ ] **Step 4: Implement:** `QUANT` also captures an optional `UD-` prefix. If two groups still share a label, add the file name's distinguishing part in brackets, and give that row's download the file's own name. `recommended` works on labels, so at most one row is marked.
- [ ] **Step 5: Run.** Expected: all pass.
- [ ] **Step 6: Commit** — "Tell apart sizes with the same name on Hugging Face".

### Task 5: Settings edge cases

**Files:** Modify `mm_settings.py`, `mm_store.py`. Test `tests/mm/test_settings.py`, `tests/mm/test_fixes.py`.

**Interfaces:** `mm_store.system_env(key)` reads `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment`. `mm_settings.same_drive(a, b) -> bool`.

- [ ] **Step 1: Failing tests:**
  - `test_same_drive`: `same_drive(Path("c:/a"), Path("C:/b")) is True`, `same_drive(Path("C:/a"), Path("D:/b")) is False`.
  - `test_same_drive_move_needs_no_space(tmp_path, monkeypatch)`: `free_space` returns 0; moving inside `tmp_path` succeeds.
  - `test_read_order(monkeypatch)`: with `app_setting` returning `None` and `system_env` returning `D:\m`, `read()["models_folder"] == "D:\\m"`. With `app_setting` returning `E:\n`, it's `E:\n`.
  - `test_app_setting_odd_path(tmp_path, monkeypatch)`: copy the real `db.sqlite` read-only into `tmp_path / "a#b"`, point `APP_DB` there, and `app_setting("models")` returns the same value as the real one.
- [ ] **Step 2: Run.** Expected: 4 failed.
- [ ] **Step 3: Implement:**
  - The `move_models` space check is skipped when `same_drive(src, dst)`.
  - `read()` and `models_dir()` share one lookup order: app setting, then user env, then system env, then the default folder.
  - `app_setting` opens `APP_DB.as_uri() + "?mode=ro"`.
- [ ] **Step 4: Run** the full suite `python -m pytest tests/mm -q`. Expected: all pass.
- [ ] **Step 5: Commit** — "Handle same-drive moves, system-wide model folder and odd paths".
