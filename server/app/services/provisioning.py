from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from app.core.config import get_settings

DEFAULT_SOUL = """# 身份

你是用户的个人 AI 助理，运行在 Whitz 平台上。你友好、专业、简洁，默认使用中文回复（除非用户改用其他语言）。

# 工作方式

- 对于需要 3 个以上步骤的复杂任务，先调用 todo_list 制定计划，把任务拆成清晰的步骤；执行过程中及时更新每个步骤的状态（pending → in_progress → completed）。
- 需要联网信息时使用 web_search / web_extract，并注明信息来源。
- 当前对话如果包含上传到工作区的文件，系统会提供文件清单与 conversation_id；凡涉及查看、分析、总结或检索这些文件时，务必使用 whitz_files 工具（list_workspace_files / read_workspace_file / search_workspace_files）读取真实内容，不要凭文件名臆测；需要交付代码、文档、网页等文本产物时，使用 write_workspace_file 写入工作区。
- 当长期记忆已开启时，可用 memory 工具记住用户告诉你的重要偏好和事实，让后续对话更贴心；用户也可以在技能工具中请求浏览、创建或安装 GitHub 技能。
- 不确定用户意图时，用 clarify 工具提问，不要凭空猜测。
- 回答保持简洁清晰，善用 Markdown 排版；代码块标注语言。
"""

TOOLSETS = ["web", "todo", "skills", "session_search", "clarify", "whitz_files", "whitz_skills"]

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


def _normalize_disabled_skills(items: list[str] | None) -> list[str]:
    if not items:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        name = str(item).strip()
        if name and name not in seen:
            seen.add(name)
            cleaned.append(name)
    return cleaned


def _read_disabled_skills_from_dir(d: Path) -> list[str]:
    cfg_path = d / "config.yaml"
    if not cfg_path.exists():
        return []
    try:
        parsed = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(parsed, dict):
        return []
    skills_block = parsed.get("skills")
    if not isinstance(skills_block, dict):
        return []
    disabled = skills_block.get("disabled")
    if not isinstance(disabled, list):
        return []
    return _normalize_disabled_skills([str(item) for item in disabled])


def read_disabled_skills(profile: str) -> list[str]:
    return _read_disabled_skills_from_dir(profile_dir(profile))


def build_config(
    profile: str | None = None,
    api_key: str | None = None,
    *,
    memory_enabled: bool = False,
    memory_require_confirm: bool = True,
    disabled_skills: list[str] | None = None,
) -> dict:
    s = get_settings()
    toolsets = list(TOOLSETS)
    if memory_enabled and "memory" not in toolsets:
        insert_at = toolsets.index("skills") + 1 if "skills" in toolsets else len(toolsets)
        toolsets.insert(insert_at, "memory")

    cfg: dict = {
        "model": {
            "default": s.llm_model,
            "provider": "custom",
            "base_url": s.llm_base_url,
            "api_key": s.llm_api_key,
            "supports_vision": bool(s.llm_supports_vision),
        },
        "platform_toolsets": {"api_server": toolsets},
        "approvals": {"mode": "smart"},
        "memory": {
            "memory_enabled": bool(memory_enabled),
            "user_profile_enabled": bool(memory_enabled),
            "write_approval": bool(memory_require_confirm),
            "memory_char_limit": 2200,
            "user_char_limit": 1375,
        },
        "skills": {
            "disabled": _normalize_disabled_skills(disabled_skills),
        },
        "agent": {
            "max_turns": 60,
            "disabled_toolsets": list(DISABLED_TOOLSETS),
            "image_input_mode": "native" if s.llm_supports_vision else "auto",
        },
    }
    if profile and api_key:
        mcp_base = (s.internal_mcp_base_url or "http://server:8000").strip().rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Whitz-Profile": profile,
        }
        cfg["mcp_servers"] = {
            "whitz_files": {
                "url": f"{mcp_base}/api/internal/mcp/files",
                "headers": dict(headers),
                "timeout": 60,
            },
            "whitz_skills": {
                "url": f"{mcp_base}/api/internal/mcp/skills",
                "headers": dict(headers),
                "timeout": 60,
            },
        }
    return cfg


