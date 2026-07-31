"""Manifest-facing Gortex adapter entrypoint."""
from impact_engine.adapters.gortex import build_gortex_overlay, parse_gortex_graphml

__all__ = ["build_gortex_overlay", "parse_gortex_graphml"]
