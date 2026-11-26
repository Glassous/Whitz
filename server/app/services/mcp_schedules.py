from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.services import scheduler_service

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_scheduled_tasks",
        "description": "列出当前用户的所有定时任务及其调度规则、启用状态、下次触发时间与最近执行状态。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_disabled": {
                    "type": "boolean",
                    "description": "是否包含已暂停或已完成的定时任务（默认 true）",
                    "default": True,
                }
            },
        },
    },
    {
        "name": "get_scheduled_task_runs",
        "description": "查看指定定时任务的近期运行历史记录（状态、耗时、结果摘要与错误信息）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "定时任务 UUID"},
                "limit": {"type": "integer", "description": "返回条数（1-50，默认 10）", "default": 10},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "create_scheduled_task",
        "description": (
            "提议创建一个新的定时任务，提交后会在聊天界面生成确认卡片等待用户点击确认后生效。"
            "支持 schedule_type: once | interval | daily | weekly | monthly | cron。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "任务名称（简明易懂，不超过 120 字）"},
                "prompt": {"type": "string", "description": "到期时自动发送给助理执行的完整指令/提示词"},
                "schedule_type": {
                    "type": "string",
                    "enum": ["once", "interval", "daily", "weekly", "monthly", "cron"],
                    "description": "调度类型",
                },
                "schedule_config": {
                    "type": "object",
                    "description": (
                        "调度参数：once={'run_at': ISO8601}; interval={'every_minutes': 60}; "
                        "daily={'hour': 9, 'minute': 0}; weekly={'weekdays': [1,3,5], 'hour': 9, 'minute': 0} (1=周一..7=周日); "
                        "monthly={'day': 1, 'hour': 9, 'minute': 0}; cron={'expr': '0 9 * * 1-5'}"
                    ),
                },
                "target_mode": {
                    "type": "string",
                    "enum": ["dedicated", "main", "conversation"],
                    "description": "结果投递目标：dedicated=任务专属旁聊（推荐），main=主聊天，conversation=指定会话",
                    "default": "dedicated",
                },
                "conversation_id": {"type": "string", "description": "当前对话或指定目标对话 UUID（可选）"},
                "model_route": {
                    "type": "string",
                    "enum": ["auto", "default", "fast", "reasoning"],
                    "default": "auto",
                },
                "skill_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：定时任务执行时自动挂载的技能名称列表",
                },
                "max_runs": {
                    "type": "integer",
                    "description": "可选：最大执行次数上限（达到后自动停止）",
                },
                "timezone": {"type": "string", "description": "可选 IANA 时区，默认使用用户当前时区"},
                "reason": {"type": "string", "description": "向用户解释为何建议创建该定时任务"},
            },
            "required": ["name", "prompt", "schedule_type", "schedule_config"],
        },
    },
    {
        "name": "update_scheduled_task",
        "description": (
            "提议修改、暂停或恢复已有的定时任务，提交后需用户在确认卡片上点击确认生效。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "定时任务 UUID"},
                "action": {
                    "type": "string",
                    "enum": ["update", "pause", "resume"],
                    "default": "update",
                },
                "name": {"type": "string"},
                "prompt": {"type": "string"},
                "schedule_type": {
                    "type": "string",
                    "enum": ["once", "interval", "daily", "weekly", "monthly", "cron"],
                },
                "schedule_config": {"type": "object"},
                "target_mode": {"type": "string", "enum": ["dedicated", "main", "conversation"]},
                "model_route": {"type": "string", "enum": ["auto", "default", "fast", "reasoning"]},
                "skill_names": {"type": "array", "items": {"type": "string"}},
                "max_runs": {"type": "integer"},
                "timezone": {"type": "string"},
                "conversation_id": {"type": "string", "description": "当前所在对话 UUID（可选）"},
                "reason": {"type": "string", "description": "变更说明"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_scheduled_task",
        "description": "提议删除一条定时任务，提交后需用户在确认卡片上点击确认后删除。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "定时任务 UUID"},
                "conversation_id": {"type": "string", "description": "当前所在对话 UUID（可选）"},
                "reason": {"type": "string", "description": "删除原因"},
            },
            "required": ["task_id"],
        },
    },
]


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _parse_uuid(raw: Any) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw).strip())
    except ValueError:
        return None


