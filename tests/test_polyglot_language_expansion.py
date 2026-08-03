from __future__ import annotations

from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.extractors.tree_sitter.adapter import extract_tree_sitter_project
from impact_engine.review import build_review_report


def _write(project: Path, relative: str, content: str) -> None:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_modern_frontend_and_native_extensions_are_selected_and_reviewed(tmp_path: Path):
    _write(tmp_path, "src/util.ts", "export const normalize = (value: string) => value.trim();\n")
    _write(tmp_path, "src/main.mts", "import { normalize } from './util'; export const run = (value: string) => normalize(value);\n")
    _write(tmp_path, "native/main.cpp", "int helper() { return 1; } int run() { return helper(); }\n")
    _write(tmp_path, "web/index.html", "<main><h1>CodeSlicer</h1></main>\n")
    _write(tmp_path, "web/site.css", ".card { color: rebeccapurple; }\n")
    _write(tmp_path, "web/App.vue", "<template><main>Vue</main></template><script setup lang=\"ts\">const ready = true</script>\n")
    _write(tmp_path, "web/App.svelte", "<script>const ready = true;</script><main>{ready}</main>\n")
    _write(tmp_path, "web/index.astro", "---\nconst title = 'Astro';\n---\n<h1>{title}</h1>\n")

    result = analyze_project_core(str(tmp_path), create_research_requests=False)
    assert result["status"] == "ok"
    metadata = result["graph"]["metadata"]
    selected = {item["id"] for item in metadata["plugin_selection_plan"]["selected"]}
    assert {"language.typescript", "language.cpp", "language.html", "language.css", "language.vue", "language.svelte", "language.astro"} <= selected

    capabilities = metadata["language_semantic_capabilities"]
    assert {"typescript", "cpp", "html", "css", "vue", "svelte", "astro"} <= set(capabilities)
    exact_ts_edges = [
        edge for edge in result["graph"]["edges"]
        if edge["kind"] == "CALLS" and edge.get("properties", {}).get("provider") == "typescript_local_import_resolver"
    ]
    assert any(edge["from"].endswith(":run") and edge["to"].endswith(":normalize") for edge in exact_ts_edges)

    report = build_review_report(
        str(tmp_path),
        diff_text="""diff --git a/native/main.cpp b/native/main.cpp
--- a/native/main.cpp
+++ b/native/main.cpp
@@ -1 +1 @@
-int helper() { return 1; } int run() { return helper(); }
+int helper() { return 2; } int run() { return helper(); }
diff --git a/web/App.vue b/web/App.vue
--- a/web/App.vue
+++ b/web/App.vue
@@ -1 +1 @@
-<template><main>Vue</main></template><script setup lang=\"ts\">const ready = true</script>
+<template><main>Vue 3</main></template><script setup lang=\"ts\">const ready = true</script>
""",
        refresh="never",
    )
    coverage = {item["path"]: item for item in report["coverage"]}
    assert coverage["native/main.cpp"]["language"] == "cpp"
    assert coverage["native/main.cpp"]["status"] == "limited"
    assert coverage["web/App.vue"]["language"] == "vue"
    assert coverage["web/App.vue"]["status"] == "limited"


def test_tree_sitter_extracts_cpp_and_frontend_file_nodes(tmp_path: Path):
    _write(tmp_path, "main.c", "int helper() { return 1; } int run() { return helper(); }\n")
    _write(tmp_path, "index.html", "<button>Save</button>\n")
    _write(tmp_path, "site.css", ".button { display: block; }\n")
    _write(tmp_path, "App.vue", "<template><button>Save</button></template>\n")
    _write(tmp_path, "App.svelte", "<main>Save</main>\n")
    _write(tmp_path, "index.astro", "<main>Save</main>\n")

    graph = extract_tree_sitter_project(tmp_path, languages=["cpp", "html", "css", "vue", "svelte", "astro"])
    node_ids = {node.id for node in graph.nodes}
    for source in ("main.c", "index.html", "site.css", "App.vue", "App.svelte", "index.astro"):
        assert f"file:{source}" in node_ids
    assert graph.metadata["tree_sitter_status"] == "native"
