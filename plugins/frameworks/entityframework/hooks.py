from plugins.frameworks.csharp_common import apply_efcore, hook_result


def ef_rules(context, graph):
    apply_efcore(graph, context.project_path)
    return hook_result(graph, "framework.csharp.entityframework")
