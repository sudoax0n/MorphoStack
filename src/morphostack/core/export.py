"""Export helpers for analysis results."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from math import sqrt
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
    "deformation_index",
    "extent",
    "equivalent_diameter_um",
    "solidity",
    "mesh_surface_area_um2",
    "mesh_volume_um3",
    "mesh_equivalent_sphere_diameter_um",
    "mesh_sphericity",
)

SUMMARY_METRICS = (
    "area_um2",
    "perimeter_um",
    "circularity",
    "bbox_width_um",
    "bbox_height_um",
    "aspect_ratio",
    "elongation",
    "deformation_index",
    "extent",
    "equivalent_diameter_um",
    "solidity",
)

BATCH_SUMMARY_COLUMNS = (
    "source_path",
    "status",
    "error_message",
    "profile",
    "threshold",
    "frame_count",
    "valid_frame_count",
    "valid_fraction",
    "mesh_surface_area_um2",
    "mesh_volume_um3",
    "mesh_equivalent_sphere_diameter_um",
    "mesh_sphericity",
    "warning_codes",
    *tuple(f"{metric}_{stat}" for metric in SUMMARY_METRICS for stat in ("mean", "min", "max", "std")),
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
                "deformation_index": metrics.deformation_index if metrics else 0.0,
                "extent": metrics.extent if metrics else 0.0,
                "equivalent_diameter_um": metrics.equivalent_diameter_um if metrics else 0.0,
                "solidity": metrics.solidity if metrics else 0.0,
                "mesh_surface_area_um2": mesh.surface_area_um2 if mesh else 0.0,
                "mesh_volume_um3": mesh.volume_um3 if mesh else 0.0,
                "mesh_equivalent_sphere_diameter_um": mesh.equivalent_sphere_diameter_um if mesh else 0.0,
                "mesh_sphericity": mesh.sphericity if mesh else 0.0,
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


def analysis_summary(analysis: StackAnalysis) -> dict[str, object]:
    metric_values: dict[str, list[float]] = {name: [] for name in SUMMARY_METRICS}
    for frame in analysis.valid_frames:
        metrics = frame.metrics
        if metrics is None:
            continue
        metric_values["area_um2"].append(metrics.area_um2)
        metric_values["perimeter_um"].append(metrics.perimeter_um)
        metric_values["circularity"].append(metrics.circularity)
        metric_values["bbox_width_um"].append(metrics.bbox_width_um)
        metric_values["bbox_height_um"].append(metrics.bbox_height_um)
        metric_values["aspect_ratio"].append(metrics.aspect_ratio)
        metric_values["elongation"].append(metrics.elongation)
        metric_values["deformation_index"].append(metrics.deformation_index)
        metric_values["extent"].append(metrics.extent)
        metric_values["equivalent_diameter_um"].append(metrics.equivalent_diameter_um)
        metric_values["solidity"].append(metrics.solidity)

    frame_count = len(analysis.frames)
    valid_frame_count = len(analysis.valid_frames)
    return {
        "frame_count": frame_count,
        "valid_frame_count": valid_frame_count,
        "valid_fraction": valid_frame_count / frame_count if frame_count else 0.0,
        "metrics": {
            name: summarize_values(values)
            for name, values in metric_values.items()
            if values
        },
    }


def summarize_values(values: list[float]) -> dict[str, float]:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {
        "mean": mean,
        "min": min(values),
        "max": max(values),
        "std": sqrt(variance),
    }


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
            "equivalent_sphere_diameter_um": analysis.mesh.equivalent_sphere_diameter_um,
            "sphericity": analysis.mesh.sphericity,
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
        "summary": analysis_summary(analysis),
        "warnings": analysis_warnings(analysis),
        "columns": list(CSV_COLUMNS),
    }


def analysis_summary_row(
    analysis: StackAnalysis,
    *,
    source_path: str,
    threshold: float | list[float] | tuple[float, ...],
) -> dict[str, object]:
    summary = analysis_summary(analysis)
    metrics = summary["metrics"]
    row: dict[str, object] = {
        "source_path": source_path,
        "status": "ok",
        "error_message": "",
        "profile": analysis.profile,
        "threshold": threshold,
        "frame_count": summary["frame_count"],
        "valid_frame_count": summary["valid_frame_count"],
        "valid_fraction": summary["valid_fraction"],
        "mesh_surface_area_um2": analysis.mesh.surface_area_um2 if analysis.mesh else 0.0,
        "mesh_volume_um3": analysis.mesh.volume_um3 if analysis.mesh else 0.0,
        "mesh_equivalent_sphere_diameter_um": analysis.mesh.equivalent_sphere_diameter_um if analysis.mesh else 0.0,
        "mesh_sphericity": analysis.mesh.sphericity if analysis.mesh else 0.0,
        "warning_codes": ";".join(str(warning["code"]) for warning in analysis_warnings(analysis)),
    }
    if isinstance(metrics, dict):
        for metric in SUMMARY_METRICS:
            values = metrics.get(metric)
            if isinstance(values, dict):
                for stat in ("mean", "min", "max", "std"):
                    row[f"{metric}_{stat}"] = values[stat]
    return {column: row.get(column, "") for column in BATCH_SUMMARY_COLUMNS}


def failed_analysis_summary_row(source_path: str, error_message: str) -> dict[str, object]:
    row = {
        "source_path": source_path,
        "status": "error",
        "error_message": error_message,
    }
    return {column: row.get(column, "") for column in BATCH_SUMMARY_COLUMNS}


def write_batch_summary_csv(rows: list[dict[str, object]], destination: str | Path | TextIO) -> None:
    close_after = False
    if hasattr(destination, "write"):
        handle = destination
    else:
        handle = Path(destination).open("w", newline="", encoding="utf-8")
        close_after = True

    try:
        writer = csv.DictWriter(handle, fieldnames=BATCH_SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if close_after:
            handle.close()


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
