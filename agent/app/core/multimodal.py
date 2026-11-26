from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx
from langchain_core.messages import BaseMessage, HumanMessage

from app.core.config import AgentSettings, get_settings
from app.core.models import _get_shared_api_client

logger = logging.getLogger("whitz.agent.multimodal")

DIRECT_DELIVERY_MODES = frozenset(
    {"native_image_url", "native_image_base64", "native_pdf_file", "inline_full"}
)

_INLINE_FILE_TOKEN_RE = re.compile(
    r"\[\[file:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\|([^\]]+)\]\]"
)


def extract_inline_file_ids(text: str) -> list[str]:
    """Extract ordered, deduplicated file UUIDs from inline ``[[file:uuid|name]]`` tokens."""
    if not text or "[[file:" not in text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _INLINE_FILE_TOKEN_RE.finditer(text):
        fid = match.group(1)
        if fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


@dataclass
class HydratedTurnMedia:
    """Result of hydrating current-turn attached files for native multimodal / full-context delivery."""

    content_blocks: list[dict[str, Any]] = field(default_factory=list)
    block_refs: list[dict[str, Any]] = field(default_factory=list)
    directly_delivered_ids: list[str] = field(default_factory=list)
    delivery_map: dict[str, str] = field(default_factory=dict)
    has_images: bool = False
    has_native_files: bool = False
    file_meta_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)


def _auth_headers(agent_namespace: str, agent_api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {agent_api_key}",
        "X-Whitz-Profile": agent_namespace,
        "X-Whitz-Namespace": agent_namespace,
        "Content-Type": "application/json",
    }


def _format_inline_document_block(item: dict[str, Any]) -> str:
    fid = str(item.get("file_id") or "")
    fname = str(item.get("filename") or "file")
    delivery = str(item.get("delivery") or "inline_full")
    stats = item.get("stats") or {}
    stat_parts = [f"{k}={v}" for k, v in stats.items() if v is not None]
    stat_str = " ".join(stat_parts)
    if delivery == "inline_full":
        body = str(item.get("content") or "")
        extra_note = ""
        if item.get("is_scanned_pdf"):
            extra_note = "\n[注意：该 PDF 可提取文本极少，疑似扫描件/纯图 PDF，请勿凭空补全缺失文字。]"
        return (
            f'<attached_file file_id="{fid}" filename="{fname}" mode="full"'
            + (f" {stat_str}" if stat_str else "")
            + f">{extra_note}\n{body}\n</attached_file>"
        )
    outline = str(item.get("outline") or "").strip()
    return (
        f'<attached_file file_id="{fid}" filename="{fname}" mode="outline"'
        + (f" {stat_str}" if stat_str else "")
        + f">\n{outline}\n[该文件篇幅较大，已附结构大纲；如需精确章节或指定行/页，请调用 read_workspace_file 或 knowledge_search]\n</attached_file>"
    )


