from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy import func, or_, select, update

from app.core.redis import MemoryRedis, get_redis
from app.db.models import (
    Conversation,
    ConversationDigest,
    ConversationEpisode,
    ConversationFile,
    FileChunk,
    MemoryCollection,
    MemoryEntry,
    MessageChunk,
)
from app.db.session import SessionLocal, detect_pgvector
from app.services import embeddings, realtime_bus

logger = logging.getLogger("whitz.rag_jobs")

RAG_JOB_QUEUE_KEY = "whitz:rag:jobs"
RAG_JOB_PROCESSING_KEY = "whitz:rag:jobs:processing"
RAG_JOB_RETRY_ZSET_KEY = "whitz:rag:jobs:retry"
RAG_JOB_DLQ_KEY = "whitz:rag:jobs:dlq"
MAX_JOB_ATTEMPTS = 3
MAX_CONCURRENT_JOBS = 4

_WORKER_TASK: asyncio.Task[Any] | None = None
_RETRY_PUMP_TASK: asyncio.Task[Any] | None = None
_LOCAL_TASKS: set[asyncio.Task[Any]] = set()
_JOB_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _JOB_SEMAPHORE
    if _JOB_SEMAPHORE is None:
        _JOB_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    return _JOB_SEMAPHORE


async def enqueue_job(job_type: str, payload: dict[str, Any]) -> bool:
    """Push a durable RAG indexing job into Redis list (falls back to local task under MemoryRedis)."""
    r = get_redis()
    job = {
        "id": uuid.uuid4().hex,
        "type": job_type,
        "payload": payload,
        "attempt": 0,
    }
    if isinstance(r, MemoryRedis):
        _schedule_local_execution(job)
        return True
    try:
        await r.rpush(RAG_JOB_QUEUE_KEY, json.dumps(job, ensure_ascii=False, default=str))
        return True
    except Exception as exc:
        logger.debug("Redis RAG queue unavailable (%s); running inline background task", exc)
        _schedule_local_execution(job)
        return True


def enqueue_file_index_nowait(file_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Fire-and-forget helper usable from synchronous schedule_* hooks."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    task = loop.create_task(
        enqueue_job("index_file", {"file_id": str(file_id), "user_id": str(user_id)})
    )
    _LOCAL_TASKS.add(task)
    task.add_done_callback(_LOCAL_TASKS.discard)
    return True


def _schedule_local_execution(job: dict[str, Any]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_execute_job(job))
    _LOCAL_TASKS.add(task)
    task.add_done_callback(_LOCAL_TASKS.discard)


async def _handle_index_file(payload: dict[str, Any]) -> None:
    from app.services import file_chunks

    file_uuid = uuid.UUID(str(payload["file_id"]))
    user_uuid = uuid.UUID(str(payload["user_id"]))
    async with SessionLocal() as db:
        rec = await db.get(ConversationFile, file_uuid)
        if rec is None or rec.status != "ready":
            return
        # Call index_file_chunks directly so transient errors propagate to rag_jobs retry/DLQ!
        try:
            await file_chunks.index_file_chunks(db, rec)
        except Exception as exc:
            try:
                await db.rollback()
                rec_reload = await db.get(ConversationFile, file_uuid)
                if rec_reload is not None:
                    rec_reload.index_status = "failed"
                    rec_reload.index_error = str(exc)[:500]
                    await db.commit()
            except Exception:
                pass
            raise
        await realtime_bus.publish_user_event(
            user_uuid,
            "library.updated",
            {
                "action": "indexed",
                "file_id": str(file_uuid),
                "index_status": rec.index_status,
                "indexed_chunks": rec.indexed_chunks,
            },
        )


async def _handle_index_turn_chunk(payload: dict[str, Any]) -> None:
    from app.services import cross_chat_memory

    async with SessionLocal() as db:
        await cross_chat_memory.index_turn_chunk(
            db,
            user_id=uuid.UUID(str(payload["user_id"])),
            conversation_id=uuid.UUID(str(payload["conversation_id"])),
            conversation_kind=str(payload.get("conversation_kind") or "side"),
            conversation_title=str(payload.get("conversation_title") or ""),
            user_msg_id=uuid.UUID(str(payload["user_msg_id"])) if payload.get("user_msg_id") else None,
            assistant_msg_id=uuid.UUID(str(payload["assistant_msg_id"])) if payload.get("assistant_msg_id") else None,
            user_content=str(payload.get("user_content") or ""),
            assistant_content=str(payload.get("assistant_content") or ""),
        )


