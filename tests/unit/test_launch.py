import os
import json

import lc_launch

BONSAI = {"name": "Bonsai-PTQ1_0", "size": 6 * 10**9, "ctx": 65536, "vision": True,
          "default": True, "state": "unloaded"}


def test_claude_points_every_model_slot_at_the_engine_through_the_relay(tmp_path):
    env = {}
    cmd = lc_launch.build_command("claude", BONSAI, tmp_path, ["--resume"], env)
    assert cmd[1:3] == ["--model", "Bonsai-PTQ1_0"]
    assert cmd[-1] == "--resume"
    assert env["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{lc_launch.RELAY_PORT}"
    # placeholder key keeps the claude.ai model policy from rejecting local models
    assert env["ANTHROPIC_AUTH_TOKEN"] == "local"
    assert env["ANTHROPIC_API_KEY"] == ""
    # the local relay can't do server-side auto-mode checks
    assert env["CLAUDE_CODE_AUTO_MODE_SERVER"] == "0"
    for k in ("OPUS", "SONNET", "HAIKU", "FABLE"):
        assert env[f"ANTHROPIC_DEFAULT_{k}_MODEL"] == "Bonsai-PTQ1_0"
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "Bonsai-PTQ1_0"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "65536"
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8192"


def test_opencode_gets_a_config_for_the_engine(tmp_path):
    env = {}
    cmd = lc_launch.build_command("opencode", BONSAI, tmp_path, [], env)
    assert cmd[-1] == str(tmp_path)
    assert "--standalone" in cmd
    cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert cfg["model"] == "engine/Bonsai-PTQ1_0"
    prov = cfg["provider"]["engine"]
    assert prov["options"]["baseURL"].endswith(":8090/v1")
    assert "Bonsai-PTQ1_0" in prov["models"]


def test_opencode_knows_the_real_memory_size(tmp_path):
    env = {}
    lc_launch.build_command("opencode", BONSAI, tmp_path, [], env)
    model = json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["engine"]["models"]["Bonsai-PTQ1_0"]
    assert model["limit"] == {"context": 65536, "output": 8192}


def test_opencode_gets_the_standing_notes(tmp_path):
    env = {}
    lc_launch.build_command("opencode", BONSAI, tmp_path, [], env)
    notes = json.loads(env["OPENCODE_CONFIG_CONTENT"])["instructions"]
    assert notes and all(os.path.isfile(n) for n in notes)


def test_opencode_addons_with_everything_available(tmp_path, monkeypatch):
    root = tmp_path / "forge"
    (root / "venv" / "Scripts").mkdir(parents=True)
    (root / "venv" / "Scripts" / "python.exe").write_text("")
    plugin = tmp_path / "plugin"
    (plugin / "0.1.0" / "server").mkdir(parents=True)
    (plugin / "0.1.0" / "server" / "forge_mcp.py").write_text("")
    monkeypatch.setattr(lc_launch, "FORGE_PLUGIN", plugin)
    bow = tmp_path / "bow-desktop.exe"
    bow.write_text("")
    monkeypatch.setattr(lc_launch, "BOW_EXE", bow)
    monkeypatch.setattr(lc_launch.shutil, "which", lambda _: "gh")
    monkeypatch.setattr(lc_launch.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "tok\n"})())
    env = {"FIRECRAWL_API_KEY": "fc", "FORGE_NEO_ROOT": str(root)}
    cfg, warnings = lc_launch.opencode_addons(env)
    assert warnings == []
    assert cfg["websearch"] == {"provider": "firecrawl"}
    assert set(cfg["mcp"]["servers"]) == {"playwright", "github", "forge-neo", "firecrawl", "bow-images"}
    assert env["GITHUB_TOKEN"] == "tok"


def test_opencode_addons_warn_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(lc_launch, "FORGE_PLUGIN", tmp_path)
    monkeypatch.setattr(lc_launch, "BOW_EXE", tmp_path / "missing.exe")
    monkeypatch.setattr(lc_launch.shutil, "which", lambda _: None)
    cfg, warnings = lc_launch.opencode_addons({})
    assert "websearch" not in cfg
    assert set(cfg["mcp"]["servers"]) == {"playwright"}
    assert len(warnings) == 4


def test_enter_picks_the_default_model(monkeypatch):
    other = dict(BONSAI, name="Other", default=False)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    assert lc_launch.choose_model([BONSAI, other])["name"] == "Bonsai-PTQ1_0"


def test_small_memory_warns(capsys):
    lc_launch.check_memory(dict(BONSAI, ctx=16384))
    assert "16k memory" in capsys.readouterr().out
