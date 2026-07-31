from plugins.frameworks.csharp_common import apply_aspnet, hook_result


def aspnetcore_rules(context, graph):
    apply_aspnet(graph, context.project_path)
    return hook_result(graph, "framework.csharp.aspnetcore")
