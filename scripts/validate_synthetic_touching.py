#!/usr/bin/env python3
"""Mandatory seeded-identity suite on labelled synthetic membrane fixtures.

Geometry: hollow bright rings with polar shrink (not filled cylinders).
Residual seeded merge/contamination is a **failure**, never a successful
“negative reference”. Unseeded baseline merge is **not** required for pass.

For each mandatory case the script scores:
  - target mask IoU, neighbour contamination, centroid error,
  - valid coverage, identity after blank gaps.

Ambiguous contact may pass via correct isolation **or** safe rejection.
Exit 0 only when every mandatory case passes.

Real CZI review is separate — see docs/validation-real-czi-signoff.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import ObjectSeed, analyze_stack
from morphostack.core.synthetic_touching import (
    all_mandatory_cases,
    score_case_from_predictions,
)


def _frame_flags(analysis, n_frames: int) -> tuple[list, list[bool], list[bool]]:
    """Extract contours, tracked flags, merge_rejected flags from StackAnalysis."""
    contours: list = [None] * n_frames
    tracked = [False] * n_frames
    merge_rejected = [False] * n_frames

    # analysis.frames use global frame indices starting at 0 for full-stack runs.
    by_idx = {int(f.frame_index): f for f in analysis.frames}
    track_by_idx = {}
    if analysis.tracking is not None:
        track_by_idx = {int(r.frame_index): r for r in analysis.tracking.records}

    for z in range(n_frames):
        fa = by_idx.get(z)
        if fa is not None and fa.contour is not None:
            contours[z] = fa.contour
            tracked[z] = True
        rec = track_by_idx.get(z)
        if rec is not None:
            if not rec.tracked:
                tracked[z] = False
                contours[z] = None
            merge_rejected[z] = bool(getattr(rec, "merge_rejected", False))
            if getattr(rec, "loss_reason", None) == "merge_rejected":
                merge_rejected[z] = True
    return contours, tracked, merge_rejected


def run_case(case, *, voxel: VoxelSize) -> dict:
    seed = ObjectSeed(
        x=float(case.seed_x),
        y=float(case.seed_y),
        frame_index=int(case.seed_frame),
        radius=float(case.seed_radius),
        type="circle",
    )
    analysis = analyze_stack(
        case.stack,
        thresholds=100.0,  # unused by seeded adaptive path; kept for API
        voxel_size=voxel,
        profile="vesicle",
        include_mesh=False,
        prefer_opencv=False,
        object_seed=seed,
    )
    contours, tracked, merge_rejected = _frame_flags(analysis, case.stack.shape[0])
    score = score_case_from_predictions(
        case,
        contours=contours,
        tracked=tracked,
        merge_rejected=merge_rejected,
    )
    return {
        "case_id": case.case_id,
        "description": case.description,
        "passed": score.passed,
        "summary": score.summary,
        "valid_coverage": score.valid_coverage,
        "mean_target_iou": score.mean_target_iou,
        "max_neighbor_contamination": score.max_neighbor_contamination,
        "mean_centroid_error_px": score.mean_centroid_error_px,
        "identity_after_gap_ok": score.identity_after_gap_ok,
        "seed": {
            "x": case.seed_x,
            "y": case.seed_y,
            "frame_index": case.seed_frame,
            "radius": case.seed_radius,
        },
        "geometry": {
            "stack_shape_zyx": list(case.stack.shape),
            "note": "Labelled synthetic membranes; not biological ground truth.",
        },
        "frames": [
            {
                "frame_index": fs.frame_index,
                "policy": fs.policy,
                "tracked": fs.tracked,
                "target_iou": fs.target_iou,
                "neighbor_contamination": fs.neighbor_contamination,
                "centroid_error_px": fs.centroid_error_px,
                "merge_rejected": fs.merge_rejected,
                "frame_pass": fs.frame_pass,
                "detail": fs.detail,
            }
            for fs in score.frames
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=str(PROJECT_ROOT / "validation" / "runs" / "synthetic-touching-membranes"),
        help="Directory for per-case JSON + aggregate summary.",
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    voxel = VoxelSize(1.0, 1.0, 1.0)
    cases = all_mandatory_cases()
    results = []
    for case in cases:
        result = run_case(case, voxel=voxel)
        results.append(result)
        (out_dir / f"{case.case_id}.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

    all_pass = all(bool(r["passed"]) for r in results)
    aggregate = {
        "suite": "synthetic-touching-membranes",
        "mandatory_case_count": len(results),
        "passed_count": sum(1 for r in results if r["passed"]),
        "failed_count": sum(1 for r in results if not r["passed"]),
        "all_passed": all_pass,
        "exit_zero_only_if_all_mandatory_pass": True,
        "residual_seeded_merge_is_failure": True,
        "unseeded_merge_not_required": True,
        "synthetic_limits": (
            "Hollow-ring geometry with polar shrink and labelled masks. "
            "IoU/contamination gates are computational, not biological proof. "
            "Real crowded CZI sign-off is separate (docs/validation-real-czi-signoff.md)."
        ),
        "cases": [
            {"case_id": r["case_id"], "passed": r["passed"], "summary": r["summary"]}
            for r in results
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    # Compat alias for older tooling that looked for failure-summary.json
    (out_dir / "failure-summary.json").write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Synthetic Touching Membranes — Seeded Identity Suite",
        "",
        f"**Aggregate: {'PASS' if all_pass else 'FAIL'}** "
        f"({aggregate['passed_count']}/{aggregate['mandatory_case_count']} cases)",
        "",
        "Residual seeded merge/contamination is a **failure**, not a successful negative reference.",
        "Fixtures: hollow membrane rings + polar shrink + per-frame target/neighbour masks.",
        "",
        "| Case | Result |",
        "| --- | --- |",
    ]
    for r in results:
        lines.append(f"| `{r['case_id']}` | {'PASS' if r['passed'] else 'FAIL'} |")
    lines.extend(
        [
            "",
            "Real-data protocol: [validation-real-czi-signoff.md](../../../docs/validation-real-czi-signoff.md)",
            "",
            "```powershell",
            "python scripts/validate_synthetic_touching.py",
            "```",
            "",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(aggregate, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