async def _handle_refresh_side_digest(payload: dict[str, Any]) -> None:
    from app.services import cross_chat_memory

    conv_uuid = uuid.UUID(str(payload["conversation_id"]))
    user_uuid = uuid.UUID(str(payload["user_id"]))
    force = bool(payload.get("force", False))
    async with SessionLocal() as db:
        await cross_chat_memory.refresh_side_chat_digest(db, conv_uuid, user_uuid, force=force, use_llm=True)


async def _handle_archive_episode(payload: dict[str, Any]) -> None:
    from app.services import cross_chat_memory

    conv_uuid = uuid.UUID(str(payload["conversation_id"]))
    force = bool(payload.get("force", False))
    r = get_redis()
    lock_key = f"episode:lock:{conv_uuid}"
    acquired = True
    try:
        acquired = bool(await r.set(lock_key, "1", ex=90, nx=True))
    except Exception:
        acquired = True
    if not acquired:
        return
    try:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, conv_uuid)
            if conv is not None:
                archived = await cross_chat_memory.archive_conversation_episode_if_needed(db, conv, force=force)
                if archived is not None:
                    await realtime_bus.publish_user_event(
                        conv.user_id,
                        "context_state.updated",
                        {"conversation_id": str(conv.id), "episode_index": getattr(archived, "episode_index", None)},
                    )
    finally:
        try:
            await r.delete(lock_key)
        except Exception:
            pass


def normalize_backfill_scope(scope: str) -> set[str]:
    """Normalize both short aliases and exact table names into target table keys."""
    s = (scope or "all").strip().lower()
    if s == "all":
        return {"file_chunks", "memory_entries", "conversation_digests", "conversation_episodes", "message_chunks"}
    if s in ("files", "file_chunks"):
        return {"file_chunks"}
    if s in ("memories", "memory_entries"):
        return {"memory_entries"}
    if s == "chats":
        return {"conversation_digests", "conversation_episodes", "message_chunks"}
    if s in ("conversation_digests", "digests"):
        return {"conversation_digests"}
    if s in ("conversation_episodes", "episodes"):
        return {"conversation_episodes"}
    if s in ("message_chunks", "messages"):
        return {"message_chunks"}
    return set()