async def hydrate_turn_attachments(
    *,
    internal_mcp_base_url: str,
    agent_namespace: str,
    agent_api_key: str,
    conversation_id: str,
    attached_file_ids: Sequence[str],
    prefer_image_mode: str | None = None,
    allow_native_pdf: bool = True,
    settings: AgentSettings | None = None,
) -> HydratedTurnMedia:
    """Fetch native image URLs / native PDF file blocks / inline full texts from server in ONE internal call."""
    out = HydratedTurnMedia()
    base = (internal_mcp_base_url or "").strip().rstrip("/")
    fids = [str(fid).strip() for fid in attached_file_ids if str(fid).strip()]
    if not base or not agent_namespace or not agent_api_key or not fids:
        return out

    s = settings or get_settings()
    eff_image_mode = (prefer_image_mode or s.llm_image_delivery_mode or "url_first").strip().lower()
    eff_pdf = bool(allow_native_pdf and s.llm_native_pdf_mode != "disabled")

    try:
        client = _get_shared_api_client()
        resp = await client.post(
            f"{base}/api/internal/files/prepare-turn",
            headers=_auth_headers(agent_namespace, agent_api_key),
            json={
                "conversation_id": conversation_id,
                "file_ids": fids,
                "prefer_image_mode": eff_image_mode,
                "allow_native_pdf": eff_pdf,
                "inline_token_budget": int(s.attachment_inline_max_tokens),
                "single_file_max_tokens": int(s.attachment_single_file_max_tokens),
            },
            timeout=httpx.Timeout(25.0, connect=6.0),
        )
        if resp.status_code >= 400:
            logger.warning("prepare-turn returned %s: %s", resp.status_code, resp.text[:240])
            return out
        data = resp.json()
    except Exception as exc:
        logger.warning("prepare-turn hydration skipped (%s); falling back to workspace tools", exc)
        return out

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return out

    for item in items:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("file_id") or "").strip()
        fname = str(item.get("filename") or "file").strip()
        delivery = str(item.get("delivery") or "").strip()
        if not fid or not delivery:
            continue

        if delivery == "error":
            err_msg = str(item.get("error") or "无法预处理该附件")
            out.delivery_map[fid] = "error"
            out.content_blocks.append(
                {
                    "type": "text",
                    "text": f"[附件 {fname} (file_id={fid}) 预处理失败：{err_msg}；可尝试调用 read_workspace_file 读取]",
                }
            )
            out.block_refs.append({"file_id": fid, "filename": fname, "category": item.get("category"), "delivery": "error"})
            continue

        expires_at = item.get("expires_at")
        if expires_at is None and delivery == "native_image_url":
            expires_at = time.time() + 1800.0

        meta_entry = {
            "file_id": fid,
            "filename": fname,
            "category": item.get("category"),
            "mime_type": item.get("mime_type"),
            "delivery": delivery,
            "expires_at": expires_at,
        }
        out.delivery_map[fid] = delivery
        out.file_meta_by_id[fid] = meta_entry

        if delivery in ("native_image_url", "native_image_base64"):
            img_url = str(item.get("image_url") or "").strip()
            if img_url:
                out.content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": img_url, "detail": "auto"},
                    }
                )
                out.block_refs.append(dict(meta_entry))
                out.has_images = True
                out.directly_delivered_ids.append(fid)

        elif delivery == "native_pdf_file":
            file_data = str(item.get("file_data") or "").strip()
            if file_data:
                out.content_blocks.append(
                    {
                        "type": "file",
                        "file": {"filename": fname, "file_data": file_data},
                    }
                )
                out.block_refs.append(dict(meta_entry))
                out.has_native_files = True
                out.directly_delivered_ids.append(fid)

        elif delivery == "inline_full":
            out.content_blocks.append({"type": "text", "text": _format_inline_document_block(item)})
            out.block_refs.append(dict(meta_entry))
            out.directly_delivered_ids.append(fid)

        elif delivery == "outline_rag":
            out.content_blocks.append({"type": "text", "text": _format_inline_document_block(item)})
            out.block_refs.append(dict(meta_entry))

    return out


async def fetch_media_fallback(
    *,
    internal_mcp_base_url: str,
    agent_namespace: str,
    agent_api_key: str,
    file_id: str,
    mode: str = "base64",
    max_tokens: int = 8000,
) -> dict[str, Any] | None:
    """Fetch a single file's media/fallback payload (``url`` / ``base64`` / ``text_fallback``)."""
    base = (internal_mcp_base_url or "").strip().rstrip("/")
    if not base or not agent_namespace or not agent_api_key or not file_id:
        return None
    try:
        client = _get_shared_api_client()
        resp = await client.get(
            f"{base}/api/internal/files/{file_id}/media",
            params={"mode": mode, "max_tokens": max_tokens},
            headers=_auth_headers(agent_namespace, agent_api_key),
            timeout=httpx.Timeout(25.0, connect=6.0),
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("media fallback fetch failed for %s (%s): %s", file_id, mode, exc)
        return None


def build_multimodal_user_message(
    input_text: str,
    hydrated: HydratedTurnMedia | None,
) -> HumanMessage:
    """Construct the current turn's HumanMessage cleanly supporting text-only, file-only, and multimodal turns."""
    cleaned = (input_text or "").strip()
    if hydrated is None or not hydrated.content_blocks:
        return HumanMessage(content=cleaned or "请查看我上传的文件并协助分析。")

    if not cleaned:
        if hydrated.has_images and not hydrated.has_native_files:
            cleaned = "请查看并分析我发送的图片。"
        elif hydrated.has_native_files:
            cleaned = "请阅读并分析我发送的文档。"
        else:
            cleaned = "请查看并分析我附带的文件。"

    blocks: list[dict[str, Any]] = [{"type": "text", "text": cleaned}, *hydrated.content_blocks]
    # Explicit block_index -> ref mapping (offset +1 because block 0 is user prompt text)
    block_refs: dict[str, dict[str, Any]] = {}
    for idx, ref in enumerate(hydrated.block_refs):
        block_refs[str(idx + 1)] = dict(ref)
    return HumanMessage(
        content=blocks,
        additional_kwargs={
            "whitz_media_meta": hydrated.file_meta_by_id,
            "whitz_block_refs": block_refs,
            "whitz_direct_file_ids": list(hydrated.directly_delivered_ids),
        },
    )


def build_ephemeral_image_observation(
    *,
    file_id: str,
    filename: str,
    image_url: str,
    mime_type: str = "image/png",
    expires_at: float | None = None,
) -> HumanMessage:
    """Create a synthetic visual observation HumanMessage paired right after a read_workspace_file ToolMessage."""
    is_http = image_url.startswith(("http://", "https://"))
    eff_exp = expires_at if expires_at is not None else (time.time() + 1800.0 if is_http else None)
    meta_entry = {
        "file_id": file_id,
        "filename": filename,
        "category": "image",
        "mime_type": mime_type,
        "delivery": "native_image_url" if is_http else "native_image_base64",
        "expires_at": eff_exp,
    }
    return HumanMessage(
        content=[
            {
                "type": "text",
                "text": f"[工作区图片视觉观察] 以下为刚通过 read_workspace_file 读取的图片「{filename}」(file_id={file_id})，请直接基于画面内容回答用户问题。",
            },
            {
                "type": "image_url",
                "image_url": {"url": image_url, "detail": "auto"},
            },
        ],
        additional_kwargs={
            "whitz_ephemeral_media": True,
            "whitz_media_meta": {file_id: meta_entry},
            "whitz_block_refs": {"1": dict(meta_entry)},
        },
    )


def try_extract_visual_tool_payload(raw_result: Any) -> dict[str, Any] | None:
    """Detect structured visual attachment metadata returned by ``read_workspace_file`` over MCP."""
    text: str | None = None
    if isinstance(raw_result, str):
        text = raw_result
    elif isinstance(raw_result, list):
        for blk in raw_result:
            if isinstance(blk, dict) and blk.get("type") == "text" and isinstance(blk.get("text"), str):
                text = blk["text"]
                break
    elif isinstance(raw_result, dict):
        if raw_result.get("whitz_visual_attachment"):
            return raw_result
        return None

    if not text or "whitz_visual_attachment" not in text:
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, dict) and parsed.get("whitz_visual_attachment"):
        return parsed
    return None