def render_soul(persona: str) -> str:
    text = DEFAULT_SOUL
    if persona and persona.strip():
        text += "\n## 用户自定义人设\n\n" + persona.strip() + "\n"
    return text


def _write_config(
    d: Path,
    profile: str | None = None,
    api_key: str | None = None,
    *,
    memory_enabled: bool = False,
    memory_require_confirm: bool = True,
    disabled_skills: list[str] | None = None,
) -> None:
    resolved_profile = profile or d.name
    resolved_key = api_key if api_key is not None else _read_profile_api_key(d)
    resolved_disabled = (
        _read_disabled_skills_from_dir(d) if disabled_skills is None else _normalize_disabled_skills(disabled_skills)
    )
    cfg = build_config(
        resolved_profile,
        resolved_key,
        memory_enabled=memory_enabled,
        memory_require_confirm=memory_require_confirm,
        disabled_skills=resolved_disabled,
    )
    (d / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def provision_profile(
    profile: str,
    api_key: str,
    persona: str = "",
    *,
    memory_enabled: bool = False,
    memory_require_confirm: bool = True,
    disabled_skills: list[str] | None = None,
) -> None:
    d = profile_dir(profile)
    d.mkdir(parents=True, exist_ok=True)
    env_lines = [f"API_SERVER_KEY={api_key}"]
    if get_settings().search_api_key:
        env_lines.append(f"TAVILY_API_KEY={get_settings().search_api_key}")
    (d / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    _write_config(
        d,
        profile=profile,
        api_key=api_key,
        memory_enabled=memory_enabled,
        memory_require_confirm=memory_require_confirm,
        disabled_skills=disabled_skills,
    )
    (d / "SOUL.md").write_text(render_soul(persona), encoding="utf-8")


def sync_profile_config(
    profile: str,
    api_key: str | None = None,
    *,
    memory_enabled: bool = False,
    memory_require_confirm: bool = True,
    disabled_skills: list[str] | None = None,
) -> None:
    d = profile_dir(profile)
    if d.exists():
        _write_config(
            d,
            profile=profile,
            api_key=api_key,
            memory_enabled=memory_enabled,
            memory_require_confirm=memory_require_confirm,
            disabled_skills=disabled_skills,
        )


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


def build_profile_context(user) -> str | None:
    """Build sanitized profile context only when explicitly opted-in and consented."""
    if user is None:
        return None
    if not getattr(user, "profile_context_enabled", False) or not getattr(user, "profile_context_consented_at", None):
        return None

    tz_name = (getattr(user, "timezone", None) or "").strip() or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz_name = "Asia/Shanghai"
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone(timedelta(hours=8))
    local_now = datetime.now(tz).strftime("%Y-%m-%d %H:%M (%Z)")

    lines = ["【已授权的个人资料上下文（仅用于个性化沟通，禁止收集或泄露邮箱/手机号/生日等敏感信息）】"]
    display_name = (getattr(user, "display_name", None) or "").strip()
    if display_name:
        lines.append(f"- 昵称 / 称呼：{display_name}")
    preferred_language = (getattr(user, "preferred_language", None) or "").strip()
    if preferred_language:
        lines.append(f"- 偏好语言：{preferred_language}")
    lines.append(f"- 时区与当地当前时间：{tz_name}（{local_now}）")
    occupation = (getattr(user, "occupation", None) or "").strip()
    if occupation:
        lines.append(f"- 职业 / 身份：{occupation}")
    location = (getattr(user, "location", None) or "").strip()
    if location:
        lines.append(f"- 所在地：{location}")
    gender = (getattr(user, "gender", None) or "").strip()
    if gender:
        lines.append(f"- 性别：{gender}")
    bio = (getattr(user, "bio", None) or "").strip()
    if bio:
        lines.append(f"- 个人简介：{bio}")
    return "\n".join(lines)