async def call_tool(
    db: AsyncSession,
    user: User,
    name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    args = arguments or {}

    if name == "list_scheduled_tasks":
        include_disabled = True if args.get("include_disabled") is None else bool(args.get("include_disabled"))
        overview = await scheduler_service.list_overview(db, user)
        tasks = overview["tasks"]
        if not include_disabled:
            tasks = [t for t in tasks if t.get("enabled")]
        return _text_result(
            {
                "quota": overview["quota"],
                "count": len(tasks),
                "tasks": [
                    {
                        "id": str(t["id"]),
                        "name": t["name"],
                        "prompt": t["prompt"],
                        "schedule_type": t["schedule_type"],
                        "schedule_description": t["schedule_description"],
                        "timezone": t["timezone"],
                        "target_mode": t["target_mode"],
                        "enabled": t["enabled"],
                        "status": t["status"],
                        "next_run_at": t["next_run_at"],
                        "last_run_at": t["last_run_at"],
                        "last_run_status": t["last_run_status"],
                        "run_count": t["run_count"],
                    }
                    for t in tasks
                ],
            }
        )

    if name == "get_scheduled_task_runs":
        task_uuid = _parse_uuid(args.get("task_id"))
        if task_uuid is None:
            return _text_result("错误：task_id 必须是有效的 UUID", is_error=True)
        limit = int(args.get("limit") or 10)
        try:
            detail = await scheduler_service.get_task_detail(db, user, task_uuid, runs_limit=limit)
        except scheduler_service.ScheduleServiceError as exc:
            return _text_result(f"错误：{exc.detail}", is_error=True)
        return _text_result(
            {
                "task_id": str(detail["id"]),
                "name": detail["name"],
                "runs": detail.get("runs") or [],
            }
        )

    if name == "create_scheduled_task":
        conv_uuid = _parse_uuid(args.get("conversation_id"))
        payload = {
            "name": str(args.get("name") or "").strip(),
            "prompt": str(args.get("prompt") or "").strip(),
            "schedule_type": str(args.get("schedule_type") or "").strip().lower(),
            "schedule_config": args.get("schedule_config") if isinstance(args.get("schedule_config"), dict) else {},
            "target_mode": str(args.get("target_mode") or "dedicated").strip().lower(),
            "model_route": str(args.get("model_route") or "auto").strip().lower(),
            "timezone": str(args.get("timezone") or user.timezone or "Asia/Shanghai").strip(),
        }
        if isinstance(args.get("skill_names"), list):
            payload["skill_names"] = [str(s).strip() for s in args["skill_names"] if str(s).strip()][:10]
        if isinstance(args.get("max_runs"), int) and args["max_runs"] >= 1:
            payload["max_runs"] = args["max_runs"]
        if conv_uuid and payload["target_mode"] == "conversation":
            payload["conversation_id"] = str(conv_uuid)
        try:
            proposal = await scheduler_service.create_proposal(
                db,
                user,
                action="create",
                payload=payload,
                conversation_id=conv_uuid,
                reason=str(args.get("reason") or ""),
            )
        except scheduler_service.ScheduleServiceError as exc:
            return _text_result(f"错误：{exc.detail}", is_error=True)
        return _text_result(
            {
                "status": "pending_confirmation",
                "proposal_id": proposal["id"],
                "schedule_description": proposal["schedule_description"],
                "message": "已提交新建定时任务提案，请提醒用户在聊天界面的确认卡片中点击「确认生效」。",
            }
        )

    if name == "update_scheduled_task":
        task_uuid = _parse_uuid(args.get("task_id"))
        if task_uuid is None:
            return _text_result("错误：task_id 必须是有效的 UUID", is_error=True)
        conv_uuid = _parse_uuid(args.get("conversation_id"))
        action = str(args.get("action") or "update").strip().lower()
        if action not in ("update", "pause", "resume"):
            return _text_result("错误：action 仅支持 update | pause | resume", is_error=True)

        payload: dict[str, Any] = {}
        for key in (
            "name",
            "prompt",
            "schedule_type",
            "schedule_config",
            "target_mode",
            "model_route",
            "skill_names",
            "max_runs",
            "timezone",
        ):
            if args.get(key) is not None:
                payload[key] = args.get(key)
        try:
            proposal = await scheduler_service.create_proposal(
                db,
                user,
                action=action,
                payload=payload,
                target_task_id=task_uuid,
                conversation_id=conv_uuid,
                reason=str(args.get("reason") or ""),
            )
        except scheduler_service.ScheduleServiceError as exc:
            return _text_result(f"错误：{exc.detail}", is_error=True)
        return _text_result(
            {
                "status": "pending_confirmation",
                "proposal_id": proposal["id"],
                "action": action,
                "message": "已提交定时任务变更提案，请提醒用户在聊天界面的确认卡片中点击确认。",
            }
        )

    if name == "delete_scheduled_task":
        task_uuid = _parse_uuid(args.get("task_id"))
        if task_uuid is None:
            return _text_result("错误：task_id 必须是有效的 UUID", is_error=True)
        conv_uuid = _parse_uuid(args.get("conversation_id"))
        try:
            proposal = await scheduler_service.create_proposal(
                db,
                user,
                action="delete",
                payload={},
                target_task_id=task_uuid,
                conversation_id=conv_uuid,
                reason=str(args.get("reason") or ""),
            )
        except scheduler_service.ScheduleServiceError as exc:
            return _text_result(f"错误：{exc.detail}", is_error=True)
        return _text_result(
            {
                "status": "pending_confirmation",
                "proposal_id": proposal["id"],
                "message": "已提交删除定时任务提案，请提醒用户在聊天界面的确认卡片中点击确认。",
            }
        )

    return _text_result(f"未知定时任务工具：{name}", is_error=True)
