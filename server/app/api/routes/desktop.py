from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services import desktop_policy, llm_gateway

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


async def desktop_key_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    return await llm_gateway.user_for_key(db, _bearer(request))


@router.get("/policy")
async def policy() -> JSONResponse:
    envelope = desktop_policy.build_envelope()
    return JSONResponse(envelope, headers={"Cache-Control": "no-store"})


@router.get("/policy/public-key")
async def policy_public_key() -> dict:
    pem = desktop_policy.public_key_pem()
    if not pem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "策略密钥未配置")
    return {"public_key": pem}


@router.post("/llm-key", status_code=status.HTTP_201_CREATED)
async def issue_llm_key(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    token = await llm_gateway.issue_key(db, user)
    return {"key": token, "model_alias": llm_gateway.model_alias()}


@router.delete("/llm-key", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_llm_key(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    await llm_gateway.revoke_keys(db, user)


@router.get("/llm/v1/models")
async def list_models(user: User = Depends(desktop_key_user)) -> dict:
    alias = llm_gateway.model_alias()
    return {
        "object": "list",
        "data": [{"id": alias, "object": "model", "owned_by": "whitz"}],
    }


@router.post("/llm/v1/chat/completions")
async def chat_completions(
    body: dict,
    user: User = Depends(desktop_key_user),
    db: AsyncSession = Depends(get_db),
):
    await llm_gateway.preflight(db, user)
    if body.get("stream"):
        stream = llm_gateway.proxy_stream(user, body)
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    data = await llm_gateway.proxy_non_stream(user, body)
    return JSONResponse(data)
