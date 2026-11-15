import pytest

from lc_ollama import call, canonical, delete
from mm_store import delete_plan, manifest_candidates, manifest_path, models_dir


def test_manifest_path_forms():
    v2, v1 = models_dir() / "manifests-v2", models_dir() / "manifests"
    assert manifest_candidates("hf.co/u/r:Q4_K_M") == [v2 / "hf.co/u/r/Q4_K_M", v1 / "hf.co/u/r/Q4_K_M"]
    assert manifest_candidates("user/x:tag") == [v2 / "ollama.com/user/x/tag",
                                                 v1 / "registry.ollama.ai/user/x/tag"]
    assert manifest_candidates("granite3.3-8b-64k") == [
        v2 / "ollama.com/library/granite3.3-8b-64k/latest",
        v1 / "registry.ollama.ai/library/granite3.3-8b-64k/latest"]


def test_manifest_path_finds_every_installed_model():
    from lc_ollama import installed
    for m in installed():
        assert manifest_path(m["name"]).exists(), m["name"]


@pytest.fixture
def copy_model(tiny_model):
    call("/api/create", {"model": "mm-test-copy", "from": tiny_model,
                         "parameters": {"num_ctx": 4096}, "stream": False}, timeout=120)
    yield "mm-test-copy"
    delete("mm-test-copy")


def test_delete_plan_shared(tiny_model, copy_model):
    plan = delete_plan([copy_model])
    assert canonical(tiny_model) in plan["shared_with"]
    assert plan["freed"] < 10**6
    assert delete_plan([tiny_model, copy_model])["freed"] >= 105454432


def test_latest_and_bare_match(copy_model):
    assert delete_plan([copy_model]) == delete_plan([copy_model + ":latest"])


def test_shared_bytes(tiny_model, copy_model):
    assert delete_plan([tiny_model])["shared_bytes"] >= 105_000_000
