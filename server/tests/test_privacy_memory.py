import json
import uuid

import pytest
import yaml
from sqlalchemy import select

from app.db.models import User
from app.services import bootstrap, memory_service, provisioning
from tests.conftest import auth_header


async def test_profile_context_consent_and_sanitization(register, client, db):
    reg = await register(email="ctx@test.local", display_name="CtxUser")
    headers = auth_header(reg["access_token"])

    # Update full profile including sensitive fields
    upd = await client.patch(
        "/api/users/me",
        json={
            "bio": "分布式系统架构师",
            "gender": "男",
            "birthday": "1995-03-21",
            "phone": "+86 139 1111 2222",
            "location": "杭州",
            "occupation": "技术负责人",
            "preferred_language": "zh-CN",
            "timezone": "Asia/Shanghai",
        },
        headers=headers,
    )
    assert upd.status_code == 200

    user = (await db.execute(select(User).where(User.email == "ctx@test.local"))).scalar_one()
    # Disabled by default
    assert provisioning.build_profile_context(user) is None

    # Enabling without consent=True fails with 400
    bad = await client.patch(
        "/api/users/me/profile-context",
        json={"enabled": True, "consent": False},
        headers=headers,
    )
    assert bad.status_code == 400

    # Enabling with consent=True succeeds and sets consented_at
    ok = await client.patch(
        "/api/users/me/profile-context",
        json={"enabled": True, "consent": True},
        headers=headers,
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["profile_context_enabled"] is True
    assert body["profile_context_consented_at"] is not None

    await db.refresh(user)
    ctx = provisioning.build_profile_context(user)
    assert ctx is not None
    assert "CtxUser" in ctx
    assert "技术负责人" in ctx
    assert "杭州" in ctx
    assert "Asia/Shanghai" in ctx
    assert "分布式系统架构师" in ctx
    # Never inject sensitive PII
    assert "ctx@test.local" not in ctx
    assert "139 1111 2222" not in ctx
    assert "1995-03-21" not in ctx

    # Disabling immediately stops context building
    off = await client.patch(
        "/api/users/me/profile-context",
        json={"enabled": False},
        headers=headers,
    )
    assert off.status_code == 200
    assert off.json()["profile_context_enabled"] is False
    await db.refresh(user)
    assert provisioning.build_profile_context(user) is None


async def test_memory_settings_consent_config_sync_and_reconcile(register, client, db):
    reg = await register(email="memcfg@test.local", display_name="MemCfg")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "memcfg@test.local"))).scalar_one()

    # Initial config has memory disabled
    cfg_path = provisioning.profile_dir(user.hermes_profile) / "config.yaml"
    cfg0 = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert "memory" not in cfg0["platform_toolsets"]["api_server"]
    assert cfg0["memory"]["memory_enabled"] is False
    assert cfg0["memory"]["write_approval"] is True

    # Turning on without consent=True returns 400
    bad = await client.put(
        "/api/users/me/memory/settings",
        json={"enabled": True, "consent": False},
        headers=headers,
    )
    assert bad.status_code == 400

    # Turning on with consent=True syncs config.yaml
    on = await client.put(
        "/api/users/me/memory/settings",
        json={"enabled": True, "require_confirm": True, "consent": True},
        headers=headers,
    )
    assert on.status_code == 200
    data = on.json()
    assert data["memory_enabled"] is True
    assert data["memory_consented_at"] is not None
    assert data["memory_require_confirm"] is True

    cfg1 = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert "memory" in cfg1["platform_toolsets"]["api_server"]
    assert cfg1["memory"]["memory_enabled"] is True
    assert cfg1["memory"]["user_profile_enabled"] is True
    assert cfg1["memory"]["write_approval"] is True
    assert cfg1["memory"]["memory_char_limit"] == 2200
    assert cfg1["memory"]["user_char_limit"] == 1375

    # Preserve skills.disabled during reconcile_profiles
    cfg1["skills"] = {"disabled": ["keep-me-disabled"]}
    cfg_path.write_text(yaml.safe_dump(cfg1, allow_unicode=True, sort_keys=False), encoding="utf-8")

    await db.refresh(user)
    await bootstrap.reconcile_profiles(db)

    cfg2 = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert "memory" in cfg2["platform_toolsets"]["api_server"]
    assert cfg2["memory"]["memory_enabled"] is True
    assert cfg2["skills"]["disabled"] == ["keep-me-disabled"]


