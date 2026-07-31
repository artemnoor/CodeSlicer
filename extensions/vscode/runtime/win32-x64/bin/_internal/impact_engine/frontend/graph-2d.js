/* 2D graph adapter boundary. Rendering remains deterministic and local. */
(function (global) {
  global.ImpactGraph2D = {
    visibleEdges(nodes, edges) {
      const ids = new Set(nodes.map((node) => node.id));
      return edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to));
    },
  };
})(window);
