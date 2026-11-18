import os
import tempfile

# Configure an isolated test environment BEFORE importing the application, whose
# settings/engine are resolved at import time.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://whitz:whitz_dev_password@localhost:5434/whitz_test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-0123456789abcdef"
os.environ["HERMES_DATA_DIR"] = tempfile.mkdtemp(prefix="whitz-test-hermes-")
os.environ["ADMIN_EMAIL"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["LLM_BASE_URL"] = "http://llm.test/v1"
os.environ["LLM_API_KEY"] = "sk-test"
os.environ["LLM_MODEL"] = "test-model"
os.environ["HERMES_API_SERVER_KEY"] = "test-gateway-key"
os.environ["REDIS_URL"] = "memory://"

import asyncpg
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import conversations as conversations_routes
from app.core import ratelimit, redis as redis_mod
from app.db.models import Base
from app.db.session import get_db
from app.main import create_app
from app.services import audit as audit_service
from app.services import email as email_service

PG = {"host": "localhost", "port": 5434, "user": "whitz", "password": "whitz_dev_password"}
TEST_DB = "whitz_test"
_db_ready = False


async def _ensure_database() -> None:
    global _db_ready
    if _db_ready:
        return
    conn = await asyncpg.connect(database="postgres", **PG)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", TEST_DB)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()
    test_conn = await asyncpg.connect(database=TEST_DB, **PG)
    try:
        await test_conn.execute("DROP TABLE IF EXISTS security_questions CASCADE")
    finally:
        await test_conn.close()
    _db_ready = True


class FakeHermesClient:
    """Stands in for the gateway so conversation CRUD needs no live Hermes."""

    def __init__(self, profile: str, api_key: str) -> None:
        self.profile = profile
        self.api_key = api_key

    async def create_session(self, title: str = "新对话") -> dict:
        return {"id": f"sess-{self.profile}"}

    async def patch_session(self, session_id: str, title: str) -> dict:
        return {}

    async def delete_session(self, session_id: str) -> None:
        return None

    async def aclose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    ratelimit.email_code_ip_limiter._hits.clear()
    ratelimit.email_code_addr_limiter._hits.clear()
    ratelimit.reset_password_limiter._hits.clear()
    ratelimit.login_code_limiter._hits.clear()
    ratelimit.redeem_limiter._hits.clear()
    if isinstance(redis_mod._redis, redis_mod.MemoryRedis):
        redis_mod._redis._data.clear()
    yield


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    import re

    outbox: list[dict[str, str]] = []

    async def _fake_send_email(to_email: str, subject: str, text_body: str, html_body: str) -> None:
        match = re.search(r"验证码：(\d{6})", text_body)
        outbox.append(
            {
                "to": to_email,
                "subject": subject,
                "text": text_body,
                "html": html_body,
                "code": match.group(1) if match else "",
            }
        )

    monkeypatch.setattr(email_service, "send_email", _fake_send_email)
    return outbox


@pytest_asyncio.fixture
async def engine():
    await _ensure_database()
    eng = create_async_engine(os.environ["DATABASE_URL"])
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def app(engine, monkeypatch):
    monkeypatch.setattr(conversations_routes, "HermesClient", FakeHermesClient)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(audit_service, "SessionLocal", session_factory)
    application = create_app()

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = _override_get_db
    yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db(engine):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def register(client, sent_emails):
    counter = 0

    async def _register(
        email: str = "user@test.local",
        password: str = "Passw0rd!",
        display_name: str | None = None,
    ) -> dict:
        nonlocal counter
        if display_name is None:
            counter += 1
            local = email.split("@", 1)[0]
            display_name = f"{local}-{counter}"
        code_resp = await client.post(
            "/api/auth/email-code",
            json={"email": email, "purpose": "register"},
        )
        assert code_resp.status_code == 200, code_resp.text
        code = sent_emails[-1]["code"]
        resp = await client.post(
            "/api/auth/register",
            json={
                "email": email,
                "code": code,
                "password": password,
                "display_name": display_name,
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _register


@pytest_asyncio.fixture
async def admin(register, db):
    import uuid

    from app.db.models import User

    data = await register(email="admin@test.local", display_name="Admin")
    user = await db.get(User, uuid.UUID(data["user"]["id"]))
    user.role = "admin"
    await db.commit()
    return data