"""Model Manager: download, import, delete and unload Ollama models, and
change Ollama's settings, from plain numbered menus.

Usage: python mm.py   (or double-click ModelManager.bat, or type: models)
"""

import re
import sys
from pathlib import Path

import traceback
from concurrent.futures import ThreadPoolExecutor

from lc_ollama import (OllamaError, call, canonical, delete, facts, installed, pull, running,
                       start_ollama, unload)
from mm_fit import fit_label, free_space, graphics_memory, human, recommended, usable
from mm_hf import HFError, download_file, ollama_name, quants, search
from mm_import import (clean_path, find_ggufs, fix_tools, import_gguf, missing_family_hint,
                       suggest_name)
from mm_settings import (MEMORY_CHOICES, STAY_CHOICES, SettingsError, apply, change_models_folder,
                         check_folder, folder_size, read)
from mm_store import delete_plan, models_dir

TOOLS_PAGE = "https://ollama.com/search?c=tools"
VRAM = None  # graphics memory in bytes, measured at start
ERROR_LOG = Path(__file__).resolve().parent / "tests" / "logs" / "model-manager-errors.log"


# ---------- asking ----------

def ask(prompt, default=None):
    shown = f"{prompt} [{default}]: " if default not in (None, "") else f"{prompt}: "
    return input(shown).replace("﻿", "").strip() or (default or "")


def ask_number(prompt, count, default, zero="back"):
    """A number from 1 to count. 0 means go back (None). Blank takes the default."""
    while True:
        text = ask(f"{prompt} (0 = {zero})", None if default is None else str(default))
        if text.isascii() and text.isdecimal() and 0 <= int(text) <= count:
            return int(text) or None
        print(f"  Please type a number from 0 to {count}.")


def ask_yes(prompt):
    while True:
        text = ask(prompt + " (y/n)", "n").lower()
        if text in ("y", "yes"):
            return True
        if text in ("n", "no"):
            return False
        print("  Please type y or n.")


def parse_picks(text, count):
    try:
        picks = [int(p) for p in re.split(r"[,\s]+", text.strip()) if p]
    except ValueError:
        return None
    if not picks or any(not 1 <= p <= count for p in picks):
        return None
    return sorted(set(picks))


def progress(label, done, total):
    if total:
        pct = done / total
        bar = "#" * int(pct * 20)
        line = f"{label:<20} {pct:4.0%} [{bar:<20}] {human(done)} / {human(total)}"
    else:
        line = f"{label}..."
    print("\r" + line.ljust(78), end="", flush=True)


def done_line():
    print()


# ---------- shared steps ----------

def short(n):
    return n[:-len(":latest")] if n.endswith(":latest") else n


def have(name):
    return canonical(name) in {canonical(m["name"]) for m in installed()}


def tool_check(name, existed_before):
    print("\nChecking whether George can use it...")
    result = fix_tools(name)
    if result == name:
        print("George can use it.")
    elif result:
        print(f"Fixed it using {short(result)}'s chat format. George can use it now.")
    else:
        print("George can't use this one as an agent (it can still chat). " + missing_family_hint(name))
        # Never offer to delete a model the user already had before this download.
        if not existed_before and ask_yes("Delete it again?"):
            delete(name)
            print("Deleted.")


def enough_space(size):
    free = free_space(models_dir())
    if size and free < size:
        print(f"Not enough disk space: it needs {human(size)} and {human(free)} is free "
              f"in {models_dir()}.")
        return False
    return True


def enough_for_direct(size):
    """The direct download needs room in Downloads, then again in the models folder."""
    downloads, models = Path.home() / "Downloads", models_dir()
    same = Path(downloads.anchor).resolve() == Path(models.anchor).resolve()
    need = {downloads: size * 2} if same else {downloads: size, models: size}
    for folder, amount in need.items():
        free = free_space(folder)
        if size and free < amount:
            print(f"Not enough disk space: {folder} needs {human(amount)} and {human(free)} is free.")
            return False
    return True


