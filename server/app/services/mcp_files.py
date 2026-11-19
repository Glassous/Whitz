from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Conversation, ConversationFile, User
from app.services import cos, file_chunks, file_parser, file_types

MAX_WRITE_FILE_BYTES = 2 * 1024 * 1024
WRITABLE_TEXT_EXTENSIONS = frozenset(
    ext
    for ext, (cat, _) in file_types.ALLOWED_FILE_TYPES.items()
    if cat in ("code", "document", "spreadsheet") and ext not in (".pdf", ".docx", ".xlsx")
)

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_workspace_files",
        "description": (
            "列出当前对话工作区中已上传并就绪的文件清单（包含 file_id、文件名、分类、MIME 类型、大小与作用域 scope）。"
            "默认同时包含用户的全局共享文件（scope='global'）。"
            "在用户提及已上传文件、附件、资料或需要确认当前工作区有哪些文件时调用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "当前对话的 UUID（从系统上下文中的 conversation_id 获取）",
                },
                "include_global": {
                    "type": "boolean",
                    "description": "是否同时列出用户的全局共享文件（默认 true）",
                    "default": True,
                },
            },
            "required": ["conversation_id"],
        },
    },
    {
        "name": "read_workspace_file",
        "description": (
            "按 file_id 读取当前对话工作区或用户全局共享文件的内容。支持文本/代码/CSV/JSON/YAML（按行分页）、"
            "PDF（按页分页）、Word DOCX（按段/表格行分页）、Excel XLSX（按工作表与行分页），"
            "以及 PNG/JPG/WebP/GIF 图片。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "当前对话的 UUID"},
                "file_id": {"type": "string", "description": "目标文件的 UUID"},
                "start_line": {
                    "type": "integer",
                    "description": "文本/代码/DOCX/XLSX 起始行号（从 1 开始，默认 1）",
                    "default": 1,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "每次最多读取的行数（1-500，默认 200）",
                    "default": 200,
                },
                "page_start": {
                    "type": "integer",
                    "description": "PDF 起始页码（从 1 开始，默认 1）",
                },
                "page_end": {
                    "type": "integer",
                    "description": "PDF 结束页码（默认最多一次读 5 页）",
                },
                "sheet_name": {
                    "type": "string",
                    "description": "Excel XLSX 指定工作表名称（不填则读取第一个工作表）",
                },
            },
            "required": ["conversation_id", "file_id"],
        },
    },
    {
        "name": "search_workspace_files",
        "description": (
            "在当前对话工作区及用户全局共享的文本、PDF、DOCX、XLSX 文件中按关键词检索，返回匹配行号/页码/工作表位置与片段，"
            "便于定位大文件里的关键章节。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "当前对话的 UUID"},
                "query": {"type": "string", "description": "要搜索的关键词（不区分大小写）"},
                "file_id": {
                    "type": "string",
                    "description": "可选：仅检索指定 file_id 的文件；留空则检索当前工作区全部可解析文件",
                },
            },
            "required": ["conversation_id", "query"],
        },
    },
    {
        "name": "write_workspace_file",
        "description": (
            "向当前对话工作区写入文本类产物文件（支持 Markdown、HTML、CSS、JS/TS、Python、JSON、CSV、YAML、XML、SQL、TXT 等），"
            "单文件最大 2 MB。写入成功后用户可在任务面板直接预览或下载。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "当前对话的 UUID"},
                "filename": {"type": "string", "description": "要写入的文件名（例如 report.md、index.html、summary.csv）"},
                "content": {"type": "string", "description": "UTF-8 文本文件内容"},
                "overwrite": {
                    "type": "boolean",
                    "description": "若当前对话已存在同名文件是否覆盖（默认 true）",
                    "default": True,
                },
            },
            "required": ["conversation_id", "filename", "content"],
        },
    },
]


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def _owned_conversation(db: AsyncSession, user: User, raw_conv_id: str) -> Conversation | None:
    try:
        conv_uuid = uuid.UUID(str(raw_conv_id))
    except (TypeError, ValueError):
        return None
    conv = await db.get(Conversation, conv_uuid)
    if conv is None or conv.user_id != user.id:
        return None
    return conv


async def _owned_ready_file(
    db: AsyncSession, user: User, conv: Conversation, raw_file_id: str
) -> ConversationFile | None:
    try:
        file_uuid = uuid.UUID(str(raw_file_id))
    except (TypeError, ValueError):
        return None
    row = await db.get(ConversationFile, file_uuid)
    if row is None or row.user_id != user.id or row.status != "ready":
        return None
    if row.conversation_id != conv.id and not row.is_global:
        return None
    return row


