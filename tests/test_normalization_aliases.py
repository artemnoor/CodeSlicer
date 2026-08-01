from impact_engine.models import Edge, GraphDocument, Node
from impact_engine.normalization.graph import normalize_graph_document


def test_existing_unresolved_scope_endpoint_is_reclassified_as_workspace_alias():
    graph = GraphDocument()
    graph.add_node(Node(
        "app.crud.create_user", "EXTERNAL_LIBRARY", "app.crud.create_user",
        {"unresolved": True},
    ))
    graph.add_node(Node(
        "method:app.crud.create_user", "METHOD", "create_user",
        {"scope": "app.crud.create_user", "file": "app/crud.py"},
    ))
    graph.add_node(Node("method:app.routes.create", "METHOD", "create", {"scope": "app.routes.create", "file": "app/routes.py"}))
    graph.add_edge(Edge("call", "CALLS", "method:app.routes.create", "app.crud.create_user"))

    normalize_graph_document(graph)

    alias = next(node for node in graph.nodes if node.id == "app.crud.create_user")
    assert alias.kind == "CANONICAL_ALIAS"
    assert alias.properties["canonical_alias_of"] == "method:app.crud.create_user"
