"""Will a model fit on the graphics card, and is there disk space."""

import shutil
import subprocess
from pathlib import Path


def graphics_memory():
    """Graphics card memory in bytes (first NVIDIA card), or None if unknown."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15, check=True).stdout
        return int(out.split()[0]) * 1024**2
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def fit_label(size, vram):
    if vram is None:
        return ""
    if size <= 0.80 * vram:
        return "fits"
    if size <= vram:
        return "tight"
    return "too big, will be slow"


def recommended(quants, vram):
    """Largest size that fits; if none fits, the smallest. Split files excluded."""
    whole = [q for q in quants if not q["split"]]
    if vram is None or not whole:
        return None
    fitting = [q for q in whole if fit_label(q["size"], vram) == "fits"]
    pick = max(fitting, key=lambda q: q["size"]) if fitting else min(whole, key=lambda q: q["size"])
    return pick["quant"]


def usable(quants, vram):
    """Sizes worth showing: whole files that fit or are tight (all whole files if the card is unknown)."""
    return [q for q in quants if not q["split"] and (vram is None or fit_label(q["size"], vram) != "too big, will be slow")]


def free_space(folder):
    folder = Path(folder)
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    return shutil.disk_usage(folder).free


def human(n):
    if n >= 10**9:
        return f"{n / 10**9:.1f} GB"
    if n >= 10**6:
        return f"{round(n / 10**6)} MB"
    return f"{round(n / 10**3)} KB"
