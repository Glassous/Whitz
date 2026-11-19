from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.config import AgentSettings
from app.core.models import ModelRouter
from app.graph.topology import get_graph_topology

DATASET_PATH = Path(__file__).with_name("dataset.json")


def load_dataset(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


async def run_dry_eval(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    """Offline evaluation validating routing, topology, and schema invariants without live API keys."""
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
    required_nodes = {"context_loader", "agent", "tools", "hitl_gate", "subagent", "memory_extractor"}

    results: list[dict[str, Any]] = []
    cat_stats: dict[str, dict[str, int]] = {}
    passed = 0
    for case in dataset:
        msgs = [HumanMessage(content=case["input"])]
        inferred = router.infer_route(
            case.get("requested_route", "auto"),
            msgs,
            has_images=bool(case.get("has_images")),
        )
        route_ok = inferred == case.get("expected_route")
        topo_ok = required_nodes.issubset(node_ids)
        ok = route_ok and topo_ok
        if ok:
            passed += 1
        cat = str(case.get("category") or "general")
        cs = cat_stats.setdefault(cat, {"total": 0, "passed": 0})
        cs["total"] += 1
        if ok:
            cs["passed"] += 1
        results.append(
            {
                "id": case["id"],
                "category": cat,
                "inferred_route": inferred,
                "expected_route": case.get("expected_route"),
                "passed": ok,
            }
        )

    category_scores = {
        cat: {**st, "pass_rate": round(st["passed"] / max(1, st["total"]), 4)}
        for cat, st in cat_stats.items()
    }
    return {
        "mode": "dry-run",
        "dataset_name": "whitz-agent-golden",
        "total": len(dataset),
        "passed": passed,
        "pass_rate": round(passed / max(1, len(dataset)), 4),
        "category_scores": category_scores,
        "results": results,
    }


async def run_live_eval(dataset: list[dict[str, Any]], dataset_name: str) -> dict[str, Any]:
    """Upload/sync golden dataset to LangSmith and evaluate the live agent graph."""
    settings = AgentSettings()
    settings.configure_langsmith()
    if not settings.langsmith_api_key.strip():
        raise RuntimeError("LANGSMITH_API_KEY is required for live LangSmith evaluation (or pass --dry-run).")

    from langsmith import Client
    from langsmith.evaluation import aevaluate

    from app.graph.builder import build_agent_graph

    client = Client()
    existing = next(iter(client.list_datasets(dataset_name=dataset_name)), None)
    if existing is None:
        ds = client.create_dataset(dataset_name=dataset_name, description="Whitz LangGraph golden eval suite")
        for item in dataset:
            client.create_example(
                inputs={"input": item["input"], "attachments": item.get("attachments", [])},
                outputs={"expected_tools": item.get("expected_tools", []), "expect_interrupt": item.get("expect_interrupt")},
                dataset_id=ds.id,
            )

    graph = build_agent_graph()

    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        res = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=inputs["input"])],
                "attachments": inputs.get("attachments", []),
                "memory_enabled": False,
            },
            config={"configurable": {"thread_id": f"eval-{id(inputs)}", "model_router": ModelRouter(settings)}},
        )
        return {"output": res.get("final_output", ""), "selected_route": res.get("selected_route", "")}

    summary = await aevaluate(target, data=dataset_name, experiment_prefix="whitz-agent")
    return {"mode": "langsmith", "dataset": dataset_name, "experiment": str(summary)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Whitz Agent LangSmith evaluations.")
    parser.add_argument("--dry-run", action="store_true", help="Run offline deterministic evals without API keys.")
    parser.add_argument("--dataset-name", default="whitz-agent-golden", help="LangSmith dataset name.")
    parser.add_argument("--report-url", default="", help="Optional Whitz server eval report URL.")
    parser.add_argument("--token", default="", help="Optional Bearer token for --report-url.")
    args = parser.parse_args(argv)

    dataset = load_dataset()
    if args.dry_run:
        report = asyncio.run(run_dry_eval(dataset))
    else:
        report = asyncio.run(run_live_eval(dataset, args.dataset_name))

    if args.report_url and "total" in report:
        import httpx

        headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
        resp = httpx.post(args.report_url, json=report, headers=headers, timeout=10.0)
        resp.raise_for_status()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.dry_run and report["passed"] != report["total"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
