#!/usr/bin/env python3
"""Run real-data promotion gates (validation-only harness).

Usage:
  python scripts/run_real_data_promotion_gates.py --corpus validation/promotion/fixtures/blocked_empty
  python scripts/run_real_data_promotion_gates.py --corpus path/to/corpus --out path/to/report_dir

Exit codes:
  0  overall PROMOTE_ENGINEERING
  2  BLOCKED / INCOMPLETE
  3  REJECT / REJECT_SCIENTIFICALLY / REJECT_SPEED
  1  usage / load error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from validation.promotion.gates import evaluate_promotion  # noqa: E402
from validation.promotion.report import render_gate_report, to_markdown  # noqa: E402
from validation.promotion.schema import load_corpus_dir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="Directory with corpus_manifest.json (+ optional predictions.json)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write gate_report.json/md here (default: <corpus>/reports/promotion)",
    )
    p.add_argument(
        "--no-require-speed",
        action="store_true",
        help="Treat missing latency as NOT_APPLICABLE instead of INCOMPLETE",
    )
    args = p.parse_args(argv)

    try:
        corpus, preds = load_corpus_dir(args.corpus)
    except Exception as exc:
        print(f"ERROR: failed to load corpus: {exc}", file=sys.stderr)
        return 1

    result = evaluate_promotion(
        corpus,
        preds,
        require_speed=not args.no_require_speed,
    )
    out = args.out or (args.corpus / "reports" / "promotion")
    paths = render_gate_report(result, out_dir=out)
    print(to_markdown(result))
    print(f"\nWrote: {paths.get('json')} {paths.get('md')}")
    print(f"overall={result['overall']} composite_accuracy_percent={result['composite_accuracy_percent']}")

    overall = result["overall"]
    if overall == "PROMOTE_ENGINEERING":
        return 0
    if overall in ("BLOCKED", "INCOMPLETE"):
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
