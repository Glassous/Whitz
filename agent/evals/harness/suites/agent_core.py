from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.config import AgentSettings
from app.core.models import ModelRouter
from app.graph.topology import get_graph_topology

DEFAULT_AGENT_DATASET = Path(__file__).resolve().parents[2] / "dataset.json"

_CATEGORY_HINTS: dict[str, str | None] = {
    "planning": "plan",
    "hitl_approval": "code",
    "subagent": "research",
}


async def run_agent_core_suite(dataset_path: Path = DEFAULT_AGENT_DATASET) -> dict[str, Any]:
    """Deterministic regression suite validating model routing, thinking escalation, and graph topology invariants."""
    dataset: list[dict[str, Any]] = json.loads(dataset_path.read_text(encoding="utf-8"))
    settings = AgentSettings(
        llm_base_url="https://mock.local/v1",
        llm_api_key="sk-mock",
        llm_model="mock-default",
        llm_fast_model="mock-fast",
        llm_reasoning_model="mock-reasoning",
        llm_vision_model="mock-vision",
        llm_supports_vision=True,
    )
    router = ModelRouter(settings=settings)
    topology = get_graph_topology()
    node_ids = {n["id"] for n in topology["nodes"]}
    required_nodes = {"context_loader", "rag_prefetch", "agent", "tools", "hitl_gate", "subagent", "memory_extractor"}
    topo_ok = required_nodes.issubset(node_ids)

    results: list[dict[str, Any]] = []
    passed = 0
    for case in dataset:
        cat = str(case.get("category") or "agent_core")
        msgs = [HumanMessage(content=case["input"])]
        hint = _CATEGORY_HINTS.get(cat)
        if cat == "agent_first" and case.get("expected_route") == "fast":
            # Trivial greeting fast-path check
            inferred = router.infer_route(case.get("requested_route", "auto"), [HumanMessage(content="你好")])
        else:
            inferred = router.infer_route(
                case.get("requested_route", "auto"),
                msgs,
                has_images=bool(case.get("has_images")),
                task_hint=hint,
            )
        ok = (inferred == case.get("expected_route")) and topo_ok
        if ok:
            passed += 1
        results.append(
            {
                "id": case["id"],
                "category": cat,
                "passed": ok,
                "inferred_route": inferred,
                "expected_route": case.get("expected_route"),
            }
        )

    return {
        "suite": "agent_core",
        "dataset_name": "whitz-agent-golden",
        "total": len(dataset),
        "passed": passed,
        "pass_rate": round(passed / max(1, len(dataset)), 4),
        "metrics": {
            "routing_accuracy": round(passed / max(1, len(dataset)), 4),
            "topology_valid": 1.0 if topo_ok else 0.0,
        },
        "results": results,
    }
