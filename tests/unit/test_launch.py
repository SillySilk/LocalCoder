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
    cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert cfg["model"] == "engine/Bonsai-PTQ1_0"
    prov = cfg["provider"]["engine"]
    assert prov["options"]["baseURL"].endswith(":8090/v1")
    assert "Bonsai-PTQ1_0" in prov["models"]


def test_enter_picks_the_default_model(monkeypatch):
    other = dict(BONSAI, name="Other", default=False)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    assert lc_launch.choose_model([BONSAI, other])["name"] == "Bonsai-PTQ1_0"


def test_small_memory_warns(capsys):
    lc_launch.check_memory(dict(BONSAI, ctx=16384))
    assert "16k memory" in capsys.readouterr().out
