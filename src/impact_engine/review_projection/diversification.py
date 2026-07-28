"""Bounded top-K selection with file/module and semantic-cluster diversity."""
from __future__ import annotations

from typing import Any, Iterable

from .contracts import ReviewCandidate
from .filters import is_test_node
from impact_engine.ranking_policy import DEFAULT_RANKING_POLICY, RankingPolicy


def diversify_candidates(candidates: Iterable[ReviewCandidate], limit: int, policy: RankingPolicy = DEFAULT_RANKING_POLICY) -> list[ReviewCandidate]:
    if limit <= 0:
        return []
    remaining = sorted(candidates, key=lambda item: (-item.rank.score, item.entity_id))
    selected: list[ReviewCandidate] = []
    files: dict[str, int] = {}
    clusters: dict[str, int] = {}
    classes: dict[str, int] = {}
    # Changed symbols are anchors, not just another transitive candidate.
    # Reserve them first; otherwise a test fan-out can crowd the actual diff
    # out of the first page.
    anchors = [item for item in remaining if "changed_symbol" in item.rank.factors]
    anchor_files = {item.file for item in anchors if item.file}
    for picked in anchors:
        if len(selected) >= min(limit, policy.max_results):
            break
        file_name = picked.file or "<unknown>"
        cluster = picked.cluster or "<unknown>"
        if files.get(file_name, 0) >= policy.max_per_file or clusters.get(cluster, 0) >= policy.max_per_cluster:
            continue
        selected.append(picked)
        remaining.remove(picked)
        files[file_name] = files.get(file_name, 0) + 1
        clusters[cluster] = clusters.get(cluster, 0) + 1
        classes[picked.impact_class] = classes.get(picked.impact_class, 0) + 1
    # A small class bonus encourages the intended mix without overpowering
    # evidence score.  Direct changed symbols are already anchored by policy.
    while remaining and len(selected) < min(limit, policy.max_results):
        def utility(item: ReviewCandidate) -> tuple[float, int, str]:
            class_bonus = 3.0 if classes.get(item.impact_class, 0) == 0 else 0.0
            test_bonus = 2.0 if item.kind == "TEST" and classes.get("test", 0) == 0 else 0.0
            csharp_anchor = any(str(file_name).lower().endswith(".cs") for file_name in anchor_files)
            same_file_bonus = 10.0 if csharp_anchor and item.file and item.file in anchor_files else 0.0
            return (item.rank.score + class_bonus + test_bonus + same_file_bonus, -len(selected), item.entity_id)

        picked = max(remaining, key=utility)
        remaining.remove(picked)
        file_name = picked.file or "<unknown>"
        cluster = picked.cluster or "<unknown>"
        if files.get(file_name, 0) >= policy.max_per_file or clusters.get(cluster, 0) >= policy.max_per_cluster:
            continue
        selected.append(picked)
        files[file_name] = files.get(file_name, 0) + 1
        clusters[cluster] = clusters.get(cluster, 0) + 1
        classes[picked.impact_class] = classes.get(picked.impact_class, 0) + 1
        if picked.kind == "TEST":
            classes["test"] = classes.get("test", 0) + 1
    return selected
