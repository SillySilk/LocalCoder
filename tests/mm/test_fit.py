import shutil

import pytest

from mm_fit import fit_label, graphics_memory, human, recommended


@pytest.mark.skipif(shutil.which("nvidia-smi") is None, reason="no NVIDIA card")
def test_graphics_memory_measured():
    assert graphics_memory() == 16380 * 1024**2


def test_fit_label():
    v = 16 * 10**9
    assert fit_label(12 * 10**9, v) == "fits"
    assert fit_label(14 * 10**9, v) == "tight"
    assert fit_label(18 * 10**9, v) == "too big, will be slow"
    assert fit_label(12 * 10**9, None) == ""


def test_recommended():
    qs = [{"quant": "Q4", "size": 9 * 10**9, "split": False},
          {"quant": "Q6", "size": 12 * 10**9, "split": False},
          {"quant": "Q8", "size": 16.5 * 10**9, "split": False},
          {"quant": "F16", "size": 30 * 10**9, "split": True}]
    assert recommended(qs, 16 * 10**9) == "Q6"
    assert recommended(qs, 4 * 10**9) == "Q4"
    assert recommended(qs, None) is None


def test_human():
    assert human(105454432) == "105 MB"
    assert human(4_900_000_000) == "4.9 GB"
