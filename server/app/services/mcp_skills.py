from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.services import skills_service

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_user_skills",
        "description": "列出当前用户已安装或自定义的技能清单及其启用状态。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_disabled": {
                    "type": "boolean",
                    "description": "是否包含已禁用的技能（默认 true）",
                    "default": True,
                }
            },
        },
    },
    {
        "name": "preview_github_skill",
        "description": (
            "从 GitHub 仓库（支持 owner/repo、tree、blob、raw.githubusercontent.com 链接）预览 SKILL.md 内容并执行静态安全检查。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "GitHub 仓库地址或 owner/repo 简写"},
                "ref": {"type": "string", "description": "可选分支或 tag"},
                "path": {"type": "string", "description": "可选子目录或 SKILL.md 路径"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "install_github_skill",
        "description": (
            "从 GitHub 获取并安全校验技能后，提交安装提案等待用户在聊天界面点击确认后生效（不会直接越权写入）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "GitHub 仓库地址或 owner/repo 简写"},
                "name": {"type": "string", "description": "可选覆盖安装后的技能名称"},
                "ref": {"type": "string", "description": "可选分支或 tag"},
                "path": {"type": "string", "description": "可选子目录或 SKILL.md 路径"},
                "conversation_id": {"type": "string", "description": "可选当前对话 UUID"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "create_user_skill",
        "description": (
            "创建新的用户自定义 SKILL.md 技能提案并执行安全校验，提交后需等待用户在聊天界面点击确认生效。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能名称（字母、数字、连字符或下划线）"},
                "description": {"type": "string", "description": "简短技能描述"},
                "content": {"type": "string", "description": "SKILL.md Markdown 正文内容"},
                "category": {"type": "string", "description": "可选分类名称"},
                "conversation_id": {"type": "string", "description": "可选当前对话 UUID"},
            },
            "required": ["name", "content"],
        },
    },
]


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def call_tool(
    db: AsyncSession,
    user: User,
    name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    args = arguments or {}

    if name == "list_user_skills":
        include_disabled = True if args.get("include_disabled") is None else bool(args.get("include_disabled"))
        items = await skills_service.list_skills(db, user)
        if not include_disabled:
            items = [item for item in items if item.get("enabled")]
        return _text_result(
            {
                "count": len(items),
                "skills": [
                    {
                        "name": item["name"],
                        "description": item["description"],
                        "category": item.get("category"),
                        "enabled": item["enabled"],
                        "source": item["source"],
                        "repo_url": item.get("repo_url"),
                    }
                    for item in items
                ],
            }
        )

    if name == "preview_github_skill":
        url = str(args.get("url") or "").strip()
        ref = str(args["ref"]).strip() if args.get("ref") else None
        path = str(args["path"]).strip() if args.get("path") else None
        try:
            preview = await skills_service.preview_github_skill(url, ref=ref, path=path)
        except skills_service.SkillServiceError as exc:
            return _text_result(f"错误：{exc.detail}", is_error=True)
        return _text_result(preview)

    if name == "install_github_skill":
        url = str(args.get("url") or "").strip()
        ref = str(args["ref"]).strip() if args.get("ref") else None
        path = str(args["path"]).strip() if args.get("path") else None
        name_override = str(args["name"]).strip() if args.get("name") else None
        conv_id = str(args["conversation_id"]).strip() if args.get("conversation_id") else None
        try:
            fetched = await skills_service.fetch_github_skill(url, ref=ref, path=path)
            target_name = skills_service.validate_skill_name(name_override or fetched["name"])
            pending = await skills_service.stage_pending_skill(
                db,
                user.id,
                name=target_name,
                content=fetched["content"],
                description=fetched["description"],
                category=fetched.get("category"),
                action="install_github",
                source="agent",
                repo_url=fetched["repo_url"],
                ref=fetched["ref"],
                path=fetched["path"],
                files=fetched["files"],
                conversation_id=conv_id,
            )
        except skills_service.SkillServiceError as exc:
            return _text_result(f"错误：{exc.detail}", is_error=True)
        return _text_result(
            {
                "status": "pending_user_confirmation",
                "pending_id": pending["id"],
                "name": pending["name"],
                "description": pending["description"],
                "repo_url": fetched["repo_url"],
                "message": "已通过安全扫描并生成安装确认请求，请提示用户在界面卡片中确认安装。",
            }
        )

    if name == "create_user_skill":
        skill_name = str(args.get("name") or "").strip()
        content = str(args.get("content") or "")
        description = str(args.get("description") or "").strip()
        category = str(args["category"]).strip() if args.get("category") else None
        conv_id = str(args["conversation_id"]).strip() if args.get("conversation_id") else None
        try:
            pending = await skills_service.stage_pending_skill(
                db,
                user.id,
                name=skill_name,
                content=content,
                description=description,
                category=category,
                action="create",
                source="agent",
                conversation_id=conv_id,
            )
        except skills_service.SkillServiceError as exc:
            return _text_result(f"错误：{exc.detail}", is_error=True)
        return _text_result(
            {
                "status": "pending_user_confirmation",
                "pending_id": pending["id"],
                "name": pending["name"],
                "description": pending["description"],
                "message": "已通过安全扫描并生成技能创建确认请求，请提示用户在界面卡片中确认保存。",
            }
        )

    return _text_result(f"未知工具: {name}", is_error=True)
