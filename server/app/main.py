import logging
import uuid as uuid_module
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import (
    admin,
    admin_membership,
    agent,
    auth,
    chat,
    conversations,
    files,
    library,
    mcp,
    memory,
    skills,
    users,
)
from app.core.config import get_settings
from app.core.redis import close_redis, get_redis
from app.db.session import SessionLocal, engine
from app.services import bootstrap

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whitz")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await get_redis().ping()
    except Exception as exc:
        logger.warning("Redis 暂不可用，依赖 Redis 的接口将失败关闭: %s", exc)
    async with SessionLocal() as db:
        try:
            await bootstrap.ensure_admin(db)
            await bootstrap.reconcile_profiles(db)
        except Exception as exc:
            logger.warning("启动初始化失败（数据库或卷可能尚未就绪）: %s", exc)
    yield
    await close_redis()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Whitz API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    allowed_hosts = [host.strip() for host in settings.allowed_hosts.split(",") if host.strip()]
    if allowed_hosts and allowed_hosts != ["*"]:
        mcp_host = urlsplit(settings.internal_mcp_base_url).hostname
        if mcp_host and mcp_host not in allowed_hosts:
            allowed_hosts.append(mcp_host)
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id")
        if not request_id or len(request_id) > 64:
            request_id = uuid_module.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(admin.router)
    app.include_router(admin_membership.router)
    app.include_router(conversations.router)
    app.include_router(files.router)
    app.include_router(library.router)
    app.include_router(memory.router)
    app.include_router(skills.router)
    app.include_router(mcp.router)
    app.include_router(chat.router)
    app.include_router(agent.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/ready")
    async def ready() -> dict:
        try:
            await get_redis().ping()
        except Exception:
            raise HTTPException(503, "redis_unavailable")
        try:
            async with SessionLocal() as db:
                await db.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "database_unavailable")
        return {"status": "ready"}

    return app


app = create_app()