def download_model(name, size=None, hf=None):
    """hf: (repo, files) for a Hugging Face model, so a failed pull can fall back
    to downloading the file directly, if the user agrees."""
    if not enough_space(size):
        return
    existed = have(name)
    print(f"\nDownloading {name}")
    try:
        pull(name, lambda status, d, t: progress(status[:20] or "Downloading", d, t))
        done_line()
    except OllamaError as e:
        done_line()
        print(f"Ollama couldn't download it: {e}")
        if not hf or not ask_yes("Download the file directly instead, then import it?"):
            return
        repo, files = hf
        if not enough_for_direct(size):
            return
        path = download_file(repo, files[0], Path.home() / "Downloads",
                             lambda d, t: progress("Downloading", d, t))
        done_line()
        name = free_name(suggest_name(path))
        existed = have(name)
        name = import_gguf(path, name, lambda s, d, t: progress(s, d, t))
        done_line()
        print(f"Imported as {short(name)}. The file is still in {path.parent}; you can delete it.")
    tool_check(name, existed)


# ---------- screens ----------

VARIANT = re.compile(r"^(.*)-(\d+)k(?::latest)?$")


def sanitized(name):
    return short(name).replace(":", "-").replace("/", "-")


def ordered_models(models):
    """Each model followed by George's bigger-memory versions made from it."""
    by_clean = {sanitized(m["name"]): m for m in models}
    children, roots = {}, []
    for m in models:
        v = VARIANT.match(m["name"])
        parent = by_clean.get(v.group(1)) if v else None
        if parent is not None and parent is not m:
            children.setdefault(parent["name"], []).append(m)
        else:
            roots.append(m)
    out = []
    for r in sorted(roots, key=lambda m: m["name"]):
        out.append((r, False))
        out += [(c, True) for c in sorted(children.get(r["name"], []), key=lambda m: m["name"])]
    return out


def my_models():
    models = installed()
    if not models:
        print(f"\nNo models yet. Use 2 or 3 on the main menu, or browse {TOOLS_PAGE}")
        return
    loaded = {m["name"] for m in running()}
    print(f"\n{'Model':<44} {'Size':>8}  {'George?':<8} {'Memory':<8} {'Fit':<22} Loaded")
    for m, child in ordered_models(models):
        f = facts(m["name"])
        name = ("   - " if child else "") + short(m["name"])
        mem = f"{f['num_ctx'] // 1024}k" if f["num_ctx"] else "default"
        print(f"{name:<44} {human(m['size']):>8}  {'yes' if f['tools'] else 'NO':<8} {mem:<8} "
              f"{fit_label(m['size'], VRAM):<22} {'yes' if m['name'] in loaded else ''}")
    ask("\nPress Enter to go back")


def runnable_results(results, quants_by_repo, vram):
    """Only models with at least one size that fits or is tight, each with its best size."""
    out = []
    for r in results:
        entries = quants_by_repo.get(r["repo"]) or []
        ok = usable(entries, vram)
        if not ok:
            continue
        rec = recommended(entries, vram)
        best = next((e for e in ok if e["quant"] == rec), ok[-1])
        out.append({**r, "entries": entries, "best": best})
    return out


def _sizes_for(repos):
    def one(repo):
        try:
            return repo, quants(repo)
        except HFError:
            return repo, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, repos))


def search_screen():
    words = ask("\nSearch Hugging Face for (e.g. qwen coder)")
    if not words:
        return
    found = search(words, limit=40)
    if not found:
        print("Nothing found. Try fewer or different words.")
        return
    print("Checking sizes against your graphics card...")
    runnable = runnable_results(found, _sizes_for([r["repo"] for r in found]), VRAM)
    results = runnable[:20]
    hidden = len(found) - len(runnable)
    more = len(runnable) - len(results)
    if not results:
        print("Found models, but none come in a size your graphics card can run. Try a smaller model.")
        return
    print()
    for i, r in enumerate(results, 1):
        gated = "  (needs a Hugging Face login)" if r["gated"] else ""
        b = r["best"]
        best = f"best fit {b['quant']} {human(b['size'])}" if VRAM else f"smallest {b['quant']} {human(b['size'])}"
        print(f"  {i:>2}) {r['repo']}  ({best}; {r['downloads']:,} downloads, updated {r['updated']}){gated}")
    if hidden and VRAM:
        print(f"  ({hidden} hidden: too big for your graphics card, or no files Ollama can use)")
    if more:
        print(f"  ({more} more that would run; add words to narrow the search)")
    pick = ask_number("Model number", len(results), None)
    if pick is None:
        return
    r = results[pick - 1]
    repo, entries = r["repo"], r["entries"]
    rec = r["best"]["quant"]
    show_all = False
    while True:
        shown = entries if show_all else usable(entries, VRAM)
        print(f"\nSizes for {repo}:" + ("" if VRAM else "  (graphics memory unknown, so no fit check)"))
        for i, e in enumerate(shown, 1):
            if e["split"]:
                note = "comes in pieces, not supported yet"
            else:
                note = fit_label(e["size"], VRAM) + ("  (recommended)" if e["quant"] == rec else "")
            print(f"  {i:>2}) {e['quant']:<10} {human(e['size']):>8}  {note}")
        extra = len(entries) - len(shown)
        count = len(shown)
        if extra:
            count += 1
            print(f"  {count:>2}) Show {extra} more sizes that are too big for your graphics card")
        default = next((i for i, e in enumerate(shown, 1) if e["quant"] == rec), None)
        pick = ask_number("Size number", count, default)
        if pick is None:
            return
        if extra and pick == count:
            show_all = True
            continue
        e = shown[pick - 1]
        if e["split"]:
            print("  That size comes in pieces, which isn't supported yet. Pick another.")
            continue
        break
    download_model(ollama_name(repo, e["quant"]), e["size"], hf=(repo, e["files"]))


