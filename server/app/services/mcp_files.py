from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Conversation, ConversationFile, ConversationFileLink, FileChunk, User
from app.services import cos, file_cache, file_chunks, file_parser, file_provenance, file_types, file_uploads

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
            "列出当前对话工作区中已上传并就绪的文件清单（包含 file_id、文件名、分类、MIME 类型、大小、索引状态与作用域 scope）。"
            "默认同时包含用户的全局共享资料库文件（scope='library'）。"
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
        "name": "inspect_workspace_file",
        "description": (
            "快速查看指定工作区或资料库文件的结构大纲与元信息（总行数、PDF 总页数与扫描件检测、Excel 全部工作表及表头、"
            "Markdown 章节目录、代码顶层符号、摘要与索引状态），适合在精读大文件前先定位章节或工作表。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "当前对话的 UUID"},
                "file_id": {"type": "string", "description": "目标文件的 UUID（与 filename 二选一，优先传 file_id）"},
                "filename": {"type": "string", "description": "目标文件名（未提供 file_id 时按当前工作区/资料库最新同名文件匹配）"},
            },
            "required": ["conversation_id"],
        },
    },
    {
        "name": "read_workspace_file",
        "description": (
            "按 file_id（或 filename）读取当前对话工作区或用户全局共享文件的内容。支持文本/代码/CSV/JSON/YAML（按行分页）、"
            "PDF（按页分页）、Word DOCX（按段/表格行分页）、Excel XLSX（按工作表与行分页），"
            "以及 PNG/JPG/WebP/GIF 图片（通过原生视觉通道查看原图）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "当前对话的 UUID"},
                "file_id": {"type": "string", "description": "目标文件的 UUID（与 filename 二选一，优先传 file_id）"},
                "filename": {"type": "string", "description": "目标文件名（当未提供 file_id 时按当前工作区/资料库最新同名文件匹配）"},
                "start_line": {
                    "type": "integer",
                    "description": "文本/代码/DOCX/XLSX 起始行号（从 1 开始，默认 1）",
                    "default": 1,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "每次最多读取的行数（1-600，默认 250）",
                    "default": 250,
                },
                "page_start": {
                    "type": "integer",
                    "description": "PDF 起始页码（从 1 开始，默认 1）",
                },
                "page_end": {
                    "type": "integer",
                    "description": "PDF 结束页码（默认最多一次读 8 页）",
                },
                "sheet_name": {
                    "type": "string",
                    "description": "Excel XLSX 指定工作表名称（不填则读取第一个工作表）",
                },
            },
            "required": ["conversation_id"],
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
                    "description": "可选：仅检索指定 file_id 的文件；留空则检索当前工作区及资料库全部可解析文件",
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
    {
        "name": "edit_workspace_file",
        "description": (
            "局部修改工作区中已存在的纯文本/代码/Markdown/HTML/CSV 文件，无需全量重写。"
            "支持两种模式：（1）精准文本替换：提供 old_text 与 new_text（可选 replace_all）；"
            "（2）行号区间替换：提供 start_line、end_line（从 1 开始的闭区间）与 new_content。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "当前对话的 UUID"},
                "file_id": {"type": "string", "description": "目标文件的 UUID（与 filename 二选一，优先传 file_id）"},
                "filename": {"type": "string", "description": "目标文件名（当未提供 file_id 时按当前对话最新同名文件匹配）"},
                "old_text": {"type": "string", "description": "文本替换模式：要被替换的原文本片段"},
                "new_text": {"type": "string", "description": "文本替换模式：替换后的新文本片段"},
                "replace_all": {
                    "type": "boolean",
                    "description": "文本替换模式：是否替换全部匹配项（默认 false，若匹配多处将提示补充上下文）",
                    "default": False,
                },
                "start_line": {"type": "integer", "description": "行区间替换模式：起始行号（从 1 开始，含）"},
                "end_line": {"type": "integer", "description": "行区间替换模式：结束行号（从 1 开始，含）"},
                "new_content": {"type": "string", "description": "行区间替换模式：替换该行区间的新文本内容"},
            },
            "required": ["conversation_id"],
        },
    },
]


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
    return row


