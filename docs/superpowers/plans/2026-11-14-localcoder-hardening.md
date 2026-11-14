# LocalCoder Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LocalCoder dependable across as many local Ollama models and quantizations as possible, for long and multi-agent sessions, on a fresh machine, and (best effort) on Mac/Linux.

**Architecture:** `lc_launch.py` (pick model, check abilities, size context, start tool) and `lc_proxy.py` (relay between Claude Code and Ollama) stay the two moving parts. The relay becomes a per-session child process on a free port instead of a shared window. New checks live under `tests/`; unit tests use `unittest` (no new dependencies).

**Tech Stack:** Python 3 standard library only, Ollama ≥ 0.40 HTTP API, Claude Code, OpenCode, Windows batch + POSIX sh.

**Spec:** the 2026-11-14 session decisions, summarised here: the tool is model-neutral; compatibility across model families and quantization levels (especially quantized models) is the goal, not judging model quality; test models one at a time and delete each after (disk); Mac/Linux only if it's an easy addition, marked untested.

## Global Constraints

- Python standard library only; no pip installs.
- Ollama ≥ 0.40; everything about a model comes from `/api/show`, never from its name.
- Claude Code needs ~23k tokens to start; minimum usable context 32768, default target 65536.
- Normal `claude` outside LocalCoder must be unaffected (all settings are per-process env / `--settings`).
- Batch launchers stay in the repo root.
- No machine-specific paths or personal details in tracked files (repo is public).
- GPU-heavy tasks (5–8) run only when `tests/compat_matrix.py` is not running.

## Review Focus

1. **Relay dies or port 11435 is taken mid-session** → the session should keep working or fail with a clear message, never silently hang. (Task 1 tests: free-port pick, child exits with launcher.)
2. **Conversation grows past the model's context** → Claude Code compacts before Ollama truncates; Ollama's log never shows `truncated = 1`. (Task 5.)
3. **Two models or two agents share a 16 GB card** → a subagent call finishes (possibly slower), it does not crash or deadlock. (Task 6.)
4. **Low-bit quant writes a tool call as plain text** → the relay turns a recognised pattern into a real tool call; anything unrecognised passes through unchanged. (Task 7 tests both.)
5. **Fresh clone on a machine without this user's plugins/paths** → `--check` passes and one practice task runs from the clone. (Task 3.)

---

### Task 1: Per-session relay + relay unit tests

**Files:**
- Modify: `lc_proxy.py` (expose `make_server(port, upstream) -> ThreadingHTTPServer`; keep `fold_system_messages`)
- Modify: `lc_launch.py` (replace `ensure_relay()` with `start_relay() -> tuple[subprocess.Popen, int]`)
- Modify: `tests/run_tests.py`, `tests/measure_startup.py` (nothing relay-specific left; they go through `lc_launch`)
- Create: `tests/test_relay.py`

**Interfaces:**
- Produces: `lc_proxy.fold_system_messages(body: dict) -> dict`, `lc_proxy.make_server(port: int, upstream: str) -> ThreadingHTTPServer`, `lc_launch.start_relay() -> (proc, port)`.

- [ ] **Step 1: Write failing tests** in `tests/test_relay.py`:
  - `test_fold_moves_system_message_into_user_text`: messages `[user "hi", system "SKILLS"]` → one user message whose last block text contains `<system-reminder>` and `SKILLS`.
  - `test_fold_leaves_plain_conversation_untouched`: no system role → returned body `is` / equals input.
  - `test_fold_keeps_tool_result_first`: user message starting with a `tool_result` block followed by a system message → `tool_result` stays block 0.
  - `test_relay_streams_and_rewrites`: start `make_server(0, fake_upstream_url)` against a tiny fake upstream (`http.server` in a thread that records the body and replies with 3 SSE chunks); POST a body with a system message; assert the upstream saw no `"role": "system"` in `messages` and the client received all 3 chunks in order.
  - `test_start_relay_picks_free_port`: occupy a port with a socket, call `start_relay()`, assert returned port differs from the occupied one, `/api/version` answers through it (fake upstream via `LC_OLLAMA_URL`), and `proc.terminate()` stops it.
