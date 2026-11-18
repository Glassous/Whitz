import uuid

import yaml

from app.services import provisioning


def test_config_whitelist_excludes_host_access():
    cfg = provisioning.build_config()
    enabled = cfg["platform_toolsets"]["api_server"]
    assert enabled == provisioning.TOOLSETS
    for dangerous in ("terminal", "file", "browser", "code_execution", "computer_use"):
        assert dangerous not in enabled


def test_config_defense_in_depth_disabled_toolsets():
    cfg = provisioning.build_config()
    disabled = cfg["agent"]["disabled_toolsets"]
    for dangerous in ("terminal", "file", "browser", "code_execution", "computer_use"):
        assert dangerous in disabled


def test_config_model_block():
    cfg = provisioning.build_config()
    assert cfg["model"]["provider"] == "custom"
    assert cfg["model"]["default"] == "test-model"
    assert cfg["model"]["base_url"] == "http://llm.test/v1"
    assert cfg["model"]["supports_vision"] is True
    assert cfg["agent"]["image_input_mode"] == "native"
    assert cfg["approvals"]["mode"] == "smart"


def test_render_soul_default_and_persona():
    assert "todo_list" in provisioning.render_soul("")
    soul = provisioning.render_soul("你是一位严谨的法律顾问。")
    assert "用户自定义人设" in soul
    assert "你是一位严谨的法律顾问。" in soul


def test_provision_writes_three_files():
    profile = f"u{uuid.uuid4().hex}"
    provisioning.provision_profile(profile, "key-abc", persona="自定义")
    d = provisioning.profile_dir(profile)
    assert (d / "config.yaml").exists()
    assert (d / ".env").exists()
    assert (d / "SOUL.md").exists()
    assert "API_SERVER_KEY=key-abc" in (d / ".env").read_text(encoding="utf-8")
    cfg = yaml.safe_load((d / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["platform_toolsets"]["api_server"] == provisioning.TOOLSETS
    assert "memory" not in cfg["platform_toolsets"]["api_server"]
    assert cfg["memory"]["memory_enabled"] is False
    assert cfg["memory"]["write_approval"] is True
    assert "whitz_files" in cfg["mcp_servers"]
    assert "whitz_skills" in cfg["mcp_servers"]
    assert cfg["mcp_servers"]["whitz_files"]["headers"]["Authorization"] == "Bearer key-abc"
    assert cfg["mcp_servers"]["whitz_files"]["headers"]["X-Whitz-Profile"] == profile
    assert cfg["mcp_servers"]["whitz_skills"]["url"].endswith("/api/internal/mcp/skills")
    assert "自定义" in (d / "SOUL.md").read_text(encoding="utf-8")


def test_memory_and_disabled_skills_config():
    cfg = provisioning.build_config(
        "u1",
        "k1",
        memory_enabled=True,
        memory_require_confirm=False,
        disabled_skills=["skill-a", "skill-b"],
    )
    assert "memory" in cfg["platform_toolsets"]["api_server"]
    assert cfg["memory"]["memory_enabled"] is True
    assert cfg["memory"]["user_profile_enabled"] is True
    assert cfg["memory"]["write_approval"] is False
    assert cfg["skills"]["disabled"] == ["skill-a", "skill-b"]


def test_set_parked_toggles_marker():
    profile = f"u{uuid.uuid4().hex}"
    provisioning.provision_profile(profile, "key")
    marker = provisioning.profile_dir(profile) / "gateway.parked"
    provisioning.set_parked(profile, True)
    assert marker.exists()
    provisioning.set_parked(profile, False)
    assert not marker.exists()


def test_write_persona_updates_soul():
    profile = f"u{uuid.uuid4().hex}"
    provisioning.provision_profile(profile, "key")
    provisioning.write_persona(profile, "新人设")
    assert "新人设" in (provisioning.profile_dir(profile) / "SOUL.md").read_text(encoding="utf-8")