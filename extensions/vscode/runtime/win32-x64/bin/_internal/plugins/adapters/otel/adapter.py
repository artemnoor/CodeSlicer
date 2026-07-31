"""The OTel adapter implementation lives in impact_engine.adapters.otel."""

from impact_engine.adapters.otel import build_otel_overlay, map_otel_overlay, parse_otel_trace

__all__ = ["build_otel_overlay", "map_otel_overlay", "parse_otel_trace"]
