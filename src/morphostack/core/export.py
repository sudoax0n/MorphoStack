"""Export helpers for analysis results."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from morphostack import __version__
from morphostack.core.pipeline import StackAnalysis

CSV_COLUMNS = (
    "frame_index",
    "threshold",
    "profile",
    "method",
    "has_contour",
    "area_px2",
    "perimeter_px",
    "area_um2",
    "perimeter_um",
    "circularity",
    "bbox_width_um",
    "bbox_height_um",
    "aspect_ratio",
    "elongation",
    "extent",
    "equivalent_diameter_um",
    "solidity",
    "mesh_surface_area_um2",
    "mesh_volume_um3",
)


def analysis_rows(analysis: StackAnalysis) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for frame in analysis.frames:
        metrics = frame.metrics
        mesh = analysis.mesh
        rows.append(
            {
                "frame_index": frame.frame_index,
                "threshold": frame.threshold,
                "profile": frame.profile,
                "method": frame.preview.method,
                "has_contour": metrics is not None,
                "area_px2": metrics.area_px2 if metrics else 0.0,
                "perimeter_px": metrics.perimeter_px if metrics else 0.0,
                "area_um2": metrics.area_um2 if metrics else 0.0,
                "perimeter_um": metrics.perimeter_um if metrics else 0.0,
                "circularity": metrics.circularity if metrics else 0.0,
                "bbox_width_um": metrics.bbox_width_um if metrics else 0.0,
                "bbox_height_um": metrics.bbox_height_um if metrics else 0.0,
                "aspect_ratio": metrics.aspect_ratio if metrics else 0.0,
                "elongation": metrics.elongation if metrics else 0.0,
                "extent": metrics.extent if metrics else 0.0,
                "equivalent_diameter_um": metrics.equivalent_diameter_um if metrics else 0.0,
                "solidity": metrics.solidity if metrics else 0.0,
                "mesh_surface_area_um2": mesh.surface_area_um2 if mesh else 0.0,
                "mesh_volume_um3": mesh.volume_um3 if mesh else 0.0,
            }
        )
    return rows


def analysis_warnings(analysis: StackAnalysis) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    frame_count = len(analysis.frames)
    valid_count = len(analysis.valid_frames)
    if frame_count == 0:
        warnings.append(
            {
                "code": "no_frames",
                "severity": "error",
                "message": "The analysis did not contain any frames.",
            }
        )
        return warnings

    if valid_count == 0:
        warnings.append(
            {
                "code": "no_valid_contours",
                "severity": "error",
                "message": "No frames produced a valid contour. Check threshold, ROI, and image contrast.",
            }
        )
    elif valid_count < frame_count:
        warnings.append(
            {
                "code": "partial_contours",
                "severity": "warning",
                "message": f"{frame_count - valid_count} of {frame_count} frames did not produce a valid contour.",
                "invalid_frame_count": frame_count - valid_count,
                "frame_count": frame_count,
            }
        )

    if analysis.mesh and (analysis.mesh.surface_area_um2 <= 0 or analysis.mesh.volume_um3 <= 0):
        warnings.append(
            {
                "code": "zero_mesh_measurement",
                "severity": "warning",
                "message": "3D mesh measurement returned zero surface area or volume.",
            }
        )
    return warnings


def analysis_manifest(
    analysis: StackAnalysis,
    *,
    source_path: str,
    threshold: float | list[float] | tuple[float, ...],
    roi: dict[str, int] | None = None,
    include_mesh: bool = False,
    prefer_opencv: bool = True,
) -> dict[str, object]:
    mesh = None
    if analysis.mesh:
        mesh = {
            "surface_area_um2": analysis.mesh.surface_area_um2,
            "volume_um3": analysis.mesh.volume_um3,
        }
    return {
        "morphostack_version": __version__,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path,
        "profile": analysis.profile,
        "threshold": threshold,
        "roi": roi,
        "include_mesh": include_mesh,
        "prefer_opencv": prefer_opencv,
        "voxel_size": {
            "x_um": analysis.voxel_size.x_um,
            "y_um": analysis.voxel_size.y_um,
            "z_um": analysis.voxel_size.z_um,
        },
        "frame_count": len(analysis.frames),
        "valid_frame_count": len(analysis.valid_frames),
        "mesh": mesh,
        "warnings": analysis_warnings(analysis),
        "columns": list(CSV_COLUMNS),
    }


def write_analysis_manifest_json(manifest: dict[str, object], destination: str | Path | TextIO) -> None:
    close_after = False
    if hasattr(destination, "write"):
        handle = destination
    else:
        handle = Path(destination).open("w", encoding="utf-8")
        close_after = True

    try:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    finally:
        if close_after:
            handle.close()


def write_analysis_csv(analysis: StackAnalysis, destination: str | Path | TextIO) -> None:
    close_after = False
    if hasattr(destination, "write"):
        handle = destination
    else:
        handle = Path(destination).open("w", newline="", encoding="utf-8")
        close_after = True

    try:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(analysis_rows(analysis))
    finally:
        if close_after:
            handle.close()
