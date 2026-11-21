from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.services import audit, pricing, reactions


def test_audit_hash_chain_and_pii_masking():
    t0 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
    uid = uuid.uuid4()
    h1 = audit.compute_record_hash(
        prev_hash=audit.GENESIS_HASH,
        created_at=t0,
        actor_user_id=uid,
        actor_email="alice@example.com",
        action="admin.user_update",
        target_type="user",
        target_id="u-1",
        outcome="success",
        severity="info",
        risk_score=65,
        metadata={"k": 1},
        diff={"before": {"role": "user"}, "after": {"role": "admin"}},
    )
    h1_same = audit.compute_record_hash(
        prev_hash=audit.GENESIS_HASH,
        created_at=t0,
        actor_user_id=uid,
        actor_email="alice@example.com",
        action="admin.user_update",
        target_type="user",
        target_id="u-1",
        outcome="success",
        severity="info",
        risk_score=65,
        metadata={"k": 1},
        diff={"after": {"role": "admin"}, "before": {"role": "user"}},
    )
    assert len(h1) == 64
    assert h1 == h1_same

    h_tampered = audit.compute_record_hash(
        prev_hash=audit.GENESIS_HASH,
        created_at=t0,
        actor_user_id=uid,
        actor_email="alice@example.com",
        action="admin.user_update",
        target_type="user",
        target_id="u-1",
        outcome="failure",
        severity="info",
        risk_score=65,
        metadata={"k": 1},
        diff={"before": {"role": "user"}, "after": {"role": "admin"}},
    )
    assert h_tampered != h1

    assert audit.compute_risk_score("admin.run_force_stop") >= 70
    assert audit.compute_risk_score("auth.login_failed", outcome="failure", severity="warning") >= 55
    assert audit.compute_risk_score("admin.audit_export", metadata={"mask_pii": False}) >= 70
    assert audit.mask_email("alice.wang@example.com") == "al******@example.com"
    assert audit.mask_ip("192.168.10.25") == "192.168.*.*"


def test_pricing_finops_and_routing_savings():
    fast_cost = pricing.calculate_cost_usd(
        model_name="gpt-4o-mini",
        model_route="fast",
        prompt_tokens=100_000,
        completion_tokens=50_000,
    )
    reasoning_baseline = pricing.calculate_reasoning_baseline_cost_usd(
        prompt_tokens=100_000,
        completion_tokens=50_000,
    )
    assert fast_cost > 0.0
    assert reasoning_baseline > fast_cost

    custom_rates = [
        {
            "model_pattern": "my-custom-model",
            "input_usd_per_1m": 2.0,
            "output_usd_per_1m": 8.0,
            "is_active": True,
        }
    ]
    custom_cost = pricing.calculate_cost_usd(
        model_name="my-custom-model-v2",
        model_route="default",
        prompt_tokens=500_000,
        completion_tokens=250_000,
        custom_rates=custom_rates,
    )
    assert custom_cost == pytest.approx(3.0, abs=1e-6)


def test_reactions_positive_only_enforcement_for_ai():
    for r in ("like", "love", "insightful", "celebrate", "dislike"):
        assert reactions.validate_reaction(author_type="user", reaction=r) == r

    for r in ("like", "love", "sparkle", "insightful"):
        assert reactions.validate_reaction(author_type="assistant", reaction=r) == r

    with pytest.raises(ValueError, match="ai_reaction_must_be_positive"):
        reactions.validate_reaction(author_type="assistant", reaction="dislike")

    with pytest.raises(ValueError, match="unsupported_reaction"):
        reactions.validate_reaction(author_type="user", reaction="angry")
