from __future__ import annotations

import math
from typing import Any, Sequence


def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: set[str] | Sequence[str], k: int) -> float:
    rel = set(relevant_ids)
    if not rel or k <= 0:
        return 0.0
    hits = sum(1 for doc_id in retrieved_ids[:k] if doc_id in rel)
    return hits / len(rel)


def mrr_at_k(retrieved_ids: Sequence[str], relevant_ids: set[str] | Sequence[str], k: int) -> float:
    rel = set(relevant_ids)
    if not rel or k <= 0:
        return 0.0
    for idx, doc_id in enumerate(retrieved_ids[:k], start=1):
        if doc_id in rel:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(retrieved_ids: Sequence[str], relevance_grades: dict[str, float | int], k: int) -> float:
    if not relevance_grades or k <= 0:
        return 0.0

    def _dcg(grades: Sequence[float]) -> float:
        return sum((2.0**g - 1.0) / math.log2(idx + 2.0) for idx, g in enumerate(grades))

    actual_grades = [float(relevance_grades.get(doc_id, 0.0)) for doc_id in retrieved_ids[:k]]
    ideal_grades = sorted((float(v) for v in relevance_grades.values() if v > 0), reverse=True)[:k]
    idcg = _dcg(ideal_grades)
    if idcg <= 0.0:
        return 0.0
    return _dcg(actual_grades) / idcg


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 4)
    rank = (max(0.0, min(100.0, p)) / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = min(len(ordered) - 1, lo + 1)
    frac = rank - lo
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac, 4)


def mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(float(v) for v in values) / len(values), 4)