def unwrap_mcp_text_result(raw_result: Any) -> str:
    """Cleanly unwrap MCP content-block lists into text while stripping any accidental raw base64 image blobs."""
    if isinstance(raw_result, str):
        return raw_result
    if isinstance(raw_result, list):
        text_parts: list[str] = []
        for blk in raw_result:
            if isinstance(blk, str):
                text_parts.append(blk)
            elif isinstance(blk, dict):
                btype = str(blk.get("type") or "").lower()
                if btype == "text" and isinstance(blk.get("text"), str):
                    text_parts.append(blk["text"])
                elif btype == "image":
                    text_parts.append("[图片二进制块已由视觉通道处理]")
        if text_parts:
            return "\n".join(text_parts)
    return json.dumps(raw_result, ensure_ascii=False, default=str)


def _resolve_block_ref(
    msg: HumanMessage,
    block_idx: int,
    fallback_list: list[dict[str, Any]],
    fallback_cursor: int,
) -> dict[str, Any]:
    """Resolve exact metadata for ``msg.content[block_idx]`` via ``whitz_block_refs`` with safe legacy fallback."""
    block_refs = (msg.additional_kwargs or {}).get("whitz_block_refs")
    if isinstance(block_refs, dict):
        ref = block_refs.get(str(block_idx))
        if isinstance(ref, dict) and ref.get("file_id"):
            return ref
    if fallback_cursor < len(fallback_list):
        return fallback_list[fallback_cursor]
    return {}