def by_name_screen():
    print(f"\nBrowse models that work with George at {TOOLS_PAGE}")
    print("Copy a name from there (e.g. qwen3:14b), or a Hugging Face link (hf.co/<user>/<repo>:<size>).")
    name = ask("Model name")
    if name:
        download_model(name.removeprefix("ollama pull ").strip())


def import_screen():
    files = find_ggufs()[:20]
    print()
    for i, p in enumerate(files, 1):
        print(f"  {i:>2}) {p.name}  ({human(p.stat().st_size)}, in {p.parent})")
    print(f"  {len(files) + 1:>2}) Paste a path to a .gguf file")
    pick = ask_number("File number", len(files) + 1, None)
    if pick is None:
        return
    if pick <= len(files):
        path = files[pick - 1]
    else:
        path = clean_path(ask("Path"))
        if not path.is_file():
            print(f"No file at {path}")
            return
    name = free_name(ask("Name for it in Ollama", suggest_name(path)).lower().replace(" ", "-"))
    if not enough_space(path.stat().st_size):
        return
    existed = have(name)
    full = import_gguf(path, name, lambda s, d, t: progress(s, d, t))
    done_line()
    print(f"Imported as {short(full)}.")
    tool_check(full, existed)


def delete_screen():
    models = [m for m, _ in ordered_models(installed())]
    if not models:
        print("\nNo models to delete.")
        return
    print()
    for i, m in enumerate(models, 1):
        print(f"  {i:>2}) {short(m['name'])}  ({human(m['size'])})")
    while True:
        text = ask("Numbers to delete, e.g. 1,3 (0 = back)")
        if text in ("", "0"):
            return
        picks = parse_picks(text, len(models))
        if picks:
            break
        print(f"  Please type numbers from 1 to {len(models)}, separated by commas.")
    names = [models[p - 1]["name"] for p in picks]
    plan = delete_plan(names)
    print("\nThis deletes: " + ", ".join(short(n) for n in names))
    print(f"Disk space you get back: {human(plan['freed'])}")
    if plan["shared_with"] and plan["shared_bytes"] >= 100 * 10**6:
        print(f"These share {human(plan['shared_bytes'])} with: " +
              ", ".join(short(n) for n in plan["shared_with"]) +
              ". That space only comes back when those are deleted too.")
    if ask_yes("Delete?"):
        for n in names:
            delete(n)
        print("Deleted.")


def unload_screen():
    models = running()
    if not models:
        print("\nNothing is loaded right now.")
        return
    print()
    for i, m in enumerate(models, 1):
        print(f"  {i:>2}) {short(m['name'])}  (using {human(m.get('size_vram', 0))} of graphics memory)")
    print(f"  {len(models) + 1:>2}) All of them")
    pick = ask_number("Unload which", len(models) + 1, len(models) + 1)
    if pick is None:
        return
    chosen = models if pick == len(models) + 1 else [models[pick - 1]]
    failed = []
    for m in chosen:
        try:
            unload(m["name"])
        except OllamaError as e:
            failed.append(f"{short(m['name'])} ({e})")
    print("Unloaded." if not failed else "Unloaded the rest. Couldn't unload: " + ", ".join(failed))


