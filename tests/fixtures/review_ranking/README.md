# Review ranking golden fixtures

Each scenario may contain `project/`, `diff.patch`, and `expected.json`.
Reports contain entity IDs, policy versions, and aggregate metrics only; they
do not contain source code. Real corpora remain in `tests/corpus/` and are
referenced by the local corpus manifest instead of being copied into this
fixture directory.

The synthetic fixture has a manually reviewed top-5 label set. It tests the
directional distinction between downstream consumers (`app`/`app.main`) and a
dependency called by the changed function (`repository.save`), which must not
be promoted to a top impact merely because it is adjacent in the graph.
