from impact_engine.graph_identity import annotate_stable_identities
from impact_engine.models import GraphDocument, Node


def test_unresolved_local_endpoint_becomes_a_canonical_alias_not_external():
    graph = GraphDocument()
    graph.add_node(Node(
        "method:backend.app.crud.create_user", "METHOD", "create_user",
        {"file": "backend/app/crud.py", "scope": "backend.app.crud.create_user"},
    ))
    graph.add_node(Node(
        "backend.app.crud.create_user", "EXTERNAL_LIBRARY", "backend.app.crud.create_user",
        {"unresolved_endpoint": True},
    ))

    annotate_stable_identities(graph, "C:/workspace/project")

    alias = next(node for node in graph.nodes if node.id == "backend.app.crud.create_user")
    assert alias.kind == "CANONICAL_ALIAS"
    assert alias.properties["canonical_alias_of"] == "method:backend.app.crud.create_user"
    assert alias.properties["canonical_identity"]["origin"] == "workspace_alias"
    assert graph.metadata["identity"]["workspace_aliases"] == 1