async def run_embeddings_backfill(*, scope: str = "all", batch_size: int = 50) -> dict[str, int]:
    """Backfill missing or stale-model embeddings across file_chunks, memory_entries, digests, episodes, and message_chunks."""
    stats = {
        "file_chunks": 0,
        "memory_entries": 0,
        "conversation_digests": 0,
        "conversation_episodes": 0,
        "message_chunks": 0,
    }
    if not embeddings.is_embedding_configured():
        return stats

    targets = normalize_backfill_scope(scope)
    if not targets:
        return stats

    model_tag = embeddings.current_embedding_model_tag()
    lim = max(1, min(int(batch_size or 50), 200))

    async with SessionLocal() as db:
        await detect_pgvector(db)

        if "file_chunks" in targets:
            rows = list(
                (
                    await db.execute(
                        select(FileChunk)
                        .where(
                            or_(
                                FileChunk.embedding.is_(None),
                                FileChunk.embedding_model.is_(None),
                                FileChunk.embedding_model != model_tag,
                            )
                        )
                        .limit(lim)
                    )
                )
                .scalars()
                .all()
            )
            if rows:
                texts = [f"{r.context_header}\n{r.content}".strip() for r in rows]
                vecs = await embeddings.embed_texts(texts)
                if vecs:
                    for row, vec in zip(rows, vecs):
                        row.embedding = vec
                        row.embedding_model = model_tag
                    await db.commit()
                    stats["file_chunks"] = len(rows)

        if "memory_entries" in targets:
            rows = list(
                (
                    await db.execute(
                        select(MemoryEntry)
                        .where(
                            or_(
                                MemoryEntry.embedding.is_(None),
                                MemoryEntry.embedding_model.is_(None),
                                MemoryEntry.embedding_model != model_tag,
                            )
                        )
                        .limit(lim)
                    )
                )
                .scalars()
                .all()
            )
            if rows:
                col_ids = {r.collection_id for r in rows if r.collection_id}
                col_map: dict[uuid.UUID, str] = {}
                if col_ids:
                    c_rows = (
                        await db.execute(select(MemoryCollection.id, MemoryCollection.name).where(MemoryCollection.id.in_(col_ids)))
                    ).all()
                    col_map = {cid: cname for cid, cname in c_rows}
                texts = [
                    f"[{col_map.get(r.collection_id, r.target)}] {r.title} {' '.join(f'#{t}' for t in (r.tags or []))}\n{r.content}".strip()
                    for r in rows
                ]
                vecs = await embeddings.embed_texts(texts)
                if vecs:
                    for row, vec in zip(rows, vecs):
                        row.embedding = vec
                        row.embedding_model = model_tag
                        row.search_tsv = func.to_tsvector(
                            "simple", " ".join(p for p in (row.title, " ".join(row.tags or []), row.content) if p)
                        )
                    await db.commit()
                    stats["memory_entries"] = len(rows)

        if "conversation_digests" in targets:
            digests = list(
                (
                    await db.execute(
                        select(ConversationDigest)
                        .where(
                            or_(
                                ConversationDigest.embedding.is_(None),
                                ConversationDigest.embedding_model.is_(None),
                                ConversationDigest.embedding_model != model_tag,
                            )
                        )
                        .limit(lim)
                    )
                )
                .scalars()
                .all()
            )
            if digests:
                texts = [
                    " ".join([d.title or "", d.summary or "", " ".join(d.key_facts or []), " ".join(d.keywords or [])]).strip()[:2000]
                    for d in digests
                ]
                vecs = await embeddings.embed_texts(texts)
                if vecs:
                    for row, vec in zip(digests, vecs):
                        row.embedding = vec
                        row.embedding_model = model_tag
                    await db.commit()
                    stats["conversation_digests"] = len(digests)

        if "message_chunks" in targets:
            mchunks = list(
                (
                    await db.execute(
                        select(MessageChunk)
                        .where(
                            or_(
                                MessageChunk.embedding.is_(None),
                                MessageChunk.embedding_model.is_(None),
                                MessageChunk.embedding_model != model_tag,
                            )
                        )
                        .limit(lim)
                    )
                )
                .scalars()
                .all()
            )
            if mchunks:
                texts = [f"{m.context_header}\n{m.content}".strip()[:1800] for m in mchunks]
                vecs = await embeddings.embed_texts(texts)
                if vecs:
                    for row, vec in zip(mchunks, vecs):
                        row.embedding = vec
                        row.embedding_model = model_tag
                    await db.commit()
                    stats["message_chunks"] = len(mchunks)

        if "conversation_episodes" in targets:
            episodes = list(
                (
                    await db.execute(
                        select(ConversationEpisode)
                        .where(
                            or_(
                                ConversationEpisode.embedding.is_(None),
                                ConversationEpisode.embedding_model.is_(None),
                                ConversationEpisode.embedding_model != model_tag,
                            )
                        )
                        .limit(lim)
                    )
                )
                .scalars()
                .all()
            )
            if episodes:
                texts = [
                    " ".join([e.topic or "", e.summary or "", " ".join(e.key_facts or []), " ".join(e.entities or [])]).strip()[:2000]
                    for e in episodes
                ]
                vecs = await embeddings.embed_texts(texts)
                if vecs:
                    for row, vec in zip(episodes, vecs):
                        row.embedding = vec
                        row.embedding_model = model_tag
                    await db.commit()
                    stats["conversation_episodes"] = len(episodes)

    return stats


