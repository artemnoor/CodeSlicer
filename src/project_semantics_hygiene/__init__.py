"""Portable semantic hygiene/classification layer for project impact analysis.

This package intentionally does not parse source code or build an impact graph.
It classifies already known project signals and annotates generic graph data.
"""

from .models import (
    CanonicalRoute,
    DependencyClassification,
    DependencyKind,
    FileClassification,
    FileRole,
    GraphEdgeAnnotation,
    GraphNodeAnnotation,
    HygieneReport,
    ProjectFile,
    Reachability,
    RouteParamStyle,
)
from .file_roles import FileRoleClassifier
from .dependency_classifier import DependencyClassifier
from .route_normalizer import RouteNormalizer, canonical_route_key
from .graph_annotator import GraphAnnotator
from .impact_filters import ImpactFilter, group_nodes_by_semantic_role
from .pipeline import HygienePipeline
from .rule_pack import HygieneRulePack, default_rule_pack, load_rule_pack, save_rule_pack
from .serialization import to_json, from_json_report, dump_json, load_json

__all__ = [
    "CanonicalRoute",
    "DependencyClassification",
    "DependencyKind",
    "FileClassification",
    "FileRole",
    "GraphEdgeAnnotation",
    "GraphNodeAnnotation",
    "HygieneReport",
    "ProjectFile",
    "Reachability",
    "RouteParamStyle",
    "FileRoleClassifier",
    "DependencyClassifier",
    "RouteNormalizer",
    "canonical_route_key",
    "GraphAnnotator",
    "ImpactFilter",
    "group_nodes_by_semantic_role",
    "HygienePipeline",
    "HygieneRulePack",
    "default_rule_pack",
    "load_rule_pack",
    "save_rule_pack",
    "to_json",
    "from_json_report",
    "dump_json",
    "load_json",
]
