from pathlib import Path

import yaml

from app.core.config import get_settings

DEFAULT_SOUL = """# 身份

你是用户的个人 AI 助理，运行在 Whitz 平台上。你友好、专业、简洁，默认使用中文回复（除非用户改用其他语言）。

# 工作方式

- 对于需要 3 个以上步骤的复杂任务，先调用 todo_list 制定计划，把任务拆成清晰的步骤；执行过程中及时更新每个步骤的状态（pending → in_progress → completed）。
- 需要联网信息时使用 web_search / web_extract，并注明信息来源。
- 当前对话如果包含上传到工作区的文件，系统会提供文件清单与 conversation_id；凡涉及查看、分析、总结或检索这些文件时，务必使用 whitz_files 工具（list_workspace_files / read_workspace_file / search_workspace_files）读取真实内容，不要凭文件名臆测。
- 用 memory 工具记住用户告诉你的重要偏好和事实，让后续对话更贴心。
- 不确定用户意图时，用 clarify 工具提问，不要凭空猜测。
- 回答保持简洁清晰，善用 Markdown 排版；代码块标注语言。
"""

TOOLSETS = ["web", "todo", "skills", "memory", "session_search", "clarify", "whitz_files"]

# Defense-in-depth: even if a composite re-enables them, strip host-access toolsets at tool granularity.
DISABLED_TOOLSETS = ["terminal", "file", "browser", "code_execution", "computer_use"]


def profile_dir(profile: str) -> Path:
    return Path(get_settings().hermes_data_dir) / "profiles" / profile


def _read_profile_api_key(d: Path) -> str:
    env_file = d / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def build_config(profile: str | None = None, api_key: str | None = None) -> dict:
    s = get_settings()
    cfg: dict = {
        "model": {
            "default": s.llm_model,
            "provider": "custom",
            "base_url": s.llm_base_url,
            "api_key": s.llm_api_key,
            "supports_vision": bool(s.llm_supports_vision),
        },
        "platform_toolsets": {"api_server": list(TOOLSETS)},
        "approvals": {"mode": "smart"},
        "agent": {
            "max_turns": 60,
            "disabled_toolsets": list(DISABLED_TOOLSETS),
            "image_input_mode": "native" if s.llm_supports_vision else "auto",
        },
    }
    if profile and api_key:
        mcp_base = (s.internal_mcp_base_url or "http://server:8000").strip().rstrip("/")
        cfg["mcp_servers"] = {
            "whitz_files": {
                "url": f"{mcp_base}/api/internal/mcp/files",
                "headers": {
                    "Authorization": f"Bearer {api_key}",
                    "X-Whitz-Profile": profile,
                },
                "timeout": 60,
            }
        }
    return cfg


def render_soul(persona: str) -> str:
    text = DEFAULT_SOUL
    if persona and persona.strip():
        text += "\n## 用户自定义人设\n\n" + persona.strip() + "\n"
    return text


def _write_config(d: Path, profile: str | None = None, api_key: str | None = None) -> None:
    resolved_profile = profile or d.name
    resolved_key = api_key if api_key is not None else _read_profile_api_key(d)
    (d / "config.yaml").write_text(
        yaml.safe_dump(build_config(resolved_profile, resolved_key), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def provision_profile(profile: str, api_key: str, persona: str = "") -> None:
    d = profile_dir(profile)
    d.mkdir(parents=True, exist_ok=True)
    env_lines = [f"API_SERVER_KEY={api_key}"]
    if get_settings().search_api_key:
        env_lines.append(f"TAVILY_API_KEY={get_settings().search_api_key}")
    (d / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    _write_config(d, profile=profile, api_key=api_key)
    (d / "SOUL.md").write_text(render_soul(persona), encoding="utf-8")


def sync_profile_config(profile: str, api_key: str | None = None) -> None:
    d = profile_dir(profile)
    if d.exists():
        _write_config(d, profile=profile, api_key=api_key)


def write_persona(profile: str, persona: str) -> None:
    d = profile_dir(profile)
    if d.exists():
        (d / "SOUL.md").write_text(render_soul(persona), encoding="utf-8")


def set_parked(profile: str, parked: bool) -> None:
    marker = profile_dir(profile) / "gateway.parked"
    if parked:
        if marker.parent.exists():
            marker.touch()
    elif marker.exists():
        marker.unlink()