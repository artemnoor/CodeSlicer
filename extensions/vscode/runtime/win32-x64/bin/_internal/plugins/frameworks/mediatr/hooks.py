from plugins.frameworks.csharp_common import apply_mediatr, hook_result


def mediatr_rules(context, graph):
    apply_mediatr(graph, context.project_path)
    return hook_result(graph, "framework.csharp.mediatr")
