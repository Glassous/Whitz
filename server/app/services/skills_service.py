from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import SkillPendingProposal, User, UserSkill

logger = logging.getLogger("whitz.skills")

MAX_GITHUB_FILES = 20
MAX_GITHUB_TOTAL_BYTES = 512 * 1024
ALLOWED_GITHUB_HOSTS = frozenset({"github.com", "raw.githubusercontent.com", "api.github.com"})
SAFE_SUPPORT_EXTS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".sh",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".css",
        ".html",
        ".sql",
        ".csv",
        ".tsv",
        ".xml",
        "",
    }
)

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SHORTHAND_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n(.*))?$", re.DOTALL)
_BUILTIN_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".hub",
        ".archive",
        ".curator_backups",
        ".locks",
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        "__pycache__",
    }
)
_SKILL_SUPPORT_DIRS = frozenset({"references", "templates", "assets", "scripts"})

# Built-in skills imported from external catalogs that call unavailable host toolsets/CLIs
# remain hidden from the skill management UI.
_UNAVAILABLE_TOOLSET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("terminal", re.compile(r"(?<![\w.])terminal\s*\(", re.IGNORECASE)),
    ("process", re.compile(r"(?<![\w.])process\s*\(\s*(?:action\s*[=:]|session_id\s*[=:])", re.IGNORECASE)),
    ("code_execution", re.compile(r"(?<![\w.])code_execution\s*\(", re.IGNORECASE)),
    ("browser", re.compile(r"(?<![\w.])browser\s*\(", re.IGNORECASE)),
    ("computer_use", re.compile(r"(?<![\w.])computer_use\s*\(", re.IGNORECASE)),
    ("terminal", re.compile(r"\bpty\s*(?:=|:)\s*true\b", re.IGNORECASE)),
)
_CLI_INSTALL_PATTERN = re.compile(
    r"\b(?:npm\s+install\s+(?:-g|--global)"
    r"|pip3?\s+install"
    r"|uv\s+(?:tool\s+)?install"
    r"|brew\s+install"
    r"|apt-get\s+install"
    r"|winget\s+install)\b",
    re.IGNORECASE,
)
_UNAVAILABLE_BUILTIN_CATEGORIES = frozenset(
    {"apple", "autonomous-ai-agents", "smart-home", "email", "social-media", "note-taking", "devops"}
)
_UNAVAILABLE_BUILTIN_NAMES = frozenset(
    {
        "apple-notes",
        "apple-reminders",
        "findmy",
        "imessage",
        "claude-code",
        "codex",
        "opencode",
        "himalaya",
        "xurl",
        "google-workspace",
        "obsidian",
        "teams-meeting-pipeline",
        "gif-search",
        "songsee",
        "manim-video",
        "ascii-video",
        "p5js",
        "dogfood",
        "python-debugpy",
        "node-inspect-debugger",
        "codebase-inspection",
        "test-driven-development",
        "systematic-debugging",
        "requesting-code-review",
        "spike",
    }
)
_HIDDEN_BUILTIN_REASON_GENERIC = "该技能依赖本平台未向智能体开放的宿主工具或本地命令行"

