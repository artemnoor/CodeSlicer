"""Stable plugin entrypoint for the local SCIP adapter."""

from impact_engine.adapters.scip import build_scip_overlay, map_scip_overlay, parse_scip_artifact

__all__ = ["build_scip_overlay", "map_scip_overlay", "parse_scip_artifact"]
