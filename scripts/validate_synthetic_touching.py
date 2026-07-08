#!/usr/bin/env python3
"""Document threshold-merge failure on synthetic touching vesicles (negative reference)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from morphostack.core.export import (
    analysis_manifest,
    analysis_run_warnings,
    write_analysis_csv,
    write_analysis_manifest_json,
)
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import ObjectSeed, analyze_stack


def build_touching_vesicle_stack(
    *,
    shape: tuple[int, int, int] = (5, 80, 80),
    large_center: tuple[float, float] = (30.0, 40.0),
    large_radius: float = 12.0,
    small_center: tuple[float, float] = (48.0, 40.0),
    small_radius: float = 8.0,
    intensity: int = 220,
) -> np.ndarray:
    stack = np.zeros(shape, dtype=np.uint8)
    lcx, lcy = large_center
    scx, scy = small_center
    for z in range(shape[0]):
        for y in range(shape[1]):
            for x in range(shape[2]):
                if np.hypot(x - lcx, y - lcy) < large_radius or np.hypot(x - scx, y - scy) < small_radius:
                    stack[z, y, x] = intensity
    return stack


def center_frame_neighbor_bleed(*, analysis, frame_index: int, neighbor_x: float) -> bool:
    frame = analysis.frames[frame_index]
    if frame.contour is None or len(frame.contour) == 0:
        return False
    return float(np.max(frame.contour[:, 0])) > neighbor_x


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=str(PROJECT_ROOT / "validation" / "runs" / "synthetic-touching-failure"),
        help="Validation output directory.",
    )
    parser.add_argument(
        "--with-active-surfaces",
        dest="with_active_surfaces",
        action="store_true",
        help="Also run the experimental Active Surfaces profile (slow; optional comparison only).",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stack = build_touching_vesicle_stack()
    voxel = VoxelSize(1.0, 1.0, 1.0)
    threshold = 100.0
    seed = ObjectSeed(x=30.0, y=40.0, frame_index=2, radius=9.0, type="circle")

    threshold_only = analyze_stack(
        stack,
        thresholds=threshold,
        voxel_size=voxel,
        profile="vesicle",
        include_mesh=True,
        prefer_opencv=False,
    )
    threshold_seeded = analyze_stack(
        stack,
        thresholds=threshold,
        voxel_size=voxel,
        profile="vesicle",
        include_mesh=True,
        prefer_opencv=False,
        object_seed=seed,
    )

    write_analysis_csv(threshold_only, out_dir / "threshold-only-metrics.csv")
    write_analysis_csv(threshold_seeded, out_dir / "threshold-seeded-metrics.csv")

    threshold_only_vol = threshold_only.mesh.volume_um3 if threshold_only.mesh else 0.0
    threshold_mesh_vol = threshold_seeded.mesh.volume_um3 if threshold_seeded.mesh else 0.0
    threshold_warnings = {str(item["code"]) for item in analysis_run_warnings(threshold_seeded, voxel_source="override")}

    # Fast negative reference: circle seed does not stop threshold tracking from merging neighbors.
    seed_ignored = abs(threshold_mesh_vol - threshold_only_vol) < max(50.0, threshold_only_vol * 0.05)
    merge_detected = "likely_neighbor_merge" in threshold_warnings
    contour_bleeds = center_frame_neighbor_bleed(
        analysis=threshold_seeded,
        frame_index=seed.frame_index,
        neighbor_x=42.0,
    )
    failure_mode_confirmed = seed_ignored or merge_detected or contour_bleeds

    active_surfaces_mesh_vol = None
    if args.with_active_surfaces:
        active_surfaces_seeded = analyze_stack(
            stack,
            thresholds=threshold,
            voxel_size=voxel,
            profile="active_surfaces",
            include_mesh=True,
            prefer_opencv=False,
            object_seed=seed,
        )
        write_analysis_csv(active_surfaces_seeded, out_dir / "active_surfaces-seeded-metrics.csv")
        active_surfaces_mesh_vol = active_surfaces_seeded.mesh.volume_um3 if active_surfaces_seeded.mesh else 0.0

    summary = {
        "case": "synthetic-touching-failure",
        "expected": "threshold vesicle profile merges touching neighbors despite circle seed",
        "failure_mode_confirmed": failure_mode_confirmed,
        "threshold_only_mesh_volume_um3": threshold_only_vol,
        "threshold_seeded_mesh_volume_um3": threshold_mesh_vol,
        "active_surfaces_seeded_mesh_volume_um3": active_surfaces_mesh_vol,
        "threshold_warning_codes": sorted(threshold_warnings),
        "checks": {
            "seed_ignored_same_mesh_as_unseeded": seed_ignored,
            "likely_neighbor_merge": merge_detected,
            "center_frame_contour_bleeds_past_neighbor": contour_bleeds,
        },
    }
    (out_dir / "failure-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    manifest = analysis_manifest(
        threshold_seeded,
        source_path="synthetic-touching-failure",
        threshold=threshold,
        include_mesh=True,
        prefer_opencv=False,
        voxel_source="override",
        object_seed=seed,
    )
    manifest["negative_reference"] = True
    manifest["failure_mode_confirmed"] = failure_mode_confirmed
    write_analysis_manifest_json(manifest, out_dir / "manifest.json")

    (out_dir / "README.md").write_text(
        "\n".join(
            [
                "# Synthetic Touching Vesicles — Negative Reference",
                "",
                "Two touching vesicles in a 5-slice stack (large r=12 µm at x=30, small r=8 µm at x=48).",
                "Circle seed is on the large vesicle only.",
                "",
                "This run documents an **expected failure mode** for threshold-only vesicle tracking:",
                "the seed does not change the merged mesh compared with the unseeded run.",
                "",
                "Run (fast, threshold only):",
                "",
                "```powershell",
                "python scripts/validate_synthetic_touching.py",
                "```",
                "",
                "Optional Active Surfaces comparison (slow):",
                "",
                "```powershell",
                "python scripts/validate_synthetic_touching.py --with-active_surfaces",
                "```",
                "",
                f"- Threshold-only mesh volume: {threshold_only_vol:.1f} µm³",
                f"- Threshold seeded mesh volume: {threshold_mesh_vol:.1f} µm³",
                f"- Failure mode confirmed: `{failure_mode_confirmed}`",
                "",
                "Use ROI crop, polygon seed, or Active Surfaces when objects touch.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))
    return 0 if failure_mode_confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())