"""Versioned, explainable policy for the review projection.

The full graph contains facts.  This policy only decides how facts compete for
space in the concise developer review.  Keeping the coefficients named and
versioned makes a ranking change observable and makes golden fixtures useful.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RankingFactor:
    name: str
    value: float
    rationale: str
    test_fixture: str
    expected_influence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "rationale": self.rationale,
            "test_fixture": self.test_fixture,
            "expected_influence": self.expected_influence,
        }


@dataclass(frozen=True)
class RankingPolicy:
    version: str
    factors: tuple[RankingFactor, ...]
    max_results: int = 10
    max_per_file: int = 5
    max_per_cluster: int = 5

    def weights(self) -> Mapping[str, float]:
        return {factor.name: factor.value for factor in self.factors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "max_results": self.max_results,
            "max_per_file": self.max_per_file,
            "max_per_cluster": self.max_per_cluster,
            "factors": [factor.to_dict() for factor in self.factors],
        }


def _factor(name: str, value: float, rationale: str, fixture: str, influence: str) -> RankingFactor:
    return RankingFactor(name, value, rationale, fixture, influence)


DEFAULT_RANKING_POLICY = RankingPolicy(
    version="review-ranking/v1.5",
    factors=(
        _factor("changed_symbol", 100.0, "The changed declaration is the primary review anchor.", "changed_symbol", "always anchors the result set"),
        _factor("changed_callable", 6.0, "A changed callable is more precise for action than a file-only anchor.", "changed_callable", "orders changed methods/functions before their containing file"),
        _factor("direct_container", 60.0, "A changed file's directly contained module is a first-order review context.", "direct_container", "keeps the changed module above deep unrelated consumers"),
        _factor("direct_import_export", 60.0, "Imports and exports are exact cross-file dependency evidence and should outrank weak transitive calls.", "direct_import", "raises direct file/module impacts above weak transitive paths"),
        _factor("direct_resolved_call", 32.0, "A resolved call is stronger than a name-only relationship.", "direct_call", "raises direct service impacts"),
        _factor("changed_downstream", 45.0, "A confirmed call from the changed method is a first-order review impact, not an unrelated graph neighbour.", "changed_method_downstream", "keeps save/send/handler calls from the changed callable in top impact"),
        _factor("test_direct", 38.0, "A test directly exercising the changed symbol is immediately actionable.", "targeted_test", "raises the exact test above fallback suites"),
        _factor("route_handler_boundary", 40.0, "Route-to-handler evidence marks a public API boundary.", "route_boundary", "raises API/controller impacts"),
        _factor("frontend_backend_boundary", 36.0, "A proven request/endpoint relationship crosses an application boundary.", "frontend_backend", "raises contract impacts"),
        _factor("schema_database_boundary", 34.0, "Schema/entity to persistence evidence indicates data compatibility risk.", "schema_boundary", "raises database impacts"),
        _factor("queue_boundary", 32.0, "Producer/consumer evidence marks an asynchronous boundary.", "queue_boundary", "raises queue impacts"),
        _factor("public_api_boundary", 28.0, "Public API symbols are more consequential than internal helpers.", "public_api", "raises public boundary impacts"),
        _factor("cross_package", 22.0, "Cross-package evidence expands the change surface.", "cross_package", "raises package boundary impacts"),
        _factor("critical_path", 24.0, "Configured critical paths deserve explicit review attention.", "critical_path", "raises configured critical symbols"),
        _factor("independent_evidence_path", 15.0, "Independent paths reduce the chance of a single extractor artifact.", "multiple_paths", "raises corroborated impacts"),
        _factor("test_coverage", 12.0, "A test relation is useful evidence even when it is not direct.", "targeted_test", "raises test-related impacts"),
        _factor("transitive_depth", -15.0, "Deep transitive paths without a boundary are less actionable; distance is never the only score.", "deep_transitive", "lowers deep internal hops without suppressing boundaries"),
        _factor("assignment_only", -30.0, "Assignments are technical evidence, not default review entities.", "assignment_noise", "suppresses assignment-only candidates"),
        _factor("builtin", -55.0, "Built-ins do not help a developer decide what to inspect.", "builtin_noise", "removes built-in noise"),
        _factor("external_library", -45.0, "External libraries are retained in the full graph but not concise cards.", "external_noise", "suppresses external terminals"),
        _factor("generated_or_vendor", -60.0, "Generated/vendor files are usually non-actionable review results.", "generated_noise", "suppresses generated/vendor noise"),
        _factor("weak_name_inference", -24.0, "Name-only inference must not outrank static evidence.", "ambiguous_name", "lowers weak inferred links"),
        _factor("ambiguous", -38.0, "Ambiguity is a warning, not proof of impact.", "ambiguous_edge", "prevents ambiguous high confidence"),
        _factor("unresolved_endpoint", -50.0, "Unresolved endpoints remain visible as coverage warnings, not impacts.", "unresolved_endpoint", "excludes unresolved boundary nodes"),
        _factor("duplicate_path", -10.0, "Near-identical evidence paths should not crowd out diverse results.", "duplicate_path", "deduplicates similar chains"),
        _factor("high_fanout_hub", 25.0, "A graph-proven hub with independent evidence is a useful review boundary, not a raw node-count metric.", "hub_boundary", "raises a high-value UI/service symbol above deep container noise"),
    ),
)

TEST_SELECTION_POLICY_VERSION = "review-tests/v6"
REVIEW_PROJECTION_POLICY_VERSION = "review-projection/v9"
REVIEW_SCHEMA_VERSION = "ReviewProjection/v1"


def ranking_policy_metadata(policy: RankingPolicy = DEFAULT_RANKING_POLICY) -> dict[str, Any]:
    return policy.to_dict()
