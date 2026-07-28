"""Public plugin facade for the local LSP adapter."""

from impact_engine.adapters.lsp import (
    configure_lsp,
    disable_lsp,
    lsp_status,
    map_lsp_overlay,
    probe_lsp,
    query_lsp,
)

__all__ = ["configure_lsp", "disable_lsp", "lsp_status", "map_lsp_overlay", "probe_lsp", "query_lsp"]