async def _execute_job(job: dict[str, Any], raw_item: str | None = None) -> None:
    jtype = str(job.get("type") or "")
    payload = job.get("payload") or {}
    attempt = int(job.get("attempt") or 0)
    r = get_redis()
    try:
        if jtype == "index_file":
            await _handle_index_file(payload)
        elif jtype == "index_turn_chunk":
            await _handle_index_turn_chunk(payload)
        elif jtype == "refresh_side_digest":
            await _handle_refresh_side_digest(payload)
        elif jtype == "archive_episode":
            await _handle_archive_episode(payload)
        elif jtype == "backfill_embeddings":
            await run_embeddings_backfill(
                scope=str(payload.get("scope") or "all"),
                batch_size=int(payload.get("batch_size") or 50),
            )
    except Exception as exc:
        logger.warning("RAG job %s failed (attempt %d): %s", jtype, attempt + 1, exc)
        if not isinstance(r, MemoryRedis):
            if attempt + 1 < MAX_JOB_ATTEMPTS:
                job["attempt"] = attempt + 1
                delay = min(5.0 * (2 ** attempt), 30.0)
                run_at = time.time() + delay
                serialized = json.dumps(job, ensure_ascii=False, default=str)
                try:
                    if hasattr(r, "zadd"):
                        await r.zadd(RAG_JOB_RETRY_ZSET_KEY, {serialized: run_at})
                    else:
                        await r.rpush(RAG_JOB_QUEUE_KEY, serialized)
                except Exception:
                    pass
            else:
                try:
                    job["last_error"] = str(exc)[:300]
                    job["failed_at"] = time.time()
                    await r.lpush(RAG_JOB_DLQ_KEY, json.dumps(job, ensure_ascii=False, default=str))
                    await r.ltrim(RAG_JOB_DLQ_KEY, 0, 199)
                except Exception:
                    pass
    finally:
        if raw_item is not None and not isinstance(r, MemoryRedis):
            try:
                await r.lrem(RAG_JOB_PROCESSING_KEY, 1, raw_item)
            except Exception:
                pass


async def _recover_inflight_and_stuck_files() -> None:
    """Re-queue any jobs left in processing list after a crash and re-enqueue stuck 'indexing' files."""
    r = get_redis()
    if not isinstance(r, MemoryRedis):
        try:
            if hasattr(r, "lmove"):
                for _ in range(200):
                    moved = await r.lmove(RAG_JOB_PROCESSING_KEY, RAG_JOB_QUEUE_KEY, "RIGHT", "LEFT")
                    if not moved:
                        break
        except Exception as exc:
            logger.debug("RAG processing recovery skipped: %s", exc)
    try:
        async with SessionLocal() as db:
            stuck = (
                await db.execute(
                    select(ConversationFile.id, ConversationFile.user_id)
                    .where(
                        ConversationFile.status == "ready",
                        ConversationFile.index_status == "indexing",
                    )
                    .limit(100)
                )
            ).all()
            for fid, uid in stuck:
                await enqueue_job("index_file", {"file_id": str(fid), "user_id": str(uid)})
    except Exception as exc:
        logger.debug("RAG stuck file sweep skipped: %s", exc)


async def _retry_pump_loop() -> None:
    """Move due delayed retry jobs from ZSET back into the main queue."""
    while True:
        try:
            await asyncio.sleep(2.0)
            r = get_redis()
            if isinstance(r, MemoryRedis) or not hasattr(r, "zrangebyscore"):
                continue
            now_ts = time.time()
            due = await r.zrangebyscore(RAG_JOB_RETRY_ZSET_KEY, "-inf", now_ts, start=0, num=20)
            for item in due or []:
                removed = await r.zrem(RAG_JOB_RETRY_ZSET_KEY, item)
                if removed:
                    await r.rpush(RAG_JOB_QUEUE_KEY, item)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug("RAG retry pump tick error: %s", exc)
            await asyncio.sleep(3.0)


async def _run_job_with_sem(job: dict[str, Any], raw_item: str) -> None:
    sem = _get_semaphore()
    try:
        await _execute_job(job, raw_item=raw_item)
    finally:
        sem.release()


