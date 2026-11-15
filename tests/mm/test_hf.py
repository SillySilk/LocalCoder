import pytest

from mm_hf import HFError, download_file, quant_of, quants, search

TINY_REPO = "bartowski/SmolLM2-135M-Instruct-GGUF"
TINY_FILE = "SmolLM2-135M-Instruct-Q4_K_M.gguf"
TINY_SIZE = 105454432


def test_search_finds_tiny():
    assert TINY_REPO in [r["repo"] for r in search("SmolLM2-135M-Instruct")]


def test_quant_of():
    assert quant_of("SmolLM2-135M-Instruct-Q4_K_M.gguf") == "Q4_K_M"
    assert quant_of("x-IQ3_XS.gguf") == "IQ3_XS"
    assert quant_of("x-f16.gguf") == "F16"
    assert quant_of("x-Q4_0_4_4.gguf") == "Q4_0_4_4"
    assert quant_of("readme.gguf") is None


def test_quants_sizes():
    q = {e["quant"]: e for e in quants(TINY_REPO)}
    assert q["Q4_K_M"]["size"] == TINY_SIZE
    assert q["Q4_K_M"]["split"] is False


def test_split_grouping():
    entries = quants("bartowski/Llama-3.3-70B-Instruct-GGUF")
    split = [e for e in entries if e["split"]]
    assert split
    assert all(len(e["files"]) > 1 for e in split)
    q5 = next(e for e in split if e["quant"] == "Q5_K_M")
    assert q5["size"] > 40 * 10**9


def test_missing_repo():
    with pytest.raises(HFError, match="not found"):
        quants("PanPDX/does-not-exist-mm")


class Stop(Exception):
    pass


def test_download_resumes(tmp_path):
    def stop_early(done, total):
        if done > 10 * 10**6:
            raise Stop

    with pytest.raises(Stop):
        download_file(TINY_REPO, TINY_FILE, tmp_path, stop_early)
    part = tmp_path / (TINY_FILE + ".part")
    first = part.stat().st_size
    assert 0 < first < TINY_SIZE

    starts = []
    out = download_file(TINY_REPO, TINY_FILE, tmp_path, lambda d, t: starts.append(d))
    assert starts[0] >= first  # carried on, didn't start over
    assert out.stat().st_size == TINY_SIZE
    assert not part.exists()


def test_gated_repo_needs_login(tmp_path):
    with pytest.raises(HFError, match="needs a Hugging Face login"):
        download_file("meta-llama/Llama-3.1-8B-Instruct", "config.json", tmp_path, lambda d, t: None)


def test_helper_files_are_not_sizes():
    sizes = quants("ggml-org/Qwen3.8-27B-GGUF")
    assert min(e["size"] for e in sizes) > 10 * 10**9  # mtp-/dflash-/mmproj- helpers left out


def test_search_has_dates():
    assert all(r["updated"] for r in search("SmolLM2-135M-Instruct", limit=3))


def test_complete_part_file_finishes(tmp_path):
    done = download_file(TINY_REPO, TINY_FILE, tmp_path, lambda d, t: None)
    part = done.with_name(done.name + ".part")
    done.rename(part)
    out = download_file(TINY_REPO, TINY_FILE, tmp_path, lambda d, t: None)
    assert out.stat().st_size == TINY_SIZE and not part.exists()


def test_oversized_part_restarts(tmp_path):
    part = tmp_path / (TINY_FILE + ".part")
    with open(part, "wb") as f:
        f.truncate(200 * 10**6)
    out = download_file(TINY_REPO, TINY_FILE, tmp_path, lambda d, t: None)
    assert out.stat().st_size == TINY_SIZE
