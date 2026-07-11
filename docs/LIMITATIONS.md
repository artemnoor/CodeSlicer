# Limitations

CodeSlicer is a deterministic static impact analyzer with optional runtime
observations and evidence-gated support packs. It does not claim compiler-level
semantic parity for every language or framework.

- Python has the strongest semantic resolver coverage.
- Go, Java, JavaScript, and TypeScript combine structural extraction with
  partial semantic and framework-specific resolution.
- Reflection, runtime-selected dependency injection, complex generics,
  generated proxies, and unresolved dynamic dispatch remain ambiguous or
  unsupported rather than being promoted to confirmed edges.
- Runtime observations prove only what was observed in the selected test
  scenario; they do not prove all production paths.
- Support packs are versioned and confidence-capped. Draft and staged packs do
  not participate in ordinary analysis.
- The current scoring model is an interpretable heuristic, not a calibrated ML
  probability. Coefficients can be calibrated later against labeled changes,
  test outcomes, and user feedback.