- [ ] **Step 2:** `python -m unittest tests.test_relay -v` → FAIL (`make_server`/`start_relay` missing).
- [ ] **Step 3:** Implement. `start_relay` binds port 0 to find a free port, starts `python lc_proxy.py <port> <ollama_url>` with no console window (`CREATE_NO_WINDOW` on Windows), waits ≤15 s for `/api/version`. `main()` runs the tool with `subprocess.call` inside `try/finally: proc.terminate()`. Remove the "LocalCoder relay" window text from README.
- [ ] **Step 4:** Unit tests PASS; `python tests/run_tests.py qwen3-coder-uncensored-64k --tools claude --tasks 1-explain` → PASS.
- [ ] **Step 5:** Commit `Run the relay per session on a free port`.

### Task 2: `--check` diagnostics

**Files:** Modify `lc_launch.py`; Test `tests/test_launch.py` (create).

**Interfaces:** Produces `lc_launch.run_checks() -> list[tuple[str, bool, str]]` (name, ok, detail) and CLI flag `--check` (prints a table, exit 0 if all ok else 1).

- [ ] **Step 1: Failing tests** with a fake Ollama (same helper as Task 1, moved to `tests/fakes.py`): `test_check_reports_ollama_version`, `test_check_flags_model_without_tools` (fake `/api/show` caps `["completion"]` → that model's row ok=False, detail contains "no tool use"), `test_check_flags_small_context` (num_ctx 4096 → detail contains "4k"), `test_check_relay_roundtrip` (relay start + system-message fold verified end to end against fake upstream).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement checks: Ollama reachable + version ≥ 0.40; `claude` / `opencode` on PATH (missing = warning row, not failure); relay starts and folds; per installed model: tools, num_ctx ≥ 32768.
- [ ] **Step 4:** Tests PASS; `python lc_launch.py --check` on this PC prints all rows ok.
- [ ] **Step 5:** Commit `Add lc_launch --check diagnostics`.

### Task 3: Fresh-clone verification

**Files:** Create `tests/fresh_clone_check.py`.

- [ ] **Step 1:** Script clones `https://github.com/SillySilk/LocalCoder` into a temp folder, runs `python lc_launch.py --check` and `python tests/run_tests.py <model> --tools claude --tasks 1-explain` from the clone, with `USERPROFILE`/`HOME` untouched but `PATH` unchanged; asserts both exit 0 and `git status` in the clone is clean afterwards.
- [ ] **Step 2:** Run it → PASS (fix anything that depended on `C:\AI\LocalCoder`).
- [ ] **Step 3:** Commit `Add fresh-clone check`.

### Task 4: Mac/Linux launcher (best effort, untested)

**Files:** Create `localcoder.sh`, `install-command.sh`; Modify `lc_launch.py` (`start_ollama` uses `open -a Ollama` on macOS, `ollama serve` elsewhere; relay spawn without Windows flags); Modify README.

- [ ] **Step 1: Failing test** `test_launch.py::test_platform_paths`: with `sys.platform` patched to `darwin` / `linux`, `start_ollama` command list and relay `Popen` kwargs contain no Windows-only flags.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; `localcoder.sh` = `exec python3 "$(dirname "$0")/lc_launch.py" "${1:-$PWD}" "${@:2}"`; `install-command.sh [name]` symlinks into `~/.local/bin`.
- [ ] **Step 4:** Tests PASS; `bash -n` on both scripts; run `localcoder.sh --check` under Git Bash as a smoke test.
- [ ] **Step 5:** README "Mac/Linux (untested)" section. Commit `Add untested Mac/Linux launcher`.

### Task 5: Long-session / compaction test (GPU)

**Files:** Create `tests/long_session.py`; possibly Modify `lc_launch.py` env.

- [ ] **Step 1:** Script generates a practice copy with ~12 extra 4k-token source files, asks Claude Code (via `lc_launch --yes`, `--output-format stream-json --verbose`) to read every file and write a one-line summary of each into `SUMMARY.md`. Pass = stream contains a `compact_boundary` system event **and** the Ollama `server.log` lines written during the run contain no `truncated = 1` and no `task.n_tokens` above the model's num_ctx, **and** `SUMMARY.md` has one line per file.
- [ ] **Step 2:** Run on `qwen3-coder-uncensored-64k`. If compaction never fires or truncation appears, set `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<num_ctx>` (and, if needed, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`) in `lc_launch.main()`, rerun until PASS.
- [ ] **Step 3:** Commit `Verify compaction before Ollama truncates` (with whichever env change was needed and the measured numbers in the body).

### Task 6: Subagent test (GPU)

**Files:** Modify `tests/run_tests.py` (add task `5-subagent`).

- [ ] **Step 1:** Task prompt: "Use the Agent tool to have a subagent find every function in this project and list them in FUNCTIONS.md." Check: `FUNCTIONS.md` lists `total_value`, `low_stock`, `build_report`; the run log shows an `Agent` tool call; no `session_crash`.
- [ ] **Step 2:** Run 3×; also record `ollama ps` during the run (one model loaded, or two?). If it crashes or deadlocks, investigate before changing anything; if it only slows, document it in README.
- [ ] **Step 3:** Commit `Add subagent compatibility task`.

### Task 7: Plain-text tool-call repair in the relay (GPU to verify)

Gate: start only after `tests/COMPAT.md` exists; add one test per failure pattern actually seen there.

**Files:** Create `lc_repair.py` (pure functions); Modify `lc_proxy.py` (streaming hook); Test `tests/test_repair.py`.

**Interfaces:** Produces `lc_repair.find_text_tool_calls(text: str, tool_names: set[str]) -> list[dict]` returning `{"name": str, "input": dict}`; and `lc_repair.StreamRepairer` with `feed(sse_bytes) -> bytes` / `close() -> bytes` that passes events straight through until a text delta contains a known opener (`<function=`, `<tool_call>`, `{"name":`), buffers from there, and on block end emits either repaired `tool_use` events or the buffered text unchanged.

- [ ] **Step 1: Failing tests:** `test_qwen_xml_without_opener` (the exact text from `tests/logs/opencode-…-1-explain.log`, tool `read`) → one call `{"name": "read", "input": {"filePath": ".../inventory.py"}}`; `test_unknown_tool_name_not_repaired`; `test_plain_prose_untouched`; `test_stream_repairer_passthrough_is_byte_identical` for a stream with no openers; plus one test per pattern from COMPAT.md.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. Tool names come from the request's `tools` list. Repaired calls get `stop_reason: "tool_use"`.
- [ ] **Step 4:** Unit tests PASS; rerun the compat sweep entries that showed the pattern with `--keep` off → the matching tasks now PASS or fail for a different, recorded reason.
- [ ] **Step 5:** Commit `Repair plain-text tool calls in the relay`. (OpenCode does not use the relay; if COMPAT.md shows the pattern mostly in OpenCode, routing OpenCode through the relay is a follow-up plan, not this task.)

### Task 8: Memory-fit warning (GPU)

**Files:** Modify `lc_launch.py`; Test `tests/test_launch.py`.

**Interfaces:** Produces `lc_launch.gpu_fit(name: str) -> float | None` (fraction of the loaded model in VRAM, from `/api/ps` `size_vram / size` after a 1-token warm-up with `keep_alive`).

- [ ] **Step 1: Failing test** with fake `/api/ps` (`size` 20 GB, `size_vram` 10 GB) → `prepare()` output mentions "about 50% on the graphics card" and offers a 32k version.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement: after context is settled, if fit < 0.9 print the warning and offer `make_variant(f, 32768)` (skipped with `--yes`).
- [ ] **Step 4:** Test PASS; on this PC `qwen3-coder-uncensored-64k` shows the warning (it's ~60% on GPU).
- [ ] **Step 5:** Commit `Warn when a model doesn't fit on the graphics card`.

### Task 9: Hand-off

- [ ] README: update Requirements, Known issues, Compatibility (summary of `tests/COMPAT.md`), relay description. Commit + push.
- [ ] Ask the user for the 2-minute interactive check: run `george` in a scratch folder, pick a model, ask it to create and edit a file, approve one permission prompt, exit. Record the outcome in README Known issues if anything is off.