async def _resolve_ready_file(
    db: AsyncSession,
    user: User,
    conv: Conversation,
    *,
    raw_file_id: str = "",
    raw_filename: str = "",
) -> ConversationFile | None:
    if raw_file_id.strip():
        found = await _owned_ready_file(db, user, conv, raw_file_id.strip())
        if found is not None:
            return found
    cleaned_name = file_types.sanitize_filename(raw_filename or "")
    if not cleaned_name:
        return None
    # Prefer files in the current conversation workspace (direct or linked)
    linked_ids = select(ConversationFileLink.file_id).where(
        ConversationFileLink.conversation_id == conv.id,
        ConversationFileLink.user_id == user.id,
    )
    in_conv = (
        await db.execute(
            select(ConversationFile)
            .where(
                ConversationFile.user_id == user.id,
                ConversationFile.status == "ready",
                ConversationFile.filename == cleaned_name,
                or_(
                    ConversationFile.conversation_id == conv.id,
                    ConversationFile.id.in_(linked_ids),
                ),
            )
            .order_by(ConversationFile.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if in_conv is not None:
        return in_conv
    return (
        await db.execute(
            select(ConversationFile)
            .where(
                ConversationFile.user_id == user.id,
                ConversationFile.status == "ready",
                ConversationFile.filename == cleaned_name,
            )
            .order_by(ConversationFile.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


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

    linked_id_set = set(
        (
            await db.execute(
                select(ConversationFileLink.file_id).where(
                    ConversationFileLink.conversation_id == conv.id,
                    ConversationFileLink.user_id == user.id,
                )
            )
        )
        .scalars()
        .all()
    )

    if name == "list_workspace_files":
        include_global = args.get("include_global")
        want_global = True if include_global is None else bool(include_global)
        if want_global:
            rows = list(
                (
                    await db.execute(
                        select(ConversationFile)
                        .where(
                            ConversationFile.user_id == user.id,
                            ConversationFile.status == "ready",
                        )
                        .order_by(ConversationFile.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        else:
            rows = await file_uploads.list_conversation_workspace_files(
                db,
                user_id=user.id,
                conversation_id=conv.id,
                order_asc=False,
            )
        provenance_map = await file_provenance.resolve_files_provenance(db, user, rows)
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
                        "is_global": True,
                        "scope": (
                            "conversation"
                            if (r.conversation_id == conv.id or r.id in linked_id_set)
                            else "library"
                        ),
                        "index_status": r.index_status or "ready",
                        "summary": (r.summary or "")[:160] if r.summary else None,
                        "conversation_id": str(r.conversation_id) if r.conversation_id else None,
                        "conversation_title": (provenance_map.get(r.id) or {}).get("conversation_title"),
                        "message_id": str(r.message_id) if r.message_id else None,
                        "turn_role": (provenance_map.get(r.id) or {}).get("turn_role"),
                        "qa_snippet": (provenance_map.get(r.id) or {}).get("qa_snippet"),
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ],
            }
        )

    settings = get_settings()

    if name == "inspect_workspace_file":
        file_row = await _resolve_ready_file(
            db,
            user,
            conv,
            raw_file_id=str(args.get("file_id") or ""),
            raw_filename=str(args.get("filename") or ""),
        )
        if file_row is None:
            return _text_result("错误：指定文件不存在、未就绪或无权在当前对话访问。", is_error=True)

        if file_row.category == "image":
            return _text_result(
                {
                    "file_id": str(file_row.id),
                    "filename": file_row.filename,
                    "format": "image",
                    "category": "image",
                    "mime_type": file_row.mime_type,
                    "size_bytes": file_row.size_bytes,
                    "index_status": file_row.index_status or "ready",
                    "summary": file_row.summary or None,
                    "note": "如需查看图片画面细节，请调用 read_workspace_file 加载原生视觉内容。",
                }
            )
        try:
            parsed = await file_cache.get_or_parse_file(file_row, settings=settings)
        except (cos.CosError, file_parser.FileParseError, ValueError) as exc:
            return _text_result(f"检查文件结构失败: {exc}", is_error=True)
        return _text_result(
            {
                "file_id": str(file_row.id),
                "filename": file_row.filename,
                "category": file_row.category,
                "mime_type": file_row.mime_type,
                "size_bytes": file_row.size_bytes,
                "index_status": file_row.index_status or "ready",
                "summary": file_row.summary or None,
                "outline": parsed.outline,
                "outline_text": file_parser.format_outline_text(parsed, filename=file_row.filename),
            }
        )

    if name == "read_workspace_file":
        file_row = await _resolve_ready_file(
            db,
            user,
            conv,
            raw_file_id=str(args.get("file_id") or ""),
            raw_filename=str(args.get("filename") or ""),
        )
        if file_row is None:
            return _text_result("错误：指定文件不存在、未就绪或无权在当前对话访问。", is_error=True)

        # Images: return lightweight visual observation metadata + COS original URL (NO multi-MB base64 JSON!)
        if file_row.category == "image":
            image_url: str | None = None
            if settings.cos_configured and file_row.storage_key:
                try:
                    image_url = cos.presign_ai_media_url(
                        key=file_row.storage_key,
                        size_bytes=int(file_row.size_bytes or 0),
                        expires_seconds=900,
                        settings=settings,
                    )
                except cos.CosError:
                    image_url = None
            return _text_result(
                {
                    "file_id": str(file_row.id),
                    "filename": file_row.filename,
                    "format": "image",
                    "mime_type": file_row.mime_type,
                    "size_bytes": int(file_row.size_bytes or 0),
                    "image_url": image_url,
                    "whitz_visual_attachment": True,
                    "note": "图片已通过原生多模态通道加载，请直接查看紧随其后的图片画面作答。",
                }
            )

        try:
            parsed = await file_cache.get_or_parse_file(file_row, settings=settings)
            sliced = file_parser.read_from_parsed(
                parsed,
                start_line=int(args.get("start_line") or 1),
                max_lines=int(args.get("max_lines") or file_parser.DEFAULT_MAX_LINES),
                page_start=int(args["page_start"]) if args.get("page_start") is not None else None,
                page_end=int(args["page_end"]) if args.get("page_end") is not None else None,
                sheet_name=str(args["sheet_name"]) if args.get("sheet_name") else None,
            )
        except (cos.CosError, file_parser.FileParseError, ValueError) as exc:
            return _text_result(f"读取文件失败: {exc}", is_error=True)

        return _text_result(
            {
                "file_id": str(file_row.id),
                "filename": file_row.filename,
                **sliced,
            }
        )

    if name == "search_workspace_files":
        query = str(args.get("query") or "").strip()
        if not query:
            return _text_result("错误：query 不能为空。", is_error=True)
        target_id = args.get("file_id")
        target_row: ConversationFile | None = None
        if target_id:
            target_row = await _owned_ready_file(db, user, conv, str(target_id))
            if target_row is None:
                return _text_result("错误：指定文件不存在、未就绪或无权在当前对话访问。", is_error=True)

        # Fast path: query indexed file_chunks in Postgres first (0 COS downloads!)
        pattern = f"%{_escape_like(query)}%"
        chunk_stmt = (
            select(FileChunk, ConversationFile)
            .join(ConversationFile, FileChunk.file_id == ConversationFile.id)
            .where(
                FileChunk.user_id == user.id,
                ConversationFile.status == "ready",
                FileChunk.content.ilike(pattern, escape="\\"),
            )
            .order_by(ConversationFile.created_at.desc(), FileChunk.chunk_index.asc())
            .limit(40)
        )
        if target_row is not None:
            chunk_stmt = chunk_stmt.where(FileChunk.file_id == target_row.id)

        chunk_rows = (await db.execute(chunk_stmt)).all()
        matches_by_file: dict[uuid.UUID, dict[str, Any]] = {}
        for chunk, frow in chunk_rows:
            entry = matches_by_file.setdefault(
                frow.id,
                {
                    "file_id": str(frow.id),
                    "filename": frow.filename,
                    "scope": (
                        "conversation"
                        if (frow.conversation_id == conv.id or frow.id in linked_id_set)
                        else "global"
                    ),
                    "hits": [],
                },
            )
            if len(entry["hits"]) >= 8:
                continue
            # Extract the exact matching line from the chunk for precise locator feedback
            snippet = chunk.content.strip()[:300]
            for ln in chunk.content.splitlines():
                if query.lower() in ln.lower():
                    snippet = ln.strip()[:300]
                    break
            entry["hits"].append(
                {
                    "location": chunk.locator or chunk.section_path or "正文匹配",
                    "snippet": snippet,
                }
            )

        # Fallback scan ONLY for target/unindexed files that have no chunks yet (using bounded file_cache)
        if target_row is not None:
            fallback_targets = [target_row] if (target_row.id not in matches_by_file and int(target_row.indexed_chunks or 0) == 0) else []
        else:
            unindexed = list(
                (
                    await db.execute(
                        select(ConversationFile)
                        .where(
                            ConversationFile.user_id == user.id,
                            ConversationFile.status == "ready",
                            ConversationFile.category != "image",
                            or_(
                                ConversationFile.indexed_chunks == 0,
                                ConversationFile.index_status != "ready",
                            ),
                        )
                        .order_by(ConversationFile.created_at.desc())
                        .limit(6)
                    )
                )
                .scalars()
                .all()
            )
            fallback_targets = [r for r in unindexed if r.id not in matches_by_file]

        for row in fallback_targets:
            if row.category == "image":
                continue
            try:
                parsed = await file_cache.get_or_parse_file(row, settings=settings)
                hits = file_parser.search_parsed_content(parsed, query=query, max_hits=10)
            except (cos.CosError, file_parser.FileParseError):
                continue
            if hits:
                matches_by_file[row.id] = {
                    "file_id": str(row.id),
                    "filename": row.filename,
                    "scope": (
                        "conversation"
                        if (row.conversation_id == conv.id or row.id in linked_id_set)
                        else "global"
                    ),
                    "hits": hits,
                }

        return _text_result({"query": query, "matched_files": list(matches_by_file.values())})

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
            existing.is_global = True
            existing.message_id = None
            existing.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(existing)
            file_cache.invalidate_file_cache(existing.id)
            await file_chunks.index_file_chunks_safe(db, existing, raw=raw_bytes)
            await db.refresh(existing)
            from app.services import realtime_bus

            await realtime_bus.publish_user_event(
                user.id,
                "library.updated",
                {"action": "updated", "file_id": str(existing.id), "conversation_id": str(conv.id)},
            )
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
            is_global=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        file_cache.invalidate_file_cache(row.id)
        await file_chunks.index_file_chunks_safe(db, row, raw=raw_bytes)
        await db.refresh(row)
        from app.services import realtime_bus

        await realtime_bus.publish_user_event(
            user.id,
            "library.updated",
            {"action": "added", "file_id": str(row.id), "conversation_id": str(conv.id)},
        )
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

    if name == "edit_workspace_file":
        if not settings.cos_configured:
            return _text_result("错误：对象存储 COS 尚未配置，无法编辑工作区文件。", is_error=True)

        file_row = await _resolve_ready_file(
            db,
            user,
            conv,
            raw_file_id=str(args.get("file_id") or ""),
            raw_filename=str(args.get("filename") or ""),
        )
        if file_row is None:
            return _text_result("错误：未找到目标文件（请检查 file_id 或 filename）。", is_error=True)

        ext = (file_row.ext or os.path.splitext(file_row.filename)[1]).lower()
        if ext not in WRITABLE_TEXT_EXTENSIONS:
            return _text_result(
                f"错误：文件 {file_row.filename}（{ext}）不是可编辑的纯文本/代码格式。",
                is_error=True,
            )

        try:
            current_raw = await cos.get_object_bytes(
                file_row.storage_key,
                max_bytes=MAX_WRITE_FILE_BYTES,
                settings=settings,
            )
        except cos.CosError as exc:
            return _text_result(f"读取原文件失败: {exc}", is_error=True)

        current_text = file_parser.decode_text(current_raw)
        lines_before = len(current_text.splitlines())

        old_text = args.get("old_text")
        new_text = args.get("new_text")
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        new_content = args.get("new_content")

        if isinstance(old_text, str) and isinstance(new_text, str):
            if not old_text:
                return _text_result("错误：old_text 不能为空。", is_error=True)
            occurrences = current_text.count(old_text)
            if occurrences == 0:
                return _text_result(
                    "错误：在文件中未找到完全匹配的 old_text，请先调用 read_workspace_file 核对准确内容。",
                    is_error=True,
                )
            replace_all = bool(args.get("replace_all", False))
            if occurrences > 1 and not replace_all:
                return _text_result(
                    f"错误：old_text 在文件中匹配了 {occurrences} 处，请补充更多上下文使其唯一，或设置 replace_all=true。",
                    is_error=True,
                )
            updated_text = current_text.replace(old_text, new_text) if replace_all else current_text.replace(old_text, new_text, 1)
        elif start_line is not None and end_line is not None and isinstance(new_content, str):
            try:
                s_idx = int(start_line)
                e_idx = int(end_line)
            except (TypeError, ValueError):
                return _text_result("错误：start_line 和 end_line 必须是整数。", is_error=True)
            orig_lines = current_text.splitlines(keepends=True)
            total_lines = len(orig_lines)
            if s_idx < 1 or e_idx < s_idx or s_idx > max(1, total_lines + 1):
                return _text_result(
                    f"错误：行号范围无效（start_line={s_idx}, end_line={e_idx}, 文件共 {total_lines} 行）。",
                    is_error=True,
                )
            e_clamped = min(e_idx, total_lines)
            replacement = new_content
            if replacement and not replacement.endswith("\n") and e_clamped < total_lines:
                replacement += "\n"
            updated_text = "".join(orig_lines[: s_idx - 1]) + replacement + "".join(orig_lines[e_clamped:])
        else:
            return _text_result(
                "错误：请提供文本替换参数 (old_text + new_text) 或行号区间参数 (start_line + end_line + new_content)。",
                is_error=True,
            )

        raw_bytes = updated_text.encode("utf-8")
        if len(raw_bytes) > MAX_WRITE_FILE_BYTES:
            return _text_result("错误：修改后的文件大小超过 2 MB 上限。", is_error=True)

        try:
            etag = await cos.put_object_bytes(
                file_row.storage_key,
                raw_bytes,
                file_row.mime_type,
                settings=settings,
            )
        except cos.CosError as exc:
            return _text_result(f"写回文件失败: {exc}", is_error=True)

        file_row.size_bytes = len(raw_bytes)
        file_row.etag = etag
        file_row.updated_at = datetime.now(timezone.utc)
        if file_row.conversation_id == conv.id:
            file_row.source = "assistant"
            file_row.message_id = None
        await db.commit()
        await db.refresh(file_row)
        file_cache.invalidate_file_cache(file_row.id)
        await file_chunks.index_file_chunks_safe(db, file_row, raw=raw_bytes)
        await db.refresh(file_row)

        from app.services import realtime_bus

        await realtime_bus.publish_user_event(
            user.id,
            "library.updated",
            {"action": "updated", "file_id": str(file_row.id), "conversation_id": str(file_row.conversation_id or conv.id)},
        )
        return _text_result(
            {
                "status": "edited",
                "file_id": str(file_row.id),
                "conversation_id": str(file_row.conversation_id or conv.id),
                "filename": file_row.filename,
                "ext": file_row.ext,
                "category": file_row.category,
                "mime_type": file_row.mime_type,
                "size_bytes": file_row.size_bytes,
                "lines_before": lines_before,
                "lines_after": len(updated_text.splitlines()),
            }
        )

    return _text_result(f"未知工具: {name}", is_error=True)
