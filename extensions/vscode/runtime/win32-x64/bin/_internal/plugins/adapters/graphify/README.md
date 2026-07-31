# Graphify adapter

Graphify is an optional local artifact adapter. Import an existing absolute
path such as `graphify-out/graph.json`; CodeSlicer does not run Graphify and
does not upload or copy the raw graph into `.codeslicer`. A sanitized overlay
is stored locally and the original path/fingerprint is retained for freshness.

Imported nodes and edges are marked `source=graphify`, `DOC_INFERRED`, and
`overlay_only`. They can explain or extend bounded Inspect/Investigate views,
but never mutate `.impact_engine`, Review risk, ranking, or test recommendations.

Supported input is the Graphify JSON subset with `nodes` and `edges`/`links`.
Missing or unsupported fields produce an `incomplete`/`unsupported` diagnostic;
the adapter never invents relationships.
