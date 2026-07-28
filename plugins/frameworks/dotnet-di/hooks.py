from plugins.frameworks.csharp_common import apply_di, hook_result


def di_rules(context, graph):
    apply_di(graph, context.project_path)
    return hook_result(graph, "framework.csharp.dotnet-di")
