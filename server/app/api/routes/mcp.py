import hmac
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db
from app.services import mcp_files, mcp_skills

router = APIRouter(prefix="/api/internal/mcp", tags=["internal-mcp"])

SUPPORTED_PROTOCOL_VERSION = "2025-03-26"


async def _authenticate_namespace(
    db: AsyncSession,
    authorization: str | None,
    namespace_header: str | None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing_bearer_token")
    token = authorization[7:].strip()
    namespace = (namespace_header or "").strip()
    if not token or not namespace:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_mcp_credentials")

    result = await db.execute(select(User).where(User.agent_namespace == namespace))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not hmac.compare_digest(user.agent_api_key, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_mcp_credentials")
    return user


def _rpc_error(req_id, code: int, message: str, http_status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
    )


async def _handle_mcp_post(
    *,
    request: Request,
    authorization: str | None,
    namespace_header: str | None,
    mcp_session_id: str | None,
    db: AsyncSession,
    server_name: str,
    service_mod,
):
    user = await _authenticate_namespace(db, authorization, namespace_header)
    try:
        payload = await request.json()
    except Exception:
        return _rpc_error(None, -32700, "Parse error", http_status=400)

    if not isinstance(payload, dict):
        return _rpc_error(None, -32600, "Invalid Request", http_status=400)

    method = payload.get("method")
    req_id = payload.get("id")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    # Notifications (no id) expect 202 Accepted in Streamable HTTP MCP.
    if req_id is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)

    session_id = mcp_session_id or uuid.uuid4().hex
    headers = {"Mcp-Session-Id": session_id}

    if method == "initialize":
        requested_version = params.get("protocolVersion")
        version = requested_version if isinstance(requested_version, str) and requested_version else SUPPORTED_PROTOCOL_VERSION
        return JSONResponse(
            headers=headers,
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": server_name, "version": "1.0.0"},
                },
            },
        )

    if method == "ping":
        return JSONResponse(headers=headers, content={"jsonrpc": "2.0", "id": req_id, "result": {}})

    if method == "tools/list":
        return JSONResponse(
            headers=headers,
            content={"jsonrpc": "2.0", "id": req_id, "result": {"tools": service_mod.MCP_TOOLS}},
        )

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        result = await service_mod.call_tool(db, user, tool_name, arguments)
        return JSONResponse(
            headers=headers,
            content={"jsonrpc": "2.0", "id": req_id, "result": result},
        )

    return _rpc_error(req_id, -32601, f"Method not found: {method}")


@router.post("/files")
async def mcp_files_post(
    request: Request,
    authorization: str | None = Header(default=None),
    x_whitz_profile: str | None = Header(default=None),
    x_whitz_namespace: str | None = Header(default=None),
    mcp_session_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await _handle_mcp_post(
        request=request,
        authorization=authorization,
        namespace_header=x_whitz_namespace or x_whitz_profile,
        mcp_session_id=mcp_session_id,
        db=db,
        server_name="whitz-files",
        service_mod=mcp_files,
    )


@router.get("/files")
async def mcp_files_get():
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)


@router.delete("/files")
async def mcp_files_delete():
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/skills")
async def mcp_skills_post(
    request: Request,
    authorization: str | None = Header(default=None),
    x_whitz_profile: str | None = Header(default=None),
    x_whitz_namespace: str | None = Header(default=None),
    mcp_session_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await _handle_mcp_post(
        request=request,
        authorization=authorization,
        namespace_header=x_whitz_namespace or x_whitz_profile,
        mcp_session_id=mcp_session_id,
        db=db,
        server_name="whitz-skills",
        service_mod=mcp_skills,
    )


@router.get("/skills")
async def mcp_skills_get():
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)


@router.delete("/skills")
async def mcp_skills_delete():
    return Response(status_code=status.HTTP_204_NO_CONTENT)
