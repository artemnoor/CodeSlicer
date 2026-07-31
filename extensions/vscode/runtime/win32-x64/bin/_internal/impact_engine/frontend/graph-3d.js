/* 3D graph adapter boundary for the local force-graph renderer. */
(function (global) {
  global.ImpactGraph3D = {
    visibleEdges(nodes, edges) {
      const ids = new Set(nodes.map((node) => node.id));
      return edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to));
    },
  };
})(window);
