"""Model Manager: download, import, delete and unload Ollama models, and
change Ollama's settings, from plain numbered menus.

Usage: python mm.py   (or double-click ModelManager.bat, or type: models)
"""

import re
import sys
from pathlib import Path

from lc_ollama import (OllamaError, call, canonical, delete, installed, model_facts, pull,
                       running, start_ollama, unload)
from mm_fit import fit_label, free_space, graphics_memory, human, recommended
from mm_hf import HFError, download_file, ollama_name, quants, search
from mm_import import (clean_path, find_ggufs, fix_tools, import_gguf, missing_family_hint,
                       suggest_name)
from mm_settings import (MEMORY_CHOICES, STAY_CHOICES, SettingsError, apply, folder_size,
                         move_models, read, stop_ollama)
from mm_store import delete_plan, models_dir

TOOLS_PAGE = "https://ollama.com/search?c=tools"
VRAM = None  # graphics memory in bytes, measured at start


# ---------- asking ----------

def ask(prompt, default=None):
    shown = f"{prompt} [{default}]: " if default not in (None, "") else f"{prompt}: "
    return input(shown).replace("﻿", "").strip() or (default or "")


def ask_number(prompt, count, default, zero="back"):
    """A number from 1 to count. 0 means go back (None). Blank takes the default."""
    while True:
        text = ask(f"{prompt} (0 = {zero})", None if default is None else str(default))
        if text.isdigit() and 0 <= int(text) <= count:
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


def tool_check(name):
    print("\nChecking whether George can use it...")
    result = fix_tools(name)
    if result == name:
        print("George can use it.")
    elif result:
        print(f"Fixed it using {short(result)}'s chat format. George can use it now.")
    else:
        print(missing_family_hint(name))
        if not ask_yes("Keep it for chat only?"):
            delete(name)
            print("Deleted.")


def enough_space(size):
    free = free_space(models_dir())
    if size and free < size:
        print(f"Not enough disk space: it needs {human(size)} and {human(free)} is free "
              f"in {models_dir()}.")
        return False
    return True


def download_model(name, size=None, hf=None):
    """hf: (repo, files) for a Hugging Face model, so a failed pull can fall back
    to downloading the file directly, if the user agrees."""
    if not enough_space(size):
        return
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
        path = download_file(repo, files[0], Path.home() / "Downloads",
                             lambda d, t: progress("Downloading", d, t))
        done_line()
        name = import_gguf(path, suggest_name(path), lambda s, d, t: progress(s, d, t))
        done_line()
        print(f"Imported as {short(name)}. The file is still in {path.parent}; you can delete it.")
    tool_check(name)


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
        f = model_facts(m["name"])
        name = ("   - " if child else "") + short(m["name"])
        mem = f"{f['num_ctx'] // 1024}k" if f["num_ctx"] else "default"
        print(f"{name:<44} {human(m['size']):>8}  {'yes' if f['tools'] else 'NO':<8} {mem:<8} "
              f"{fit_label(m['size'], VRAM):<22} {'yes' if m['name'] in loaded else ''}")
    ask("\nPress Enter to go back")


def search_screen():
    words = ask("\nSearch Hugging Face for (e.g. qwen coder)")
    if not words:
        return
    results = search(words)
    if not results:
        print("Nothing found. Try fewer or different words.")
        return
    print()
    for i, r in enumerate(results, 1):
        gated = "  (needs a Hugging Face login)" if r["gated"] else ""
        print(f"  {i:>2}) {r['repo']}  ({r['downloads']:,} downloads, updated {r['updated']}){gated}")
    pick = ask_number("Model number", len(results), None)
    if pick is None:
        return
    repo = results[pick - 1]["repo"]
    entries = quants(repo)
    if not entries:
        print("That one has no model files Ollama can use.")
        return
    rec = recommended(entries, VRAM)
    print(f"\nSizes for {repo}:" + ("" if VRAM else "  (graphics memory unknown, so no fit check)"))
    for i, e in enumerate(entries, 1):
        if e["split"]:
            note = "comes in pieces, not supported yet"
        else:
            note = fit_label(e["size"], VRAM) + ("  (recommended)" if e["quant"] == rec else "")
        print(f"  {i:>2}) {e['quant']:<10} {human(e['size']):>8}  {note}")
    default = next((i for i, e in enumerate(entries, 1) if e["quant"] == rec), None)
    while True:
        pick = ask_number("Size number", len(entries), default)
        if pick is None:
            return
        e = entries[pick - 1]
        if not e["split"]:
            break
        print("  That size comes in pieces, which isn't supported yet. Pick another.")
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
    name = ask("Name for it in Ollama", suggest_name(path)).lower().replace(" ", "-")
    if not enough_space(path.stat().st_size):
        return
    full = import_gguf(path, name, lambda s, d, t: progress(s, d, t))
    done_line()
    print(f"Imported as {short(full)}.")
    tool_check(full)


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
    if plan["shared_with"]:
        print("These share files with: " + ", ".join(short(n) for n in plan["shared_with"]) +
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
    for m in chosen:
        unload(m["name"])
    print("Unloaded.")


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
        dst = clean_path(ask("New folder for models"))
        if not str(dst) or str(dst) == ".":
            return
        src = Path(s["models_folder"])
        if dst.resolve() == src.resolve():
            print("That's already where they are.")
            return
        size = folder_size(src) if src.is_dir() else 0
        if size and ask_yes(f"Move your existing models there first? ({human(size)})"):
            stop_ollama()
            move_models(src, dst, lambda d, t: progress("Moving", d, t))
            done_line()
        elif size:
            print("Your existing models stay where they are and won't show until you switch back.")
        dst.mkdir(parents=True, exist_ok=True)
        apply_and_report("models_folder", str(dst))
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
    start_ollama()
    VRAM = graphics_memory()
    while True:
        try:
            print("\n" + header())
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


if __name__ == "__main__":
    sys.exit(main())