async def call_tool(
    db: AsyncSession,
    user: User,
    name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    args = arguments or {}
    conv_id = str(args.get("conversation_id") or "")
    conv = await _owned_conversation(db, user, conv_id)
    if conv is None:
        return _text_result("错误：对话不存在或无权访问该对话的工作区。", is_error=True)

    if name == "list_workspace_files":
        include_global = args.get("include_global")
        want_global = True if include_global is None else bool(include_global)
        if want_global:
            condition = or_(
                ConversationFile.conversation_id == conv.id,
                ConversationFile.is_global.is_(True),
            )
        else:
            condition = ConversationFile.conversation_id == conv.id

        rows = (
            await db.execute(
                select(ConversationFile)
                .where(
                    ConversationFile.user_id == user.id,
                    ConversationFile.status == "ready",
                    condition,
                )
                .order_by(ConversationFile.created_at.asc())
            )
        ).scalars().all()
        return _text_result(
            {
                "conversation_id": str(conv.id),
                "count": len(rows),
                "files": [
                    {
                        "file_id": str(r.id),
                        "filename": r.filename,
                        "ext": r.ext,
                        "category": r.category,
                        "mime_type": r.mime_type,
                        "size_bytes": r.size_bytes,
                        "source": r.source,
                        "is_global": r.is_global,
                        "scope": "conversation" if r.conversation_id == conv.id else "global",
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ],
            }
        )

    settings = get_settings()
    max_download = max(settings.max_file_size_bytes, 25 * 1024 * 1024)

    if name == "read_workspace_file":
        file_row = await _owned_ready_file(db, user, conv, str(args.get("file_id") or ""))
        if file_row is None:
            return _text_result("错误：指定文件不存在、未就绪或无权在当前对话访问。", is_error=True)
        try:
            raw = await cos.get_object_bytes(
                file_row.storage_key,
                max_bytes=max_download,
                settings=settings,
            )
            parsed = file_parser.read_file_content(
                raw,
                ext=file_row.ext,
                mime_type=file_row.mime_type,
                start_line=int(args.get("start_line") or 1),
                max_lines=int(args.get("max_lines") or 200),
                page_start=int(args["page_start"]) if args.get("page_start") is not None else None,
                page_end=int(args["page_end"]) if args.get("page_end") is not None else None,
                sheet_name=str(args["sheet_name"]) if args.get("sheet_name") else None,
            )
        except (cos.CosError, file_parser.FileParseError, ValueError) as exc:
            return _text_result(f"读取文件失败: {exc}", is_error=True)

        if parsed.get("format") == "image":
            content_blocks: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "file_id": str(file_row.id),
                            "filename": file_row.filename,
                            "mime_type": parsed["mime_type"],
                            "size_bytes": parsed["size_bytes"],
                            "note": parsed["content"],
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
            if parsed.get("image_base64"):
                content_blocks.append(
                    {
                        "type": "image",
                        "data": parsed["image_base64"],
                        "mimeType": parsed["mime_type"],
                    }
                )
            return {"content": content_blocks, "isError": False}

        return _text_result(
            {
                "file_id": str(file_row.id),
                "filename": file_row.filename,
                **parsed,
            }
        )

    if name == "search_workspace_files":
        query = str(args.get("query") or "").strip()
        if not query:
            return _text_result("错误：query 不能为空。", is_error=True)
        target_id = args.get("file_id")
        if target_id:
            file_row = await _owned_ready_file(db, user, conv, str(target_id))
            if file_row is None:
                return _text_result("错误：指定文件不存在、未就绪或无权在当前对话访问。", is_error=True)
            targets = [file_row]
        else:
            targets = list(
                (
                    await db.execute(
                        select(ConversationFile)
                        .where(
                            ConversationFile.user_id == user.id,
                            ConversationFile.status == "ready",
                            or_(
                                ConversationFile.conversation_id == conv.id,
                                ConversationFile.is_global.is_(True),
                            ),
                        )
                        .order_by(ConversationFile.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
        matches: list[dict[str, Any]] = []
        for row in targets:
            if row.category == "image":
                continue
            try:
                raw = await cos.get_object_bytes(
                    row.storage_key,
                    max_bytes=max_download,
                    settings=settings,
                )
                hits = file_parser.search_file_content(raw, ext=row.ext, query=query, max_hits=10)
            except cos.CosError:
                continue
            if hits:
                matches.append(
                    {
                        "file_id": str(row.id),
                        "filename": row.filename,
                        "scope": "conversation" if row.conversation_id == conv.id else "global",
                        "hits": hits,
                    }
                )
        return _text_result({"query": query, "matched_files": matches})

    if name == "write_workspace_file":
        if not settings.cos_configured:
            return _text_result("错误：对象存储 COS 尚未配置，无法写入工作区文件。", is_error=True)

        filename = file_types.sanitize_filename(str(args.get("filename") or ""))
        if not filename:
            return _text_result("错误：filename 不能为空。", is_error=True)
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        if ext not in WRITABLE_TEXT_EXTENSIONS:
            return _text_result(
                f"错误：不支持写入扩展名 {ext or '无扩展名'}。仅允许安全文本/代码/数据格式（如 .md, .html, .txt, .json, .csv, .py, .ts 等）。",
                is_error=True,
            )

        raw_content = args.get("content")
        if not isinstance(raw_content, str):
            return _text_result("错误：content 必须是字符串。", is_error=True)
        raw_bytes = raw_content.encode("utf-8")
        if not raw_bytes:
            return _text_result("错误：文件内容不能为空。", is_error=True)
        if len(raw_bytes) > MAX_WRITE_FILE_BYTES:
            return _text_result("错误：写入文件大小超过 2 MB 上限。", is_error=True)

        category, mime_type = file_types.ALLOWED_FILE_TYPES[ext]
        overwrite = True if args.get("overwrite") is None else bool(args.get("overwrite"))

        existing = (
            await db.execute(
                select(ConversationFile)
                .where(
                    ConversationFile.conversation_id == conv.id,
                    ConversationFile.user_id == user.id,
                    ConversationFile.filename == filename,
                    ConversationFile.status == "ready",
                )
                .order_by(ConversationFile.created_at.desc())
                .limit(1)
            )
        ).scalars().first()

        if existing is not None and not overwrite:
            return _text_result(f"错误：工作区中已存在文件 {filename}，若需覆盖请设置 overwrite=true。", is_error=True)

        if existing is not None:
            try:
                etag = await cos.put_object_bytes(
                    existing.storage_key,
                    raw_bytes,
                    mime_type,
                    settings=settings,
                )
            except cos.CosError as exc:
                return _text_result(f"写入文件失败: {exc}", is_error=True)
            existing.ext = ext
            existing.mime_type = mime_type
            existing.category = category
            existing.size_bytes = len(raw_bytes)
            existing.etag = etag
            existing.source = "assistant"
            existing.message_id = None
            existing.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(existing)
            await file_chunks.index_file_chunks_safe(db, existing, raw=raw_bytes)
            return _text_result(
                {
                    "status": "updated",
                    "file_id": str(existing.id),
                    "conversation_id": str(conv.id),
                    "filename": existing.filename,
                    "ext": existing.ext,
                    "category": existing.category,
                    "mime_type": existing.mime_type,
                    "size_bytes": existing.size_bytes,
                    "source": existing.source,
                }
            )

        existing_count = await db.scalar(
            select(func.count())
            .select_from(ConversationFile)
            .where(
                ConversationFile.conversation_id == conv.id,
                ConversationFile.status.in_(("ready", "pending")),
            )
        )
        if int(existing_count or 0) >= max(settings.max_files_per_conversation, 20):
            return _text_result(
                f"错误：当前对话文件数量已达上限（{settings.max_files_per_conversation} 个），请先清理部分文件。",
                is_error=True,
            )

        file_id = uuid.uuid4()
        storage_key = cos.build_storage_key(user.id, conv.id, file_id, filename, settings=settings)
        try:
            etag = await cos.put_object_bytes(storage_key, raw_bytes, mime_type, settings=settings)
        except cos.CosError as exc:
            return _text_result(f"写入文件失败: {exc}", is_error=True)

        row = ConversationFile(
            id=file_id,
            conversation_id=conv.id,
            user_id=user.id,
            filename=filename,
            ext=ext,
            mime_type=mime_type,
            category=category,
            size_bytes=len(raw_bytes),
            storage_key=storage_key,
            etag=etag,
            status="ready",
            source="assistant",
            is_global=False,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        await file_chunks.index_file_chunks_safe(db, row, raw=raw_bytes)
        return _text_result(
            {
                "status": "created",
                "file_id": str(row.id),
                "conversation_id": str(conv.id),
                "filename": row.filename,
                "ext": row.ext,
                "category": row.category,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "source": row.source,
            }
        )

    return _text_result(f"未知工具: {name}", is_error=True)
