from pathlib import Path

import pytest

from lc_ollama import OllamaError, call, delete, installed, model_facts
from mm_hf import download_file
from mm_import import blob_digest, clean_path, fix_tools, import_gguf, suggest_name

TINY_REPO = "bartowski/SmolLM2-135M-Instruct-GGUF"
TINY_FILE = "SmolLM2-135M-Instruct-Q4_K_M.gguf"
TEST_MODELS = ["mm-test-import", "mm-test-good", "mm-test-bad"]


@pytest.fixture(scope="module")
def tiny_gguf(tmp_path_factory):
    path = download_file(TINY_REPO, TINY_FILE, tmp_path_factory.mktemp("gguf"), lambda d, t: None)
    yield path
    for m in TEST_MODELS:
        try:
            delete(m)
        except OllamaError:
            pass


def test_clean_path():
    assert clean_path('  "C:\\a b\\x.gguf" ') == Path("C:/a b/x.gguf")
    assert clean_path("'C:\\x.gguf'") == Path("C:/x.gguf")


def test_suggest_name():
    assert suggest_name(Path("C:/m/My Model-Q4_K_M.gguf")) == "my-model-q4_k_m"


def test_import_gguf(tiny_gguf):
    seen = []
    name = import_gguf(tiny_gguf, "mm-test-import", lambda step, done, total: seen.append(step))
    assert name == "mm-test-import:latest"
    assert name in [m["name"] for m in installed()]
    assert seen


def _create(name, gguf, template):
    call("/api/create", {"model": name, "files": {gguf.name: blob_digest(gguf)},
                         "template": template, "stream": False}, timeout=120)


def test_fix_tools_copies_from_donor(tiny_gguf):
    import_gguf(tiny_gguf, "mm-test-import", lambda *a: None)  # makes sure the blob is uploaded
    tools_template = call("/api/show", {"model": "granite3.3:8b"})["template"]
    _create("mm-test-good", tiny_gguf, tools_template)
    _create("mm-test-bad", tiny_gguf, "{{ .Prompt }}")
    assert model_facts("mm-test-good")["tools"] is True
    assert model_facts("mm-test-bad")["tools"] is False
    donor = fix_tools("mm-test-bad")
    assert donor is not None and model_facts(donor)["arch"] == model_facts("mm-test-bad")["arch"]
    assert model_facts("mm-test-bad")["tools"] is True


def test_fix_tools_no_donor(tiny_gguf):
    import_gguf(tiny_gguf, "mm-test-import", lambda *a: None)
    for m in ("mm-test-good", "mm-test-import"):
        try:
            delete(m)
        except OllamaError:
            pass
    _create("mm-test-bad", tiny_gguf, "{{ .Prompt }}")
    arch = model_facts("mm-test-bad")["arch"]
    others = [m["name"] for m in installed() if not m["name"].startswith("mm-test-bad")
              and model_facts(m["name"])["tools"] and model_facts(m["name"])["arch"] == arch]
    if others:
        pytest.skip(f"another {arch} model with tool use is installed: {others}")
    assert fix_tools("mm-test-bad") is None
