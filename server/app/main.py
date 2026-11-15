import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, agent, auth, chat, conversations, users
from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.services import bootstrap

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whitz")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as db:
        try:
            await bootstrap.ensure_admin(db)
            await bootstrap.reconcile_profiles(db)
        except Exception as exc:
            logger.warning("启动初始化失败（数据库或卷可能尚未就绪）: %s", exc)
    yield
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
    )

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(admin.router)
    app.include_router(conversations.router)
    app.include_router(chat.router)
    app.include_router(agent.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()