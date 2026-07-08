#!/usr/bin/env python3
"""Generate a synthetic ellipsoid stack and validate MorphoStack metrics against reference CSV."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from morphostack.core.export import write_analysis_csv, write_analysis_manifest_json, analysis_manifest
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import analyze_stack
from morphostack.core.validation import compare_metric_csv, format_validation_report


def build_ellipsoid_stack(
    *,
    shape: tuple[int, int, int] = (12, 50, 50),
    center: tuple[float, float, float] = (25.0, 25.0, 6.0),
    radii: tuple[float, float, float] = (8.0, 5.0, 5.0),
) -> np.ndarray:
    stack = np.zeros(shape, dtype=np.uint8)
    cz, cy, cx = center
    rz, ry, rx = radii
    for z in range(shape[0]):
        for y in range(shape[1]):
            for x in range(shape[2]):
                norm = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 + ((z - cz) / rz) ** 2
                if norm < 1.0:
                    stack[z, y, x] = 255
    return stack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=str(PROJECT_ROOT / "validation" / "runs" / "synthetic-ellipsoid"),
        help="Validation output directory.",
    )
    parser.add_argument("--tolerance", type=float, default=0.08, help="Numeric CSV tolerance.")
    parser.add_argument("--update-reference", action="store_true", help="Rewrite reference metrics.csv.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stack = build_ellipsoid_stack()
    voxel = VoxelSize(1.0, 1.0, 1.0)
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=voxel,
        include_mesh=True,
        prefer_opencv=False,
    )

    actual_csv = out_dir / "metrics.csv"
    reference_csv = out_dir / "reference-metrics.csv"
    write_analysis_csv(analysis, actual_csv)
    manifest = analysis_manifest(
        analysis,
        source_path="synthetic-ellipsoid",
        threshold=100,
        include_mesh=True,
        prefer_opencv=False,
        voxel_source="override",
    )
    write_analysis_manifest_json(manifest, out_dir / "manifest.json")
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                "# Synthetic Ellipsoid Validation",
                "",
                "Known-geometry ellipsoid stack (radii 8×5×5 µm, voxel 1×1×1 µm).",
                "",
                "Run:",
                "",
                "```powershell",
                "python scripts/validate_synthetic_ellipsoid.py",
                "```",
                "",
                "Expect lower sphericity than the sphere reference and stable mesh volume regression.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    if args.update_reference or not reference_csv.exists():
        reference_csv.write_text(actual_csv.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Reference metrics written: {reference_csv}")
        return 0

    report = compare_metric_csv(
        reference_csv,
        actual_csv,
        tolerance=args.tolerance,
        columns=["area_um2", "circularity", "mesh_volume_um3", "mesh_sphericity"],
    )
    print(format_validation_report(report))
    summary = {
        "passed": report.passed,
        "compared_rows": report.compared_rows,
        "compared_cells": report.compared_cells,
        "difference_count": len(report.differences),
    }
    (out_dir / "validation-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())