def show_memory(v):
    return f"{int(v) // 1024}k" if v else "Ollama's default"


def show_stay(v):
    names = dict((val, label) for label, val in STAY_CHOICES)
    return names.get(v, v) if v else "5 min (Ollama's default)"


def apply_and_report(key, value):
    print("Restarting Ollama...")
    if apply(key, value):
        print("Done. Ollama is using the new setting.")
    else:
        print("Ollama restarted but didn't pick up the change. Check the Ollama app's own Settings screen.")


def settings_screen():
    s = read()
    print("\n===== Settings =====")
    print(f"  1) Where models are saved:   {s['models_folder']}")
    print(f"  2) Default memory size:      {show_memory(s['memory'])}")
    print(f"  3) How long models stay loaded after use: {show_stay(s['stay_loaded'])}")
    pick = ask_number("Change which", 3, None)
    if pick is None:
        return
    print("Changing this restarts Ollama; anything running in George will stop.")
    if pick == 1:
        text = ask("New folder for models (full path, e.g. D:\\Ollama models)")
        if not text:
            return
        dst = check_folder(clean_path(text))
        src = Path(s["models_folder"])
        if dst.resolve() == src.resolve():
            print("That's already where they are.")
            return
        size = folder_size(src) if src.is_dir() else 0
        move = bool(size) and ask_yes(f"Move your existing models there first? ({human(size)})")
        if size and not move:
            print("Your existing models stay where they are and won't show until you switch back.")
        print("Restarting Ollama...")
        ok = change_models_folder(src, dst, move, lambda d, t: progress("Moving", d, t))
        done_line()
        print("Done. Ollama is using the new folder." if ok else
              "Ollama restarted but didn't pick up the change. Check the Ollama app's own Settings screen.")
    elif pick == 2:
        choices = MEMORY_CHOICES + [("Ollama's default", None)]
        for i, (label, _) in enumerate(choices, 1):
            print(f"  {i}) {label}")
        p = ask_number("Memory size", len(choices), None)
        if p:
            apply_and_report("memory", choices[p - 1][1])
    else:
        choices = STAY_CHOICES[:]
        for i, (label, _) in enumerate(choices, 1):
            print(f"  {i}) {label}")
        p = ask_number("Stay loaded for", len(choices), None)
        if p:
            apply_and_report("stay_loaded", None if choices[p - 1][1] == "5m" else choices[p - 1][1])


SCREENS = {1: my_models, 2: search_screen, 3: by_name_screen, 4: import_screen,
           5: delete_screen, 6: unload_screen, 7: settings_screen}

MENU = """  1) My models
  2) Search Hugging Face and download
  3) Download by name
  4) Import a .gguf file
  5) Delete a model
  6) Unload models (free graphics memory)
  7) Settings
  0) Quit"""


def free_name(name):
    """Ask before an import replaces a model that already has this name."""
    while have(name):
        if ask_yes(f"A model called {name} already exists. Replace it?"):
            return name
        name = ask("Another name").lower().replace(" ", "-") or name
    return name


def log_error():
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
    except OSError:
        pass


def header():
    version = call("/api/version").get("version", "?")
    count = len(installed())
    card = f"{round(VRAM / 1024**3)} GB graphics card" if VRAM else "graphics memory unknown"
    return f"===== Model Manager =====  (Ollama {version}, {count} models, {card})"


def main():
    global VRAM
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # never crash on a character the window can't show
    try:
        start_ollama()
        VRAM = graphics_memory()
    except (KeyboardInterrupt, EOFError):
        print()
        return
    while True:
        try:
            try:
                top = header()
            except OllamaError as e:
                top = f"===== Model Manager =====  (Ollama problem: {e})"
            print("\n" + top)
            print(MENU)
            pick = ask_number("Choose", 7, None, zero="quit")
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if pick is None:
            return
        try:
            SCREENS[pick]()
        except (KeyboardInterrupt, EOFError):
            done_line()
            print("Back to the main menu.")
        except (OllamaError, HFError, SettingsError) as e:
            done_line()
            print(f"Problem: {e}")
        except Exception as e:  # anything unexpected: plain words, details to a log file
            done_line()
            log_error()
            print(f"Something went wrong: {e}. Details were saved to {ERROR_LOG}.")


if __name__ == "__main__":
    sys.exit(main())
