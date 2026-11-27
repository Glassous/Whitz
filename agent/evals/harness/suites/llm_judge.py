from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.config import AgentSettings
from app.core.models import ModelRouter
from evals.harness.metrics import mean


async def judge_answer_quality(
    *,
    question: str,
    context: str,
    answer: str,
    router: ModelRouter,
) -> dict[str, Any]:
    """Provider-agnostic LLM-as-a-Judge evaluator scoring faithfulness, relevance, and citation quality."""
    llm, _ = await router.get_chat_model("fast", task_hint="eval_judge", temperature=0.0, streaming=False)
    prompt = (
        "You are a strict RAG & Agent evaluation judge. Score the assistant answer from 0.0 to 1.0 on:\n"
        "1. faithfulness: every factual claim is supported by the provided context (no hallucination).\n"
        "2. answer_relevance: directly and completely answers the user question.\n"
        "3. citation_accuracy: citations like [[cite:S1]] match the supporting context snippets (1.0 if none needed).\n"
        'Return ONLY a JSON object: {"faithfulness": 0.0, "answer_relevance": 0.0, "citation_accuracy": 0.0, "reason": "brief explanation"}\n\n'
        f"Question:\n{question}\n\nContext:\n{context}\n\nAssistant Answer:\n{answer}"
    )
    resp = await llm.ainvoke([HumanMessage(content=prompt)])
    raw = resp.content if isinstance(resp.content, str) else ""
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        return {"faithfulness": 0.0, "answer_relevance": 0.0, "citation_accuracy": 0.0, "reason": "invalid_judge_json"}
    parsed = json.loads(raw[s : e + 1])
    return {
        "faithfulness": max(0.0, min(1.0, float(parsed.get("faithfulness", 0.0)))),
        "answer_relevance": max(0.0, min(1.0, float(parsed.get("answer_relevance", 0.0)))),
        "citation_accuracy": max(0.0, min(1.0, float(parsed.get("citation_accuracy", 0.0)))),
        "reason": str(parsed.get("reason") or ""),
    }


async def run_llm_judge_suite(
    samples: list[dict[str, Any]] | None = None,
    *,
    settings: AgentSettings | None = None,
) -> dict[str, Any]:
    """Optional online LLM-as-a-Judge suite (skipped cleanly if no LLM API key is configured)."""
    s = settings or AgentSettings()
    if not s.llm_model.strip() or not s.llm_api_key.strip():
        return {
            "suite": "live_judge",
            "dataset_name": "whitz-llm-judge-v1",
            "total": 0,
            "passed": 0,
            "pass_rate": 1.0,
            "skipped": True,
            "reason": "LLM_API_KEY / LLM_MODEL not configured; skipping live judge suite.",
            "metrics": {},
            "results": [],
        }

    router = ModelRouter(settings=s)
    eval_samples = samples or [
        {
            "id": "judge-01",
            "question": "合同中延期交付的违约金比例和上限是多少？",
            "context": "[S1] 第七条违约责任：若乙方无故延期交付超过 15 个工作日，每逾期一日应按合同总金额的 0.3% 向甲方支付违约金，违约金累计上限不超过合同总金额的 10%。",
            "answer": "根据合同第七条，延期超过 15 个工作日后，每逾期一日按合同总金额的 0.3% 支付违约金，累计上限为合同总金额的 10% [[cite:S1]]。",
        }
    ]

    faith_scores: list[float] = []
    rel_scores: list[float] = []
    cite_scores: list[float] = []
    results: list[dict[str, Any]] = []
    passed = 0

    for item in eval_samples:
        scored = await judge_answer_quality(
            question=str(item["question"]),
            context=str(item["context"]),
            answer=str(item["answer"]),
            router=router,
        )
        faith_scores.append(scored["faithfulness"])
        rel_scores.append(scored["answer_relevance"])
        cite_scores.append(scored["citation_accuracy"])
        ok = scored["faithfulness"] >= 0.8 and scored["answer_relevance"] >= 0.8
        if ok:
            passed += 1
        results.append({"id": item["id"], "category": "live_judge", "passed": ok, **scored})

    return {
        "suite": "live_judge",
        "dataset_name": "whitz-llm-judge-v1",
        "total": len(eval_samples),
        "passed": passed,
        "pass_rate": round(passed / max(1, len(eval_samples)), 4),
        "metrics": {
            "faithfulness": mean(faith_scores),
            "answer_relevance": mean(rel_scores),
            "citation_accuracy": mean(cite_scores),
        },
        "results": results,
    }
