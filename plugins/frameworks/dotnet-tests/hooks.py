from plugins.frameworks.csharp_common import apply_tests, hook_result


def test_rules(context, graph):
    apply_tests(graph, context.project_path)
    return hook_result(graph, "framework.csharp.dotnet-tests")
