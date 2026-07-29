# Visual-regression baselines

This directory is deliberately empty until a maintainer approves a baseline.
The browser E2E tests always validate behavior; pixel comparison is opt-in
because a screenshot is a product decision, not a test by-product.

When a UI change is intentionally accepted:

1. Run the browser E2E at the agreed desktop and mobile viewports.
2. Inspect the generated screenshots manually.
3. Copy the approved PNGs here with stable names that identify the scenario
   and viewport.
4. Add a dedicated visual-diff check that compares only against those approved
   images. Updating a baseline must be a separate, reviewed commit.

Graphify screenshots are not stored here: Graphify remains an independent
optional product and its renderer is not a CodeSlicer visual baseline.
