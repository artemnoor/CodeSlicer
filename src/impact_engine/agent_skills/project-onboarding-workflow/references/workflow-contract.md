# Workflow contract

| Need | Tool/output | Evidence rule |
| --- | --- | --- |
| Understand modules, communities and broad relationships | Graphify architecture graph | Separate, supplemental exploration graph; never affects CodeSlicer ranking. |
| Explain a symbol, diff risk or targeted test | CodeSlicer canonical graph | Use provenance and confidence; report unsupported or dynamic areas. |
| Fetch a repository | `onboard <url> --allow-network` | Only after explicit approval; clone stays in the local workspace. |
| Run tests or external tool commands | Project command / tool runtime | Only after explicit approval; record the result separately from static evidence. |

The onboarding report is stored locally in `.codeslicer/artifacts/onboarding/last.json`.
Its architecture artifact is stored separately under `.codeslicer/artifacts/graphify/graphify-out/`.
