#!/usr/bin/env python3
"""CLI: validate an RBC Phase 5 lab evidence manifest (fail-closed)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morphostack.core.rbc_evidence import validate_rbc_evidence_bundle  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        default=str(ROOT / "validation" / "references" / "rbc-annotations-v1" / "manifest.json"),
        help="Path to evidence manifest JSON",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to write the validation result JSON",
    )
    args = parser.parse_args(argv)

    result = validate_rbc_evidence_bundle(args.manifest)
    payload = result.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")

    if result.accepted:
        print("RESULT: accepted (lab threshold approval still required for promotion)")
        return 0
    print("RESULT: refused")
    for code in result.reasons:
        print(f"  - {code}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
