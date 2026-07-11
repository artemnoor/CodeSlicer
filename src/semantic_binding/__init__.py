"""Universal semantic binding layer."""

from .facts import FactSet
from .models import (
    AssignmentFact,
    Binding,
    CallFact,
    ClassFact,
    DataFlowFact,
    DecoratorFact,
    Evidence,
    ExportFact,
    FunctionFact,
    ImportFact,
    Recipe,
    ResolutionResult,
    ResolvedEdge,
    ReturnFact,
    Symbol,
)
from .resolver import SemanticResolver
from .integration import semantic_result_to_graph_edges

__all__ = [
    "AssignmentFact",
    "Binding",
    "CallFact",
    "ClassFact",
    "DataFlowFact",
    "DecoratorFact",
    "Evidence",
    "ExportFact",
    "FactSet",
    "FunctionFact",
    "ImportFact",
    "Recipe",
    "ResolutionResult",
    "ResolvedEdge",
    "ReturnFact",
    "SemanticResolver",
    "semantic_result_to_graph_edges",
    "Symbol",
]
