# Bundled graph libraries

This local UI bundles the following MIT-licensed browser libraries so graph
rendering works without a CDN connection:

- `force-graph` 1.51.4, https://github.com/vasturiano/force-graph
- `3d-force-graph` 1.80.0, https://github.com/vasturiano/3d-force-graph

The application graph data, filters, selections, and evidence remain produced
by the local Impact Engine backend. These libraries only calculate layout and
render the already analysed nodes and edges.
