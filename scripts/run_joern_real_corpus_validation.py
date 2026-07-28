"""Run one explicitly selected local Joern real-corpus validation case."""
from __future__ import annotations

import argparse
import json
import sys

from impact_engine.adapters.joern_real_validation import run_real_corpus_validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one real local Joern source-to-sink corpus case")
    parser.add_argument("--joern", required=True, help="absolute path to an installed local Joern executable or directory")
    parser.add_argument("--corpus", required=True, help="absolute path to an already local corpus checkout")
    parser.add_argument("--manifest", required=True, help="absolute path to the pinned corpus manifest")
    parser.add_argument("--case", required=True, dest="case_id")
    parser.add_argument("--output", default=None, help="absolute bounded JSON report path")
    parser.add_argument("--impact-engine", default=None, help="absolute impact-engine executable; otherwise resolve from PATH")
    parser.add_argument("--java-home", default=None, help="absolute local Java 21 home for Joern; otherwise use JAVA_HOME")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    try:
        report = run_real_corpus_validation(args.joern, args.corpus, args.manifest, args.case_id, output_path=args.output, impact_engine_path=args.impact_engine, java_home=args.java_home, timeout=args.timeout)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(json.dumps({"schema_version": "CodeSlicerJoernRealCorpusReport/v1", "status": "blocked", "diagnostics": [{"code": "validation_blocked", "severity": "error", "message": f"validation could not start ({type(exc).__name__})"}], "privacy": {"mode": "local-only", "network_used": False, "absolute_user_paths_stored": False}}, indent=2, ensure_ascii=False))
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
