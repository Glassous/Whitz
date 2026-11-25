from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    PostCommentCreateRequest,
    PostCommentCreateResponse,
    PostCreateRequest,
    PostDiscussOut,
    PostListOut,
    PostOut,
    PostQuotaSummaryOut,
)
from app.db.models import User
from app.db.session import get_db
from app.services import audit, posts_service

router = APIRouter(prefix="/api/posts", tags=["posts"])


def _raise(exc: posts_service.PostServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("", response_model=PostListOut)
async def list_my_posts(
    author_type: str | None = Query(default=None, pattern="^(ai|user)$"),
    bookmarked_only: bool = Query(default=False),
    collection_id: uuid.UUID | None = Query(default=None),
    post_kind: str | None = Query(default=None),
    cursor: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await posts_service.list_posts(
        db,
        user,
        author_type=author_type,
        bookmarked_only=bookmarked_only,
        collection_id=collection_id,
        post_kind=post_kind,
        cursor=cursor,
        limit=limit,
    )


@router.get("/quota", response_model=PostQuotaSummaryOut)
async def get_my_post_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await posts_service.get_user_post_quota_summary(db, user)


@router.post("", response_model=PostOut, status_code=status.HTTP_201_CREATED)
async def create_my_post(
    body: PostCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        created = await posts_service.create_user_post(
            db,
            user,
            content=body.content,
            title=body.title,
            tags=body.tags,
        )
    except posts_service.PostServiceError as exc:
        _raise(exc)
    await audit.record(
        "post.create",
        actor=user,
        target_type="post",
        target_id=created["id"],
        request=request,
        metadata={"author_type": "user", "memory_synced": bool(created.get("memory_entry_id"))},
    )
    return created


@router.get("/{post_id}", response_model=PostOut)
async def get_my_post(
    post_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await posts_service.get_post_detail(db, user, post_id)
    except posts_service.PostServiceError as exc:
        _raise(exc)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_post(
    post_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await posts_service.delete_post(db, user, post_id)
    except posts_service.PostServiceError as exc:
        _raise(exc)
    await audit.record(
        "post.delete",
        actor=user,
        target_type="post",
        target_id=post_id,
        request=request,
    )


@router.post("/{post_id}/like", response_model=PostOut)
async def toggle_post_like(
    post_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await posts_service.toggle_like(db, user, post_id)
    except posts_service.PostServiceError as exc:
        _raise(exc)


@router.post("/{post_id}/bookmark", response_model=PostOut)
async def toggle_post_bookmark(
    post_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await posts_service.toggle_bookmark(db, user, post_id)
    except posts_service.PostServiceError as exc:
        _raise(exc)


@router.post("/{post_id}/comments", response_model=PostCommentCreateResponse, status_code=status.HTTP_201_CREATED)
async def add_post_comment(
    post_id: uuid.UUID,
    body: PostCommentCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await posts_service.create_comment(
            db,
            user,
            post_id,
            content=body.content,
            reply_to_id=body.reply_to_id,
            trigger_ai_reply=body.trigger_ai_reply,
        )
    except posts_service.PostServiceError as exc:
        _raise(exc)


@router.delete("/{post_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_post_comment(
    post_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await posts_service.delete_comment(db, user, post_id, comment_id)
    except posts_service.PostServiceError as exc:
        _raise(exc)


@router.post("/{post_id}/discuss", response_model=PostDiscussOut)
async def discuss_post_in_chat(
    post_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await posts_service.start_discussion_from_post(db, user, post_id)
    except posts_service.PostServiceError as exc:
        _raise(exc)