async def _worker_loop() -> None:
    await _recover_inflight_and_stuck_files()
    while True:
        try:
            r = get_redis()
            if isinstance(r, MemoryRedis):
                await asyncio.sleep(5.0)
                continue
            sem = _get_semaphore()
            await sem.acquire()
            raw: str | None = None
            try:
                if hasattr(r, "blmove"):
                    raw = await r.blmove(RAG_JOB_QUEUE_KEY, RAG_JOB_PROCESSING_KEY, 3, "LEFT", "RIGHT")
                else:
                    item = await r.blpop([RAG_JOB_QUEUE_KEY], timeout=3)
                    raw = item[1] if item else None
            except Exception:
                sem.release()
                raise
            if not raw:
                sem.release()
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "ignore")
            try:
                job = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                sem.release()
                try:
                    await r.lrem(RAG_JOB_PROCESSING_KEY, 1, raw)
                except Exception:
                    pass
                continue
            if not isinstance(job, dict):
                sem.release()
                continue
            task = asyncio.create_task(_run_job_with_sem(job, raw), name=f"rag-job-{job.get('type', 'unknown')}")
            _LOCAL_TASKS.add(task)
            task.add_done_callback(_LOCAL_TASKS.discard)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug("RAG job worker tick error: %s", exc)
            await asyncio.sleep(2.0)


def start_rag_job_worker() -> None:
    global _WORKER_TASK, _RETRY_PUMP_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(_worker_loop(), name="rag-job-worker")
    if _RETRY_PUMP_TASK is None or _RETRY_PUMP_TASK.done():
        _RETRY_PUMP_TASK = asyncio.create_task(_retry_pump_loop(), name="rag-retry-pump")


async def stop_rag_job_worker() -> None:
    global _WORKER_TASK, _RETRY_PUMP_TASK
    for task_ref in (_WORKER_TASK, _RETRY_PUMP_TASK):
        if task_ref is not None:
            task_ref.cancel()
            try:
                await task_ref
            except (asyncio.CancelledError, Exception):
                pass
    _WORKER_TASK = None
    _RETRY_PUMP_TASK = None
    if _LOCAL_TASKS:
        pending = list(_LOCAL_TASKS)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        _LOCAL_TASKS.clear()


async def get_queue_depth() -> dict[str, int]:
    try:
        r = get_redis()
        if isinstance(r, MemoryRedis):
            return {"pending": 0, "processing": 0, "retrying": 0, "dlq": 0}
        q_len = int(await r.llen(RAG_JOB_QUEUE_KEY) or 0)
        proc_len = int(await r.llen(RAG_JOB_PROCESSING_KEY) or 0)
        retry_len = int(await r.zcard(RAG_JOB_RETRY_ZSET_KEY) or 0) if hasattr(r, "zcard") else 0
        dlq_len = int(await r.llen(RAG_JOB_DLQ_KEY) or 0)
        return {"pending": q_len, "processing": proc_len, "retrying": retry_len, "dlq": dlq_len}
    except Exception:
        return {"pending": 0, "processing": 0, "retrying": 0, "dlq": 0}


async def list_dlq(*, limit: int = 50) -> list[dict[str, Any]]:
    try:
        r = get_redis()
        if isinstance(r, MemoryRedis) or not hasattr(r, "lrange"):
            return []
        raw_items = await r.lrange(RAG_JOB_DLQ_KEY, 0, max(0, limit - 1))
        out: list[dict[str, Any]] = []
        for raw in raw_items or []:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "ignore")
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    out.append(parsed)
            except (json.JSONDecodeError, ValueError):
                out.append({"raw": str(raw)[:300]})
        return out
    except Exception:
        return []


async def replay_dlq(*, limit: int = 50) -> int:
    try:
        r = get_redis()
        if isinstance(r, MemoryRedis) or not hasattr(r, "rpop"):
            return 0
        replayed = 0
        for _ in range(max(1, min(limit, 200))):
            raw = await r.rpop(RAG_JOB_DLQ_KEY)
            if not raw:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "ignore")
            try:
                job = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(job, dict):
                job["attempt"] = 0
                job.pop("last_error", None)
                await r.rpush(RAG_JOB_QUEUE_KEY, json.dumps(job, ensure_ascii=False, default=str))
                replayed += 1
        return replayed
    except Exception:
        return 0


async def purge_dlq() -> int:
    try:
        r = get_redis()
        if isinstance(r, MemoryRedis):
            return 0
        count = int(await r.llen(RAG_JOB_DLQ_KEY) or 0)
        await r.delete(RAG_JOB_DLQ_KEY)
        return count
    except Exception:
        return 0