async def test_memory_crud_limits_pending_and_isolation(register, client, db):
    u1 = await register(email="mem1@test.local", display_name="Mem1")
    u2 = await register(email="mem2@test.local", display_name="Mem2")
    h1 = auth_header(u1["access_token"])
    h2 = auth_header(u2["access_token"])
    user1 = (await db.execute(select(User).where(User.email == "mem1@test.local"))).scalar_one()

    # Add entries to MEMORY.md and USER.md
    r1 = await client.post(
        "/api/users/me/memory/entries",
        json={"target": "memory", "content": "项目使用 FastAPI + PostgreSQL 17"},
        headers=h1,
    )
    assert r1.status_code == 201
    assert len(r1.json()["entries"]) == 1
    mem_id = r1.json()["entries"][0]["id"]

    r2 = await client.post(
        "/api/users/me/memory/entries",
        json={"target": "user", "content": "偏好简洁中文技术回复"},
        headers=h1,
    )
    assert r2.status_code == 201
    assert len(r2.json()["entries"]) == 2
    assert r2.json()["user_char_count"] > 0

    # Verify delimiter in MEMORY.md
    r3 = await client.post(
        "/api/users/me/memory/entries",
        json={"target": "memory", "content": "Redis 端口为 6379"},
        headers=h1,
    )
    assert r3.status_code == 201
    mem_file = provisioning.profile_dir(user1.hermes_profile) / "memories" / "MEMORY.md"
    assert "\n§\n" in mem_file.read_text(encoding="utf-8")

    # Enforce USER.md 1375 char limit
    oversized = await client.post(
        "/api/users/me/memory/entries",
        json={"target": "user", "content": "A" * 1400},
        headers=h1,
    )
    assert oversized.status_code == 400

    # Update entry
    upd = await client.patch(
        f"/api/users/me/memory/entries/{mem_id}",
        json={"content": "项目采用 FastAPI + SQLAlchemy 2.0 + PostgreSQL 17"},
        headers=h1,
    )
    assert upd.status_code == 200
    assert any("SQLAlchemy 2.0" in e["content"] for e in upd.json()["entries"])

    # Other user cannot access or delete user1's entry
    u2_get = await client.get("/api/users/me/memory", headers=h2)
    assert u2_get.status_code == 200
    assert u2_get.json()["entries"] == []

    # Stage pending memory proposals (add & replace) matching Hermes format
    pend_dir = provisioning.profile_dir(user1.hermes_profile) / "pending" / "memory"
    pend_dir.mkdir(parents=True, exist_ok=True)
    p1_id = "mem_pend_1"
    p2_id = "mem_pend_2"
    (pend_dir / f"{p1_id}.json").write_text(
        json.dumps(
            {
                "id": p1_id,
                "target": "memory",
                "action": "add",
                "content": "部署使用 Docker Compose",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pend_dir / f"{p2_id}.json").write_text(
        json.dumps(
            {
                "id": p2_id,
                "target": "user",
                "action": "add",
                "content": "应被拒绝的噪音偏好",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    overview = await client.get("/api/users/me/memory", headers=h1)
    assert len(overview.json()["pending"]) == 2

    # Approve with inline edit
    app_resp = await client.post(
        f"/api/users/me/memory/pending/{p1_id}",
        json={"action": "approve", "content": "生产环境使用 Docker Compose 部署"},
        headers=h1,
    )
    assert app_resp.status_code == 200
    assert any("Docker Compose 部署" in e["content"] for e in app_resp.json()["entries"])
    assert len(app_resp.json()["pending"]) == 1

    # Reject second pending proposal
    rej_resp = await client.post(
        f"/api/users/me/memory/pending/{p2_id}",
        json={"action": "reject"},
        headers=h1,
    )
    assert rej_resp.status_code == 200
    assert rej_resp.json()["pending"] == []

    # Delete single entry & clear all
    target_id = rej_resp.json()["entries"][0]["id"]
    del_one = await client.delete(f"/api/users/me/memory/entries/{target_id}", headers=h1)
    assert del_one.status_code == 200
    assert all(e["id"] != target_id for e in del_one.json()["entries"])

    cleared = await client.delete("/api/users/me/memory", headers=h1)
    assert cleared.status_code == 200
    assert cleared.json()["entries"] == []
    assert cleared.json()["memory_char_count"] == 0
    assert cleared.json()["user_char_count"] == 0
