---
name: graphify-architecture-analysis
description: Build and inspect a separate Graphify architecture graph and communities.
---

# Graphify Architecture Analysis

Run Graphify explicitly when an architecture view is required:

```bash
impact-engine adapters native <project> graphify index --confirm
impact-engine adapters native <project> graphify query --query "<concept>" --confirm
```

The resulting `graphify-out/graph.json` is a Graphify artifact. It may be imported as a separately attributed overlay, but it does not replace canonical CodeSlicer impact evidence. Report missing artifacts and unsupported patterns honestly.