async def refresh_expiring_image_urls(
    messages: Sequence[BaseMessage],
    *,
    internal_mcp_base_url: str,
    agent_namespace: str,
    agent_api_key: str,
    leeway_seconds: float = 180.0,
    force: bool = False,
) -> tuple[list[BaseMessage], bool]:
    """Proactively re-sign remote COS ``image_url`` blocks before expiry (critical after HITL pauses)."""
    now = time.time()
    changed = False
    out: list[BaseMessage] = []
    for msg in messages:
        if not isinstance(msg, HumanMessage) or not isinstance(msg.content, list):
            out.append(msg)
            continue
        kwargs = dict(msg.additional_kwargs or {})
        meta_map = kwargs.get("whitz_media_meta") or {}
        block_refs = dict(kwargs.get("whitz_block_refs") or {}) if isinstance(kwargs.get("whitz_block_refs"), dict) else {}
        image_metas = [
            {"file_id": fid, **info}
            for fid, info in meta_map.items()
            if isinstance(info, dict) and info.get("category") == "image"
        ]
        img_cursor = 0
        new_blocks: list[Any] = []
        msg_changed = False

        for idx, blk in enumerate(msg.content):
            if isinstance(blk, dict) and blk.get("type") == "image_url" and isinstance(blk.get("image_url"), dict):
                url = str(blk["image_url"].get("url") or "")
                ref = _resolve_block_ref(msg, idx, image_metas, img_cursor)
                img_cursor += 1
                if url.startswith(("http://", "https://")):
                    exp = ref.get("expires_at")
                    fid = str(ref.get("file_id") or "")
                    needs_refresh = force or (isinstance(exp, (int, float)) and (float(exp) - now) < leeway_seconds)
                    if fid and needs_refresh:
                        refreshed = await fetch_media_fallback(
                            internal_mcp_base_url=internal_mcp_base_url,
                            agent_namespace=agent_namespace,
                            agent_api_key=agent_api_key,
                            file_id=fid,
                            mode="url",
                        )
                        fresh_url = str((refreshed or {}).get("image_url") or "")
                        if fresh_url.startswith(("http://", "https://")):
                            new_blocks.append({"type": "image_url", "image_url": {"url": fresh_url, "detail": "auto"}})
                            new_exp = refreshed.get("expires_at") or (now + 1800.0)
                            updated_ref = {**ref, "expires_at": new_exp}
                            block_refs[str(idx)] = updated_ref
                            if fid in meta_map and isinstance(meta_map[fid], dict):
                                meta_map = dict(meta_map)
                                meta_map[fid] = {**meta_map[fid], "expires_at": new_exp}
                            msg_changed = True
                            changed = True
                            continue
            new_blocks.append(blk)

        if msg_changed:
            kwargs["whitz_media_meta"] = meta_map
            kwargs["whitz_block_refs"] = block_refs
            out.append(HumanMessage(content=new_blocks, additional_kwargs=kwargs, id=msg.id))
        else:
            out.append(msg)
    return out, changed


async def upgrade_messages_images_to_base64(
    messages: Sequence[BaseMessage],
    *,
    internal_mcp_base_url: str,
    agent_namespace: str,
    agent_api_key: str,
) -> tuple[list[BaseMessage], bool]:
    """Replace remote http(s) ``image_url`` blocks with uncompressed base64 data URIs on URL-fetch failure."""
    changed = False
    out: list[BaseMessage] = []
    for msg in messages:
        if not isinstance(msg, HumanMessage) or not isinstance(msg.content, list):
            out.append(msg)
            continue
        meta_map = (msg.additional_kwargs or {}).get("whitz_media_meta") or {}
        image_metas = [
            {"file_id": fid, **info}
            for fid, info in meta_map.items()
            if isinstance(info, dict) and info.get("category") == "image"
        ]
        # Advance img_cursor across ALL image_url blocks (not just http) so legacy fallback stays aligned too.
        img_cursor = 0
        new_blocks: list[Any] = []
        msg_changed = False
        for idx, blk in enumerate(msg.content):
            if isinstance(blk, dict) and blk.get("type") == "image_url" and isinstance(blk.get("image_url"), dict):
                ref = _resolve_block_ref(msg, idx, image_metas, img_cursor)
                img_cursor += 1
                url = str(blk["image_url"].get("url") or "")
                if url.startswith(("http://", "https://")):
                    fid = str(ref.get("file_id") or "")
                    if fid:
                        fb = await fetch_media_fallback(
                            internal_mcp_base_url=internal_mcp_base_url,
                            agent_namespace=agent_namespace,
                            agent_api_key=agent_api_key,
                            file_id=fid,
                            mode="base64",
                        )
                        b64_url = str((fb or {}).get("image_url") or "")
                        if b64_url.startswith("data:image/"):
                            new_blocks.append({"type": "image_url", "image_url": {"url": b64_url, "detail": "auto"}})
                            msg_changed = True
                            changed = True
                            continue
            new_blocks.append(blk)
        if msg_changed:
            out.append(HumanMessage(content=new_blocks, additional_kwargs=dict(msg.additional_kwargs or {}), id=msg.id))
        else:
            out.append(msg)
    return out, changed


