from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.harness.suites import (
    run_agent_core_suite,
    run_cache_bench_suite,
    run_guardrails_bench_suite,
    run_llm_judge_suite,
    run_rag_bench_suite,
)

# Metrics where LOWER is better (regressions happen when value INCREASES)
_LOWER_IS_BETTER = frozenset({"benign_fpr", "false_hit_rate", "p95_latency_ms"})

# Key quality metrics checked by regression gate (excludes timing noise like p95_latency_ms)
_GATED_METRICS: dict[str, tuple[str, ...]] = {
    "rag": ("recall_at_3", "recall_at_5", "mrr_at_5", "ndcg_at_5"),
    "guardrails": ("attack_tpr", "benign_fpr", "tool_safety_accuracy", "pii_f1"),
    "cache": ("positive_hit_rate", "false_hit_rate", "tenant_isolation_rate", "bypass_accuracy", "invalidation_ok"),
    "agent_core": ("routing_accuracy", "topology_valid"),
}


def _detect_git_sha() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True)
        return out.strip() or None
    except Exception:
        return None


@dataclass
class HarnessReport:
    mode: str
    dataset_name: str
    total: int
    passed: int
    pass_rate: float
    suites: dict[str, dict[str, Any]]
    regressions: list[dict[str, Any]] = field(default_factory=list)
    git_sha: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_admin_quant_payload(self) -> dict[str, Any]:
        """Serialize in exact format accepted by `POST /api/admin/quant/evals/report` (EvalReportIn)."""
        category_scores: dict[str, Any] = {}
        flat_results: list[dict[str, Any]] = []
        for sname, sdata in self.suites.items():
            category_scores[sname] = {
                "total": sdata.get("total", 0),
                "passed": sdata.get("passed", 0),
                "pass_rate": sdata.get("pass_rate", 0.0),
                "metrics": sdata.get("metrics") or {},
            }
            if "ablations" in sdata:
                category_scores[sname]["ablations"] = sdata["ablations"]
            flat_results.extend(sdata.get("results") or [])
        return {
            "mode": self.mode,
            "dataset_name": self.dataset_name,
            "total": self.total,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "category_scores": category_scores,
            "results": flat_results,
            "git_sha": self.git_sha,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_admin_quant_payload()
        payload["suites"] = self.suites
        payload["regressions"] = self.regressions
        payload["created_at"] = self.created_at
        return payload

    def to_markdown(self) -> str:
        lines: list[str] = [
            f"# Whitz Eval Harness Report",
            "",
            f"- **Mode**: `{self.mode}` | **Git SHA**: `{self.git_sha or 'unknown'}` | **Generated**: `{self.created_at}`",
            f"- **Overall Pass Rate**: **{self.passed}/{self.total} ({self.pass_rate * 100:.2f}%)**",
            f"- **Regression Gate**: {'FAILED (' + str(len(self.regressions)) + ' regressions)' if self.regressions else 'PASSED'}",
            "",
            "## Suite Summary",
            "",
            "| Suite | Passed / Total | Pass Rate | Key Metrics |",
            "| --- | --- | --- | --- |",
        ]
        for sname, sdata in self.suites.items():
            metrics = sdata.get("metrics") or {}
            m_str = ", ".join(f"`{k}={v}`" for k, v in metrics.items())
            lines.append(
                f"| `{sname}` | {sdata.get('passed', 0)}/{sdata.get('total', 0)} | "
                f"{float(sdata.get('pass_rate', 0.0)) * 100:.2f}% | {m_str} |"
            )

        rag = self.suites.get("rag")
        if rag and isinstance(rag.get("ablations"), dict):
            lines.extend(
                [
                    "",
                    "## RAG Retrieval Ablation Study",
                    "",
                    "| Strategy | Recall@3 | Recall@5 | MRR@5 | NDCG@5 | P95 Latency (ms) |",
                    "| --- | --- | --- | --- | --- | --- |",
                ]
            )
            for strat, vals in rag["ablations"].items():
                lines.append(
                    f"| `{strat}` | {vals['recall_at_3']:.4f} | {vals['recall_at_5']:.4f} | "
                    f"{vals['mrr_at_5']:.4f} | {vals['ndcg_at_5']:.4f} | {vals['p95_latency_ms']:.3f} |"
                )

        if self.regressions:
            lines.extend(
                [
                    "",
                    "## Regressions Detected",
                    "",
                    "| Suite | Metric | Baseline | Current | Delta |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for reg in self.regressions:
                lines.append(
                    f"| `{reg['suite']}` | `{reg['metric']}` | {reg['baseline']:.4f} | "
                    f"{reg['current']:.4f} | {reg['delta']:+.4f} |"
                )
        lines.append("")
        return "\n".join(lines)


def check_regressions(
    current_suites: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    *,
    max_drop: float = 0.02,
) -> list[dict[str, Any]]:
    base_suites = baseline.get("suites") or baseline.get("category_scores") or {}
    regressions: list[dict[str, Any]] = []
    for sname, gated_keys in _GATED_METRICS.items():
        if sname not in current_suites or sname not in base_suites:
            continue
        cur_m = current_suites[sname].get("metrics") or {}
        base_m = base_suites[sname].get("metrics") or {}
        for key in gated_keys:
            if key not in cur_m or key not in base_m:
                continue
            cur_v = float(cur_m[key])
            base_v = float(base_m[key])
            delta = round(cur_v - base_v, 4)
            if key in _LOWER_IS_BETTER:
                if cur_v > base_v + max_drop:
                    regressions.append(
                        {"suite": sname, "metric": key, "baseline": base_v, "current": cur_v, "delta": delta}
                    )
            else:
                if cur_v < base_v - max_drop:
                    regressions.append(
                        {"suite": sname, "metric": key, "baseline": base_v, "current": cur_v, "delta": delta}
                    )
    return regressions


async def run_harness(
    *,
    suite_names: list[str] | None = None,
    baseline_path: Path | None = None,
    max_drop: float = 0.02,
) -> HarnessReport:
    selected = suite_names or ["rag", "guardrails", "cache", "agent_core"]
    if "all" in selected:
        selected = ["rag", "guardrails", "cache", "agent_core"]

    runners = {
        "rag": run_rag_bench_suite,
        "guardrails": run_guardrails_bench_suite,
        "cache": run_cache_bench_suite,
        "agent_core": run_agent_core_suite,
        "live_judge": run_llm_judge_suite,
    }

    suites_out: dict[str, dict[str, Any]] = {}
    for name in selected:
        fn = runners.get(name)
        if fn is None:
            raise ValueError(f"Unknown eval suite: {name}")
        suites_out[name] = await fn()

    total = sum(int(s.get("total") or 0) for s in suites_out.values())
    passed = sum(int(s.get("passed") or 0) for s in suites_out.values())
    pass_rate = round(passed / max(1, total), 4)

    regressions: list[dict[str, Any]] = []
    if baseline_path is not None and baseline_path.is_file():
        baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
        regressions = check_regressions(suites_out, baseline_data, max_drop=max_drop)

    mode = "live-judge" if "live_judge" in selected else "offline-harness"
    return HarnessReport(
        mode=mode,
        dataset_name="whitz-eval-harness-v1",
        total=total,
        passed=passed,
        pass_rate=pass_rate,
        suites=suites_out,
        regressions=regressions,
        git_sha=_detect_git_sha(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Whitz Unified Eval Harness")
    parser.add_argument(
        "--suites",
        default="rag,guardrails,cache,agent_core",
        help="Comma-separated suites: rag,guardrails,cache,agent_core,live_judge,all",
    )
    parser.add_argument("--baseline", default="", help="Optional baseline JSON path for regression comparison.")
    parser.add_argument("--max-drop", type=float, default=0.02, help="Allowed metric drop before failing gate.")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero if any gated metric regresses.")
    parser.add_argument("--write-baseline", default="", help="Write current metrics snapshot as baseline JSON.")
    parser.add_argument("--report-json", default="", help="Write full JSON report to path.")
    parser.add_argument("--report-md", default="", help="Write Markdown summary report to path.")
    parser.add_argument("--report-url", default="", help="Optional Whitz server /api/admin/quant/evals/report URL.")
    parser.add_argument("--token", default="", help="Optional Bearer token for --report-url.")
    args = parser.parse_args(argv)

    suite_names = [s.strip() for s in args.suites.split(",") if s.strip()]
    baseline_path = Path(args.baseline) if args.baseline else None
    report = asyncio.run(run_harness(suite_names=suite_names, baseline_path=baseline_path, max_drop=args.max_drop))

    if args.write_baseline:
        out_base = Path(args.write_baseline)
        out_base.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "dataset_name": report.dataset_name,
            "mode": report.mode,
            "suites": {
                k: {
                    "total": v.get("total", 0),
                    "passed": v.get("passed", 0),
                    "pass_rate": v.get("pass_rate", 0.0),
                    "metrics": v.get("metrics") or {},
                }
                for k, v in report.suites.items()
            },
        }
        out_base.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.report_json:
        p = Path(args.report_json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.report_md:
        p = Path(args.report_md)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(report.to_markdown(), encoding="utf-8")

    if args.report_url:
        import httpx

        headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
        resp = httpx.post(args.report_url, json=report.to_admin_quant_payload(), headers=headers, timeout=15.0)
        resp.raise_for_status()

    print(report.to_markdown())
    if args.fail_on_regression and report.regressions:
        return 2
    if report.passed != report.total:
        return 1
    return 0
