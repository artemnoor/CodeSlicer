"""Synchronize packaged skills from the checkout's canonical .agents copy."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".agents" / "skills"
TARGET = ROOT / "src" / "impact_engine" / "agent_skills"
SKILLS = ("code-intelligence-orchestrator", "codeslicer-impact-analysis", "graphify-architecture-analysis", "project-onboarding-workflow")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="copy canonical checkout skills into the packaged location")
    args = parser.parse_args()
    mismatches: list[str] = []
    for name in SKILLS:
        source = SOURCE / name / "SKILL.md"
        target = TARGET / name / "SKILL.md"
        if not source.is_file():
            raise FileNotFoundError(source)
        if not target.is_file() or source.read_bytes() != target.read_bytes():
            mismatches.append(name)
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    if mismatches and not args.write:
        print("skills out of sync: " + ", ".join(mismatches), file=sys.stderr)
        return 1
    print("skills synchronized" if mismatches else "skills already synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