async def downgrade_messages_native_pdf_to_text(
    messages: Sequence[BaseMessage],
    *,
    internal_mcp_base_url: str,
    agent_namespace: str,
    agent_api_key: str,
    max_tokens: int = 8000,
) -> tuple[list[BaseMessage], bool]:
    """Replace OpenAI native ``file`` PDF blocks with structured full-text / outline blocks on provider rejection."""
    changed = False
    out: list[BaseMessage] = []
    for msg in messages:
        if not isinstance(msg, HumanMessage) or not isinstance(msg.content, list):
            out.append(msg)
            continue
        meta_map = (msg.additional_kwargs or {}).get("whitz_media_meta") or {}
        pdf_metas = [
            {"file_id": fid, **info}
            for fid, info in meta_map.items()
            if isinstance(info, dict) and info.get("delivery") == "native_pdf_file"
        ]
        pdf_cursor = 0
        new_blocks: list[Any] = []
        msg_changed = False
        for idx, blk in enumerate(msg.content):
            if isinstance(blk, dict) and blk.get("type") == "file":
                ref = _resolve_block_ref(msg, idx, pdf_metas, pdf_cursor)
                pdf_cursor += 1
                fid = str(ref.get("file_id") or "")
                if fid:
                    fb = await fetch_media_fallback(
                        internal_mcp_base_url=internal_mcp_base_url,
                        agent_namespace=agent_namespace,
                        agent_api_key=agent_api_key,
                        file_id=fid,
                        mode="text_fallback",
                        max_tokens=max_tokens,
                    )
                    if fb and fb.get("delivery") in ("inline_full", "outline_rag"):
                        new_blocks.append({"type": "text", "text": _format_inline_document_block(fb)})
                        msg_changed = True
                        changed = True
                        continue
                fname = str((blk.get("file") or {}).get("filename") or ref.get("filename") or "document.pdf")
                new_blocks.append(
                    {
                        "type": "text",
                        "text": f"[文档 {fname} (file_id={fid}) 无法以原生 PDF 直传，请调用 read_workspace_file 读取]",
                    }
                )
                msg_changed = True
                changed = True
                continue
            new_blocks.append(blk)
        if msg_changed:
            out.append(HumanMessage(content=new_blocks, additional_kwargs=dict(msg.additional_kwargs or {}), id=msg.id))
        else:
            out.append(msg)
    return out, changed


def fold_multimodal_message_for_history(msg: HumanMessage) -> HumanMessage:
    """Fold stale image/PDF/oversized inline document blocks in older turns into compact references."""
    if not isinstance(msg.content, list):
        return msg
    meta_map = (msg.additional_kwargs or {}).get("whitz_media_meta") or {}
    text_parts: list[str] = []
    media_stubs: list[str] = []
    img_idx = 0
    file_idx = 0
    img_metas = [
        {"file_id": fid, **v}
        for fid, v in meta_map.items()
        if isinstance(v, dict) and v.get("category") == "image"
    ]
    # Only native PDFs map to `type == "file"` blocks (never mix inline text docs into pdf fallback!)
    pdf_metas = [
        {"file_id": fid, **v}
        for fid, v in meta_map.items()
        if isinstance(v, dict) and v.get("delivery") == "native_pdf_file"
    ]
    if not pdf_metas:
        pdf_metas = [
            {"file_id": fid, **v}
            for fid, v in meta_map.items()
            if isinstance(v, dict) and v.get("category") != "image"
        ]

    for idx, blk in enumerate(msg.content):
        if isinstance(blk, str):
            text_parts.append(blk)
            continue
        if not isinstance(blk, dict):
            continue
        btype = str(blk.get("type") or "")
        if btype == "text":
            txt = str(blk.get("text") or "")
            if txt.startswith("<attached_file ") and len(txt) > 800:
                first_line = txt.splitlines()[0][:180]
                media_stubs.append(f"[历史已直注文档已折叠: {first_line}… 如需复查请调用 read_workspace_file]")
            else:
                text_parts.append(txt)
        elif btype in ("image_url", "image"):
            m = _resolve_block_ref(msg, idx, img_metas, img_idx)
            img_idx += 1
            fname = m.get("filename") or f"image_{img_idx}"
            fid = m.get("file_id") or ""
            stub = f"[历史图片: {fname}" + (f" (file_id={fid})" if fid else "") + "，如需重新查看细节请调用 read_workspace_file]"
            media_stubs.append(stub)
        elif btype == "file":
            m = _resolve_block_ref(msg, idx, pdf_metas, file_idx)
            file_idx += 1
            fname = (blk.get("file") or {}).get("filename") or m.get("filename") or f"document_{file_idx}.pdf"
            fid = m.get("file_id") or ""
            stub = f"[历史文档: {fname}" + (f" (file_id={fid})" if fid else "") + "，如需重新查阅请调用 read_workspace_file]"
            media_stubs.append(stub)

    combined = "\n".join(p for p in [*text_parts, *media_stubs] if p.strip()).strip()
    return HumanMessage(content=combined or "[历史多模态消息]", id=msg.id)