_SECURITY_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "remote_pipe_exec",
        "检测到从远程下载并直接通过管道执行脚本（curl/wget | sh/python）",
        re.compile(
            r"(?:curl|wget)\b[^\n|]{0,240}\|\s*(?:sudo\s+)?(?:(?:ba|z|da|k)?sh|python[23]?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "eval_remote_exec",
        "检测到动态执行远程拉取的代码（eval $(curl/wget)）",
        re.compile(r"\beval\s+[\"']?\$\((?:curl|wget)\b", re.IGNORECASE),
    ),
    (
        "reverse_shell",
        "检测到反弹 Shell 或网络连接重定向指令",
        re.compile(
            r"(?:/dev/tcp/\S+/\d+|\b(?:nc|ncat|netcat)\b[^\n]{0,120}\s-(?:e|c)\s|\bbash\s+-i\s+>&\s*/dev/tcp/)",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_path_access",
        "检测到读取系统密码或私钥凭证路径（~/.ssh 私钥、/etc/shadow、~/.aws/credentials 等）",
        re.compile(
            r"(?:(?:~|/root|/home/[^/\s]+|\$HOME)/\.(?:ssh/(?:id_rsa|id_ed25519|id_ecdsa|authorized_keys)|aws/credentials|kube/config|netrc)|/etc/shadow\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "secret_exfiltration",
        "检测到向外部发送环境变量或敏感密钥的网络外泄行为",
        re.compile(
            r"(?:curl|wget|Invoke-WebRequest|requests\.post|httpx\.post|urllib\.request)\b[^\n]{0,240}(?:os\.environ|API_SERVER_KEY|AGENT_INTERNAL_TOKEN|JWT_SECRET|COS_SECRET|AWS_SECRET|OPENAI_API_KEY|ANTHROPIC_API_KEY|\.env\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "destructive_fs",
        "检测到高危破坏性系统命令（rm -rf / 或 Fork 炸弹）",
        re.compile(
            r"(?:\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/(?:\s|$|\*)|:\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:)",
            re.IGNORECASE,
        ),
    ),
    (
        "obfuscated_exec",
        "检测到混淆解码执行指令（exec(base64.b64decode) / PowerShell EncodedCommand）",
        re.compile(
            r"(?:\bexec\s*\(\s*(?:base64\.b64decode|codecs\.decode|marshal\.loads)|\bpowershell(?:\.exe)?\b[^\n]{0,120}\s-(?:enc|encodedcommand)\b)",
            re.IGNORECASE,
        ),
    ),
]


class SkillServiceError(ValueError):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class SkillSecurityError(SkillServiceError):
    pass


class SkillSsrfError(SkillServiceError):
    pass


def _global_skills_dir() -> Path:
    settings = get_settings()
    configured = (settings.builtin_skills_dir or "").strip()
    if configured:
        return Path(configured)
    app_skills = Path(settings.app_data_dir) / "skills"
    if app_skills.is_dir():
        return app_skills
    return Path(__file__).resolve().parents[2] / "resources" / "builtin_skills"


def _split_names(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip().lower() for part in re.split(r"[,;\s]+", value) if part.strip()}


def _builtin_name_overrides() -> tuple[set[str], set[str]]:
    settings = get_settings()
    return _split_names(settings.skills_builtin_allowlist), _split_names(settings.skills_builtin_denylist)


def _builtin_unavailable_reason(
    content: str | None,
    *,
    name: str,
    category: str | None,
) -> str | None:
    """Explain why a built-in skill cannot run here, or return None when it can."""
    allow, deny = _builtin_name_overrides()
    lowered = (name or "").strip().lower()
    if lowered in deny:
        return "该技能已被平台屏蔽"
    if allow and lowered not in allow:
        return "该技能未在平台技能白名单中"
    if lowered in _UNAVAILABLE_BUILTIN_NAMES:
        return _HIDDEN_BUILTIN_REASON_GENERIC
    if category and category.strip().lower() in _UNAVAILABLE_BUILTIN_CATEGORIES:
        return _HIDDEN_BUILTIN_REASON_GENERIC
    if content:
        for toolset, pattern in _UNAVAILABLE_TOOLSET_PATTERNS:
            if pattern.search(content):
                return f"该技能依赖 {toolset} 工具集，本平台未向智能体开放"
        if _CLI_INSTALL_PATTERN.search(content):
            return _HIDDEN_BUILTIN_REASON_GENERIC
    return None


def hidden_builtin_names() -> set[str]:
    """Lower-cased names of built-in skills hidden on this deployment."""
    return {item["name"].lower() for item in _scan_builtin_skills(set()) if not item.get("available")}


def validate_skill_name(raw_name: str) -> str:
    name = (raw_name or "").strip()
    if not name or ".." in name or "/" in name or "\\" in name or not _SKILL_NAME_RE.match(name):
        raise SkillServiceError("技能名称仅支持字母、数字、点、下划线和连字符（1-80 字符）", 400)
    return name


def _slugify_skill_name(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (raw or "").strip()).strip(".-")
    if not cleaned:
        return f"skill-{uuid.uuid4().hex[:8]}"
    return cleaned[:80]


def _safe_rel_path(raw_path: str) -> str:
    cleaned = (raw_path or "").replace("\\", "/").strip().lstrip("/")
    if not cleaned or "\x00" in cleaned:
        raise SkillServiceError("技能文件路径无效", 400)
    parts = PurePosixPath(cleaned).parts
    if not parts:
        raise SkillServiceError("技能文件路径无效", 400)
    for part in parts:
        if part in ("", ".", "..", ".git") or part.startswith(".git"):
            raise SkillServiceError(f"检测到非法技能文件路径: {raw_path}", 400)
    return "/".join(parts)


def scan_skill_files(files: dict[str, str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for filename, text in files.items():
        if not text:
            continue
        for rule_id, message, pattern in _SECURITY_RULES:
            match = pattern.search(text)
            if match:
                findings.append(
                    {
                        "rule": rule_id,
                        "file": filename,
                        "message": message,
                        "snippet": match.group(0)[:160],
                    }
                )
    return findings


def assert_skill_safe(files: dict[str, str]) -> None:
    findings = scan_skill_files(files)
    if findings:
        first = findings[0]
        raise SkillSecurityError(
            f"安全扫描拦截（{first['file']}）：{first['message']}",
            400,
        )


def parse_skill_markdown(content: str, fallback_name: str = "") -> dict[str, Any]:
    text = (content or "").lstrip("\ufeff")
    meta: dict[str, Any] = {}
    body = text
    match = _FRONTMATTER_RE.match(text)
    if match:
        raw_fm = match.group(1)
        body = (match.group(2) or "").lstrip("\r\n")
        try:
            loaded = yaml.safe_load(raw_fm)
            if isinstance(loaded, dict):
                meta = loaded
        except yaml.YAMLError:
            meta = {}

    extra_meta: dict[str, Any] = {}
    raw_metadata = meta.get("metadata")
    if isinstance(raw_metadata, dict):
        for meta_key in ("whitz", "agent"):
            if isinstance(raw_metadata.get(meta_key), dict):
                extra_meta = raw_metadata[meta_key]
                break

    name = str(meta.get("name") or fallback_name or "").strip()
    title = str(meta.get("title") or "").strip() or None
    description = str(meta.get("description") or "").strip()
    if not description:
        for line in body.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                description = stripped[:240]
                break
    category = str(meta.get("category") or extra_meta.get("category") or "").strip() or None
    raw_tags = meta.get("tags")
    if raw_tags is None:
        raw_tags = extra_meta.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags = [t.strip().strip("\"'") for t in raw_tags.strip("[]").split(",") if t.strip()]
    else:
        tags = []
    return {
        "name": name,
        "title": title,
        "description": description,
        "category": category,
        "tags": tags,
        "meta": meta,
        "body": body,
    }


def render_skill_markdown(
    content: str,
    *,
    name: str,
    description: str | None = None,
    category: str | None = None,
) -> str:
    text = (content or "").lstrip("\ufeff").strip()
    if not text:
        raise SkillServiceError("技能内容不能为空", 400)
    match = _FRONTMATTER_RE.match(text)
    if match:
        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            fm = None
        if isinstance(fm, dict):
            fm["name"] = name
            if description is not None and description.strip():
                fm["description"] = description.strip()
            elif not fm.get("description"):
                fm["description"] = name
            if category is not None:
                if category.strip():
                    fm["category"] = category.strip()
                else:
                    fm.pop("category", None)
            body = (match.group(2) or "").lstrip("\r\n")
            dumped = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
            return f"---\n{dumped}\n---\n\n{body}\n" if body else f"---\n{dumped}\n---\n"

    fm_data: dict[str, Any] = {
        "name": name,
        "description": (description or "").strip() or name,
    }
    if category and category.strip():
        fm_data["category"] = category.strip()
    dumped = yaml.safe_dump(fm_data, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n\n{text}\n"


_BUILTIN_SCAN_CACHE: dict[tuple[str, float, str, str], tuple[float, list[dict[str, Any]]]] = {}


def _scan_builtin_skills(disabled_set: set[str]) -> list[dict[str, Any]]:
    """Scan built-in skills on disk with short mtime-keyed cache to avoid per-turn event-loop disk walks."""
    import time as _time

    global_root = _global_skills_dir()
    if not global_root.is_dir():
        return []

    settings = get_settings()
    try:
        dir_mtime = global_root.stat().st_mtime
    except OSError:
        dir_mtime = 0.0
    cache_key = (
        str(global_root),
        dir_mtime,
        settings.skills_builtin_allowlist or "",
        settings.skills_builtin_denylist or "",
    )
    now_mono = _time.monotonic()
    cached = _BUILTIN_SCAN_CACHE.get(cache_key)
    if cached and (now_mono - cached[0]) < 60.0:
        return [{**item, "enabled": item["name"] not in disabled_set} for item in cached[1]]

    items: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(global_root, followlinks=False):
        current_dir = Path(dirpath)
        is_root = current_dir == global_root
        has_skill_md = not is_root and "SKILL.md" in filenames
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in _BUILTIN_EXCLUDED_DIRS
            and not (has_skill_md and d in _SKILL_SUPPORT_DIRS)
        )
        if not has_skill_md:
            continue
        skill_md = current_dir / "SKILL.md"
        try:
            content = skill_md.read_text(encoding="utf-8")
            from datetime import timezone as _tz

            mtime = datetime.fromtimestamp(skill_md.stat().st_mtime, tz=_tz.utc)
        except (OSError, UnicodeDecodeError):
            continue

        dir_name = skill_md.parent.name
        parsed = parse_skill_markdown(content, fallback_name=dir_name)
        name = (parsed["name"] or dir_name).strip()
        if not name:
            continue
        try:
            rel_parts = skill_md.relative_to(global_root).parts
        except ValueError:
            rel_parts = ()
        path_category = rel_parts[0] if len(rel_parts) >= 3 else None
        category = path_category or parsed["category"]
        unavailable_reason = _builtin_unavailable_reason(content, name=name, category=category)
        items.append(
            {
                "name": name,
                "title": parsed["title"] or name,
                "description": parsed["description"],
                "category": category,
                "enabled": name not in disabled_set,
                "source": "builtin",
                "editable": False,
                "repo_url": None,
                "content": content,
                "tags": parsed["tags"],
                "updated_at": mtime,
                "available": unavailable_reason is None,
                "unavailable_reason": unavailable_reason,
            }
        )
    if len(_BUILTIN_SCAN_CACHE) > 32:
        _BUILTIN_SCAN_CACHE.clear()
    _BUILTIN_SCAN_CACHE[cache_key] = (now_mono, items)
    return items


def _serialize_user_skill(row: UserSkill) -> dict[str, Any]:
    parsed = parse_skill_markdown(row.content or "", fallback_name=row.name)
    tags = row.tags if isinstance(row.tags, list) else parsed["tags"]
    return {
        "name": row.name,
        "title": row.title or parsed["title"] or row.name,
        "description": row.description or parsed["description"],
        "category": row.category or parsed["category"],
        "enabled": bool(row.enabled),
        "source": row.source or "custom",
        "editable": (row.source or "custom") != "builtin",
        "repo_url": row.repo_url,
        "content": row.content,
        "tags": [str(t) for t in tags if str(t).strip()],
        "updated_at": row.updated_at,
    }


async def list_skills(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (
        await db.execute(select(UserSkill).where(UserSkill.user_id == user.id))
    ).scalars().all()

    by_name: dict[str, dict[str, Any]] = {}
    builtin_enabled_overrides: dict[str, bool] = {}
    for row in rows:
        if row.source == "builtin":
            builtin_enabled_overrides[row.name] = bool(row.enabled)
        else:
            by_name[row.name] = _serialize_user_skill(row)

    disabled_builtins = {name for name, enabled in builtin_enabled_overrides.items() if not enabled}
    for item in _scan_builtin_skills(disabled_builtins):
        if not item.get("available"):
            continue
        if item["name"] in by_name:
            continue
        cleaned = {k: v for k, v in item.items() if k not in ("available", "unavailable_reason")}
        if item["name"] in builtin_enabled_overrides:
            cleaned["enabled"] = builtin_enabled_overrides[item["name"]]
        by_name[item["name"]] = cleaned

    return sorted(by_name.values(), key=lambda s: (0 if s["source"] != "builtin" else 1, s["name"].lower()))


async def create_custom_skill(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    description: str,
    content: str,
    category: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    clean_name = validate_skill_name(name)
    existing = (
        await db.execute(
            select(UserSkill).where(UserSkill.user_id == user.id, UserSkill.name == clean_name)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.source != "builtin":
        raise SkillServiceError(f"技能 '{clean_name}' 已存在", 409)

    rendered = render_skill_markdown(
        content,
        name=clean_name,
        description=description,
        category=category,
    )
    assert_skill_safe({"SKILL.md": rendered})
    parsed = parse_skill_markdown(rendered, fallback_name=clean_name)

    if existing is not None:
        existing.title = parsed["title"] or clean_name
        existing.description = parsed["description"]
        existing.category = parsed["category"]
        existing.content = rendered
        existing.files = {"SKILL.md": rendered}
        existing.tags = parsed["tags"]
        existing.enabled = bool(enabled)
        existing.source = "custom"
        existing.repo_url = None
        existing.ref = None
        existing.path = None
        row = existing
    else:
        row = UserSkill(
            user_id=user.id,
            name=clean_name,
            title=parsed["title"] or clean_name,
            description=parsed["description"],
            category=parsed["category"],
            content=rendered,
            files={"SKILL.md": rendered},
            tags=parsed["tags"],
            enabled=bool(enabled),
            source="custom",
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_user_skill(row)


async def update_custom_skill(
    db: AsyncSession,
    user: User,
    name: str,
    *,
    description: str | None = None,
    content: str | None = None,
    category: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    clean_name = validate_skill_name(name)
    row = (
        await db.execute(
            select(UserSkill).where(
                UserSkill.user_id == user.id,
                UserSkill.name == clean_name,
                UserSkill.source != "builtin",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise SkillServiceError("仅支持编辑用户本地或已安装的技能", 404)

    next_raw = content if content is not None else row.content
    rendered = render_skill_markdown(
        next_raw,
        name=clean_name,
        description=description if description is not None else row.description,
        category=category if category is not None else row.category,
    )
    assert_skill_safe({"SKILL.md": rendered})
    parsed = parse_skill_markdown(rendered, fallback_name=clean_name)

    files = dict(row.files or {})
    files["SKILL.md"] = rendered
    row.title = parsed["title"] or clean_name
    row.description = parsed["description"]
    row.category = parsed["category"]
    row.content = rendered
    row.files = files
    row.tags = parsed["tags"]
    if enabled is not None:
        row.enabled = bool(enabled)

    await db.commit()
    await db.refresh(row)
    return _serialize_user_skill(row)


async def toggle_skill(
    db: AsyncSession,
    user: User,
    name: str,
    enabled: bool,
) -> dict[str, Any]:
    clean_name = validate_skill_name(name)
    known = {item["name"]: item for item in await list_skills(db, user)}
    row = (
        await db.execute(
            select(UserSkill).where(UserSkill.user_id == user.id, UserSkill.name == clean_name)
        )
    ).scalar_one_or_none()
    if clean_name not in known and row is None:
        raise SkillServiceError("技能不存在", 404)

    if row is not None:
        row.enabled = bool(enabled)
    else:
        meta = known[clean_name]
        row = UserSkill(
            user_id=user.id,
            name=clean_name,
            title=meta.get("title") or clean_name,
            description=meta.get("description") or "",
            category=meta.get("category"),
            content="",
            tags=meta.get("tags") or [],
            enabled=bool(enabled),
            source="builtin",
        )
        db.add(row)
    await db.commit()

    refreshed = {item["name"]: item for item in await list_skills(db, user)}
    if clean_name in refreshed:
        return refreshed[clean_name]
    return {
        "name": clean_name,
        "title": clean_name,
        "description": "",
        "category": None,
        "enabled": bool(enabled),
        "source": "builtin",
        "editable": False,
        "repo_url": None,
        "content": None,
        "tags": [],
        "updated_at": None,
    }


async def delete_skill(db: AsyncSession, user: User, name: str) -> None:
    clean_name = validate_skill_name(name)
    row = (
        await db.execute(
            select(UserSkill).where(
                UserSkill.user_id == user.id,
                UserSkill.name == clean_name,
                UserSkill.source != "builtin",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise SkillServiceError("技能不存在或为系统内置技能（不可删除）", 404)
    await db.delete(row)
    await db.commit()


def _is_public_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _validate_remote_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme.lower() != "https":
        raise SkillSsrfError("仅允许使用 HTTPS 协议访问 GitHub 仓库", 400)
    if parsed.username or parsed.password:
        raise SkillSsrfError("URL 不允许包含身份认证信息", 400)
    if parsed.port not in (None, 443):
        raise SkillSsrfError("仅允许访问标准 HTTPS 443 端口", 400)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if host not in ALLOWED_GITHUB_HOSTS:
        raise SkillSsrfError(f"禁止访问非 GitHub 允许域名的地址: {host or 'unknown'}", 400)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SkillSsrfError("禁止直接通过 IP 地址访问", 400)

    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        infos = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and not _is_public_ip(sockaddr[0]):
            raise SkillSsrfError("目标域名解析到内网或受限 IP，已拒绝访问", 400)
    return raw_url


def _clean_ref(ref: str | None) -> str | None:
    if ref is None:
        return None
    cleaned = ref.strip()
    if not cleaned:
        return None
    if ".." in cleaned or "\\" in cleaned or "\x00" in cleaned or any(ord(c) < 32 for c in cleaned):
        raise SkillServiceError("GitHub 分支/引用名称无效", 400)
    return cleaned.strip("/")


def _clean_subpath(path: str | None) -> str | None:
    if path is None:
        return None
    cleaned = path.replace("\\", "/").strip().strip("/")
    if not cleaned:
        return None
    return _safe_rel_path(cleaned)


def parse_github_source(
    raw_url: str,
    *,
    ref: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    raw = (raw_url or "").strip()
    if not raw:
        raise SkillServiceError("GitHub 地址不能为空", 400)

    override_ref = _clean_ref(ref)
    override_path = _clean_subpath(path)

    shorthand = _SHORTHAND_RE.match(raw)
    if shorthand and "://" not in raw:
        owner, repo = shorthand.group(1), shorthand.group(2)
        return {
            "mode": "dir",
            "owner": owner,
            "repo": repo,
            "ref": override_ref,
            "path": override_path,
            "repo_url": f"https://github.com/{owner}/{repo}",
        }

    _validate_remote_url(raw)
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    segments = [seg for seg in parsed.path.split("/") if seg]

    if host == "raw.githubusercontent.com":
        if len(segments) < 4:
            raise SkillServiceError("raw.githubusercontent.com 链接格式无效", 400)
        owner, repo, url_ref = segments[0], segments[1], segments[2]
        file_path = _safe_rel_path("/".join(segments[3:]))
        if not (_SEGMENT_RE.match(owner) and _SEGMENT_RE.match(repo)):
            raise SkillServiceError("GitHub 仓库名称无效", 400)
        return {
            "mode": "file",
            "owner": owner,
            "repo": repo,
            "ref": override_ref or _clean_ref(url_ref),
            "path": override_path or file_path,
            "repo_url": f"https://github.com/{owner}/{repo}",
        }

    if host == "github.com":
        if len(segments) < 2:
            raise SkillServiceError("GitHub 仓库链接格式无效", 400)
        owner = segments[0]
        repo = segments[1].removesuffix(".git")
        if not (_SEGMENT_RE.match(owner) and _SEGMENT_RE.match(repo)):
            raise SkillServiceError("GitHub 仓库名称无效", 400)
        if len(segments) == 2:
            return {
                "mode": "dir",
                "owner": owner,
                "repo": repo,
                "ref": override_ref,
                "path": override_path,
                "repo_url": f"https://github.com/{owner}/{repo}",
            }
        kind = segments[2]
        if kind == "tree" and len(segments) >= 4:
            url_ref = _clean_ref(segments[3])
            sub = _clean_subpath("/".join(segments[4:])) if len(segments) > 4 else None
            return {
                "mode": "dir",
                "owner": owner,
                "repo": repo,
                "ref": override_ref or url_ref,
                "path": override_path or sub,
                "repo_url": f"https://github.com/{owner}/{repo}",
            }
        if kind == "blob" and len(segments) >= 5:
            url_ref = _clean_ref(segments[3])
            file_path = _safe_rel_path("/".join(segments[4:]))
            return {
                "mode": "file",
                "owner": owner,
                "repo": repo,
                "ref": override_ref or url_ref,
                "path": override_path or file_path,
                "repo_url": f"https://github.com/{owner}/{repo}",
            }
        raise SkillServiceError("不支持的 GitHub URL 路径格式（支持仓库主页、tree 目录或 blob 文件链接）", 400)

    raise SkillSsrfError("仅支持 github.com 与 raw.githubusercontent.com 地址", 400)


async def _http_get_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    headers: dict[str, str] | None = None,
) -> bytes:
    current_url = _validate_remote_url(url)
    for _ in range(4):
        async with client.stream("GET", current_url, headers=headers) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise SkillServiceError("GitHub 重定向响应缺少 Location", 502)
                current_url = _validate_remote_url(location)
                continue
            if resp.status_code == 404:
                raise SkillServiceError("目标 GitHub 仓库或文件不存在", 404)
            if resp.status_code == 403:
                raise SkillServiceError("GitHub 接口访问受限或触发频率限制", 502)
            if resp.status_code >= 400:
                raise SkillServiceError(f"拉取 GitHub 资源失败 ({resp.status_code})", 502)

            cl = resp.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > max_bytes:
                raise SkillServiceError("GitHub 技能文件体积超过 512 KB 上限", 400)

            buf = bytearray()
            async for chunk in resp.aiter_bytes(32768):
                if len(buf) + len(chunk) > max_bytes:
                    raise SkillServiceError("GitHub 技能文件体积超过 512 KB 上限", 400)
                buf.extend(chunk)
            return bytes(buf)
    raise SkillServiceError("GitHub 重定向次数过多", 502)


async def _fetch_raw_skill_file(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    ref: str,
    file_path: str,
    remaining_bytes: int,
) -> bytes:
    encoded_path = "/".join(quote(seg, safe="") for seg in file_path.split("/"))
    url = (
        f"https://raw.githubusercontent.com/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/{quote(ref, safe='')}/{encoded_path}"
    )
    return await _http_get_bytes(client, url, max_bytes=remaining_bytes)


async def _fetch_directory_skill_files(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    ref: str | None,
    subpath: str | None,
) -> tuple[dict[str, str], str | None]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Whitz-Skills/1.0"}
    files: dict[str, str] = {}
    total_bytes = 0
    base_prefix = f"{subpath}/" if subpath else ""
    visited_dirs: set[str] = set()

    async def _walk(api_path: str, depth: int = 0) -> None:
        nonlocal total_bytes
        if depth > 10 or api_path in visited_dirs:
            return
        visited_dirs.add(api_path)
        encoded_api_path = "/".join(quote(seg, safe="") for seg in api_path.split("/")) if api_path else ""
        url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents"
        if encoded_api_path:
            url += f"/{encoded_api_path}"
        if ref:
            url += f"?ref={quote(ref, safe='')}"

        raw = await _http_get_bytes(client, url, max_bytes=MAX_GITHUB_TOTAL_BYTES, headers=headers)
        try:
            listing = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillServiceError("GitHub 目录响应格式无效", 502) from exc

        if isinstance(listing, dict):
            listing = [listing]
        if not isinstance(listing, list):
            raise SkillServiceError("GitHub 目录响应格式无效", 502)

        for entry in listing:
            if not isinstance(entry, dict):
                continue
            etype = entry.get("type")
            epath = str(entry.get("path") or "")
            ename = str(entry.get("name") or "")
            if not epath or ename.startswith("."):
                continue
            rel = epath[len(base_prefix) :] if base_prefix and epath.startswith(base_prefix) else epath
            rel = _safe_rel_path(rel)
            if etype == "dir":
                await _walk(epath, depth + 1)
                continue
            if etype != "file":
                continue

            _, ext = os.path.splitext(ename.lower())
            if ext not in SAFE_SUPPORT_EXTS:
                continue
            if len(files) >= MAX_GITHUB_FILES:
                raise SkillServiceError(f"GitHub 技能文件数量超过上限（最多 {MAX_GITHUB_FILES} 个文件）", 400)

            size_hint = int(entry.get("size") or 0)
            if total_bytes + size_hint > MAX_GITHUB_TOTAL_BYTES:
                raise SkillServiceError("GitHub 技能总大小超过 512 KB 上限", 400)

            download_url = entry.get("download_url")
            if not isinstance(download_url, str) or not download_url:
                continue
            remaining = MAX_GITHUB_TOTAL_BYTES - total_bytes
            content_bytes = await _http_get_bytes(client, download_url, max_bytes=remaining)
            total_bytes += len(content_bytes)
            try:
                text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            files[rel] = text

    try:
        await _walk(subpath or "")
    except SkillServiceError as exc:
        if exc.status_code != 502:
            raise
        target_rel = f"{subpath}/SKILL.md" if subpath else "SKILL.md"
        for candidate_ref in ([ref] if ref else ["main", "master"]):
            try:
                raw_bytes = await _fetch_raw_skill_file(
                    client, owner, repo, candidate_ref, target_rel, MAX_GITHUB_TOTAL_BYTES
                )
                return {"SKILL.md": raw_bytes.decode("utf-8")}, candidate_ref
            except SkillServiceError:
                continue
        raise

    return files, ref


async def fetch_github_skill(
    url: str,
    *,
    ref: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    spec = parse_github_source(url, ref=ref, path=path)
    owner = spec["owner"]
    repo = spec["repo"]
    resolved_ref = spec["ref"]
    target_path = spec["path"]

    async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(15.0)) as client:
        if spec["mode"] == "file":
            if not target_path or not target_path.lower().endswith(".md"):
                raise SkillServiceError("GitHub 单文件导入仅支持 Markdown 技能文件（如 SKILL.md）", 400)
            if not resolved_ref:
                raise SkillServiceError("缺少 GitHub 分支/引用名称", 400)
            raw_bytes = await _fetch_raw_skill_file(
                client, owner, repo, resolved_ref, target_path, MAX_GITHUB_TOTAL_BYTES
            )
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillServiceError("技能文件必须是 UTF-8 编码文本", 400) from exc
            files = {"SKILL.md": text}
        else:
            files, resolved_ref = await _fetch_directory_skill_files(client, owner, repo, resolved_ref, target_path)

    skill_md_key = next((k for k in files if k.lower() == "skill.md"), None)
    if skill_md_key is None:
        raise SkillServiceError("未在目标 GitHub 路径根目录下找到 SKILL.md", 400)
    if skill_md_key != "SKILL.md":
        files["SKILL.md"] = files.pop(skill_md_key)

    assert_skill_safe(files)

    skill_content = files["SKILL.md"]
    fallback = PurePosixPath(target_path).name if target_path and not target_path.lower().endswith(".md") else repo
    parsed = parse_skill_markdown(skill_content, fallback_name=fallback)
    skill_name = _slugify_skill_name(parsed["name"] or fallback)

    return {
        "name": skill_name,
        "description": parsed["description"],
        "category": parsed["category"],
        "content": skill_content,
        "files": files,
        "repo_url": spec["repo_url"],
        "ref": resolved_ref,
        "path": target_path,
    }


async def preview_github_skill(
    url: str,
    *,
    ref: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    fetched = await fetch_github_skill(url, ref=ref, path=path)
    return {
        "name": fetched["name"],
        "description": fetched["description"],
        "content": fetched["content"],
        "repo_url": fetched["repo_url"],
        "ref": fetched["ref"],
        "path": fetched["path"],
    }


async def _install_skill_files(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    files: dict[str, str],
    description: str | None = None,
    category: str | None = None,
    source: str = "github",
    repo_url: str | None = None,
    ref: str | None = None,
    path: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    clean_name = validate_skill_name(name)
    if "SKILL.md" not in files:
        raise SkillServiceError("缺少 SKILL.md 内容", 400)
    if len(files) > MAX_GITHUB_FILES:
        raise SkillServiceError(f"技能文件数量超过上限（最多 {MAX_GITHUB_FILES} 个文件）", 400)

    rendered_md = render_skill_markdown(
        files["SKILL.md"],
        name=clean_name,
        description=description,
        category=category,
    )
    sanitized_files: dict[str, str] = {"SKILL.md": rendered_md}
    total_bytes = len(rendered_md.encode("utf-8"))
    for rel, text in files.items():
        if rel == "SKILL.md":
            continue
        safe_rel = _safe_rel_path(rel)
        _, ext = os.path.splitext(safe_rel.lower())
        if ext not in SAFE_SUPPORT_EXTS:
            continue
        encoded_len = len(text.encode("utf-8"))
        if total_bytes + encoded_len > MAX_GITHUB_TOTAL_BYTES:
            raise SkillServiceError("技能总大小超过 512 KB 上限", 400)
        total_bytes += encoded_len
        sanitized_files[safe_rel] = text

    assert_skill_safe(sanitized_files)
    parsed = parse_skill_markdown(rendered_md, fallback_name=clean_name)

    existing = (
        await db.execute(
            select(UserSkill).where(UserSkill.user_id == user.id, UserSkill.name == clean_name)
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.title = parsed["title"] or clean_name
        existing.description = parsed["description"]
        existing.category = parsed["category"]
        existing.content = rendered_md
        existing.files = sanitized_files
        existing.tags = parsed["tags"]
        existing.enabled = bool(enabled)
        existing.source = source
        existing.repo_url = repo_url
        existing.ref = ref
        existing.path = path
        row = existing
    else:
        row = UserSkill(
            user_id=user.id,
            name=clean_name,
            title=parsed["title"] or clean_name,
            description=parsed["description"],
            category=parsed["category"],
            content=rendered_md,
            files=sanitized_files,
            tags=parsed["tags"],
            enabled=bool(enabled),
            source=source,
            repo_url=repo_url,
            ref=ref,
            path=path,
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_user_skill(row)


async def install_github_skill(
    db: AsyncSession,
    user: User,
    url: str,
    *,
    name: str | None = None,
    ref: str | None = None,
    path: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    fetched = await fetch_github_skill(url, ref=ref, path=path)
    target_name = validate_skill_name(name) if name else validate_skill_name(fetched["name"])
    return await _install_skill_files(
        db,
        user,
        name=target_name,
        files=fetched["files"],
        description=fetched["description"],
        category=fetched.get("category"),
        source="github",
        repo_url=fetched["repo_url"],
        ref=fetched["ref"],
        path=fetched["path"],
        enabled=enabled,
    )


async def stage_pending_skill(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    content: str,
    description: str = "",
    category: str | None = None,
    action: str = "create",
    source: str = "agent",
    repo_url: str | None = None,
    ref: str | None = None,
    path: str | None = None,
    files: dict[str, str] | None = None,
    conversation_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    clean_name = validate_skill_name(name)
    rendered_md = render_skill_markdown(
        content,
        name=clean_name,
        description=description,
        category=category,
    )
    staged_files = dict(files or {})
    staged_files["SKILL.md"] = rendered_md
    assert_skill_safe(staged_files)

    conv_uuid: uuid.UUID | None = None
    if conversation_id is not None:
        try:
            conv_uuid = uuid.UUID(str(conversation_id))
        except ValueError:
            conv_uuid = None

    parsed = parse_skill_markdown(rendered_md, fallback_name=clean_name)
    desc = description.strip() or parsed["description"]
    cat = category or parsed["category"]

    row = SkillPendingProposal(
        user_id=user_id,
        conversation_id=conv_uuid,
        name=clean_name,
        description=desc,
        category=cat,
        content=rendered_md,
        files=staged_files,
        action=action,
        source=source,
        repo_url=repo_url,
        ref=ref,
        path=path,
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "content": row.content,
        "action": row.action,
        "source": row.source,
        "conversation_id": row.conversation_id,
        "created_at": row.created_at,
    }


def _serialize_pending_skill(row: SkillPendingProposal) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "content": row.content,
        "action": row.action or "create",
        "source": row.source or "agent",
        "conversation_id": row.conversation_id,
        "created_at": row.created_at,
    }


async def list_pending(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await db.execute(
        select(SkillPendingProposal)
        .where(SkillPendingProposal.user_id == user_id, SkillPendingProposal.status == "pending")
        .order_by(SkillPendingProposal.created_at.asc(), SkillPendingProposal.id.asc())
    )
    return [_serialize_pending_skill(row) for row in result.scalars().all()]


async def resolve_pending(
    db: AsyncSession,
    user: User,
    pending_id: str,
    action: str,
    *,
    content_override: str | None = None,
    enabled: bool = True,
) -> dict[str, Any] | None:
    if not _SAFE_ID_RE.match(pending_id) or ".." in pending_id:
        raise SkillServiceError("无效的待审批技能 ID", 400)
    try:
        pending_uuid = uuid.UUID(pending_id)
    except ValueError as exc:
        raise SkillServiceError("待审批技能不存在", 404) from exc

    proposal = (
        await db.execute(
            select(SkillPendingProposal).where(
                SkillPendingProposal.id == pending_uuid,
                SkillPendingProposal.user_id == user.id,
                SkillPendingProposal.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise SkillServiceError("待审批技能不存在", 404)

    if action == "reject":
        await db.delete(proposal)
        await db.commit()
        return None
    if action != "approve":
        raise SkillServiceError(f"不支持的审批动作: {action}", 400)

    raw_files = proposal.files if isinstance(proposal.files, dict) else {}
    files: dict[str, str] = {
        str(k): str(v) for k, v in raw_files.items() if isinstance(k, str) and isinstance(v, str)
    }
    if content_override is not None:
        files["SKILL.md"] = content_override
    elif "SKILL.md" not in files:
        files["SKILL.md"] = proposal.content

    source = "github" if proposal.action == "install_github" or proposal.repo_url else "agent"
    installed = await _install_skill_files(
        db,
        user,
        name=proposal.name,
        files=files,
        description=proposal.description,
        category=proposal.category,
        source=source,
        repo_url=proposal.repo_url,
        ref=proposal.ref,
        path=proposal.path,
        enabled=enabled,
    )
    await db.delete(proposal)
    await db.commit()
    return installed
