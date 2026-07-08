"""Export helpers for analysis results."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from typing import TextIO

from morphostack import __version__
from morphostack.core.pipeline import (
    ObjectSeed,
    StackAnalysis,
    TrackingDiagnostics,
    object_seed_payload,
    tracking_diagnostics_payload,
)

CSV_COLUMNS = (
    "frame_index",
    "threshold",
    "profile",
    "method",
    "excluded",
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
    "source_sha256",
    "status",
    "error_message",
    "profile",
    "threshold",
    "voxel_source",
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
        excluded = frame.frame_index in analysis.excluded_frames
        rows.append(
            {
                "frame_index": frame.frame_index,
                "threshold": frame.threshold,
                "profile": frame.profile,
                "method": frame.preview.method,
                "excluded": excluded,
                "has_contour": metrics is not None and not excluded,
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
    if analysis.excluded_frames:
        warnings.append(
            {
                "code": "excluded_frames",
                "severity": "info",
                "message": (
                    f"{len(analysis.excluded_frames)} frame(s) excluded from metrics summary and 3D mesh."
                ),
                "frame_indices": sorted(analysis.excluded_frames),
            }
        )
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


def object_tracking_warnings(diagnostics: TrackingDiagnostics | None) -> list[dict[str, object]]:
    if diagnostics is None or not diagnostics.records:
        return []

    warnings: list[dict[str, object]] = []
    lost_count = diagnostics.lost_frame_count
    frame_count = len(diagnostics.records)
    if frame_count > 0 and lost_count > 0:
        lost_fraction = diagnostics.lost_fraction
        if lost_fraction >= 0.25:
            warnings.append(
                {
                    "code": "tracking_lost_many_frames",
                    "severity": "warning",
                    "message": (
                        f"Object tracking was lost on {lost_count} of {frame_count} frames "
                        f"({lost_fraction:.0%}). Metrics may mix frames or omit slices."
                    ),
                    "lost_frame_count": lost_count,
                    "frame_count": frame_count,
                }
            )
        else:
            warnings.append(
                {
                    "code": "tracking_lost_some_frames",
                    "severity": "info",
                    "message": f"Object tracking was lost on {lost_count} of {frame_count} frames.",
                    "lost_frame_count": lost_count,
                    "frame_count": frame_count,
                }
            )

    boundary_frames = [record.frame_index for record in diagnostics.records if record.touches_roi_boundary]
    if boundary_frames:
        warnings.append(
            {
                "code": "roi_boundary_touch",
                "severity": "warning",
                "message": (
                    "Selected component touches the ROI or crop boundary on "
                    f"{len(boundary_frames)} frame(s); area may be clipped."
                ),
                "frame_indices": boundary_frames,
            }
        )

    merge_frames = [record.frame_index for record in diagnostics.records if record.likely_neighbor_merge]
    if merge_frames:
        warnings.append(
            {
                "code": "likely_neighbor_merge",
                "severity": "warning",
                "message": (
                    "Tracked component area grew sharply on "
                    f"{len(merge_frames)} frame(s); neighbors may have merged."
                ),
                "frame_indices": merge_frames,
            }
        )
    return warnings


def analysis_run_warnings(analysis: StackAnalysis, *, voxel_source: str = "unknown") -> list[dict[str, object]]:
    warnings = analysis_warnings(analysis)
    warnings.extend(object_tracking_warnings(analysis.tracking))
    if voxel_source == "default":
        warnings.append(
            {
                "code": "default_voxel_size",
                "severity": "warning",
                "message": "Voxel spacing came from MorphoStack defaults. Physical units should be treated as uncalibrated.",
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
    source_sha256: str | None = None,
    roi: dict[str, int] | None = None,
    z_range: dict[str, int] | None = None,
    include_mesh: bool = False,
    prefer_opencv: bool = True,
    voxel_source: str = "unknown",
    object_seed: ObjectSeed | None = None,
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
        "source_sha256": source_sha256,
        "profile": analysis.profile,
        "threshold": threshold,
        "roi": roi,
        "z_range": z_range,
        "include_mesh": include_mesh,
        "prefer_opencv": prefer_opencv,
        "voxel_size": {
            "x_um": analysis.voxel_size.x_um,
            "y_um": analysis.voxel_size.y_um,
            "z_um": analysis.voxel_size.z_um,
        },
        "voxel_source": voxel_source,
        "frame_count": len(analysis.frames),
        "valid_frame_count": len(analysis.valid_frames),
        "excluded_frames": sorted(analysis.excluded_frames),
        "excluded_frame_count": len(analysis.excluded_frames),
        "mesh": mesh,
        "summary": analysis_summary(analysis),
        "warnings": analysis_run_warnings(analysis, voxel_source=voxel_source),
        "object_seed": object_seed_payload(object_seed),
        "tracking": tracking_diagnostics_payload(analysis.tracking),
        "columns": list(CSV_COLUMNS),
    }


def analysis_summary_row(
    analysis: StackAnalysis,
    *,
    source_path: str,
    threshold: float | list[float] | tuple[float, ...],
    source_sha256: str | None = None,
    voxel_source: str = "unknown",
) -> dict[str, object]:
    summary = analysis_summary(analysis)
    metrics = summary["metrics"]
    row: dict[str, object] = {
        "source_path": source_path,
        "source_sha256": source_sha256 or "",
        "status": "ok",
        "error_message": "",
        "profile": analysis.profile,
        "threshold": threshold,
        "voxel_source": voxel_source,
        "frame_count": summary["frame_count"],
        "valid_frame_count": summary["valid_frame_count"],
        "valid_fraction": summary["valid_fraction"],
        "mesh_surface_area_um2": analysis.mesh.surface_area_um2 if analysis.mesh else 0.0,
        "mesh_volume_um3": analysis.mesh.volume_um3 if analysis.mesh else 0.0,
        "mesh_equivalent_sphere_diameter_um": analysis.mesh.equivalent_sphere_diameter_um if analysis.mesh else 0.0,
        "mesh_sphericity": analysis.mesh.sphericity if analysis.mesh else 0.0,
        "warning_codes": ";".join(str(warning["code"]) for warning in analysis_run_warnings(analysis, voxel_source=voxel_source)),
    }
    if isinstance(metrics, dict):
        for metric in SUMMARY_METRICS:
            values = metrics.get(metric)
            if isinstance(values, dict):
                for stat in ("mean", "min", "max", "std"):
                    row[f"{metric}_{stat}"] = values[stat]
    return {column: row.get(column, "") for column in BATCH_SUMMARY_COLUMNS}


def failed_analysis_summary_row(
    source_path: str,
    error_message: str,
    *,
    source_sha256: str | None = None,
) -> dict[str, object]:
    row = {
        "source_path": source_path,
        "source_sha256": source_sha256 or "",
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


def analysis_report_markdown(
    analysis: StackAnalysis,
    *,
    source_path: str,
    threshold: float | list[float] | tuple[float, ...],
    source_sha256: str | None = None,
    roi: dict[str, int] | None = None,
    z_range: dict[str, int] | None = None,
    include_mesh: bool = False,
    prefer_opencv: bool = True,
    voxel_source: str = "unknown",
    object_seed: ObjectSeed | None = None,
    row_limit: int = 10,
) -> str:
    summary = analysis_summary(analysis)
    warnings = analysis_run_warnings(analysis, voxel_source=voxel_source)
    metrics = summary["metrics"]
    lines = [
        "# MorphoStack Analysis Report",
        "",
        "## Run Settings",
        "",
        f"- Source: `{source_path}`",
        f"- Source SHA-256: `{source_sha256 if source_sha256 is not None else 'not recorded'}`",
        f"- MorphoStack version: `{__version__}`",
        f"- Profile: `{analysis.profile}`",
        f"- Threshold: `{threshold}`",
        f"- ROI: `{roi if roi is not None else 'full stack'}`",
        f"- Z range: `{z_range if z_range is not None else 'full stack'}`",
        f"- Include mesh: `{include_mesh}`",
        f"- Prefer OpenCV contours: `{prefer_opencv}`",
        f"- Voxel source: `{voxel_source}`",
        (
            "- Voxel size: "
            f"x={format_report_number(analysis.voxel_size.x_um)} um, "
            f"y={format_report_number(analysis.voxel_size.y_um)} um, "
            f"z={format_report_number(analysis.voxel_size.z_um)} um"
        ),
        "",
    ]
    if object_seed is not None:
        seed_payload = object_seed_payload(object_seed)
        lines.extend(
            [
                "## Object Selection",
                "",
                f"- Seed frame: `{seed_payload['frame_index']}`",
                f"- Seed center: `({format_report_number(seed_payload['x'])}, {format_report_number(seed_payload['y'])})`",
                f"- Seed radius: `{format_report_number(seed_payload['radius'])}` px",
                f"- Seed type: `{seed_payload['type']}`",
                "",
            ]
        )
    if analysis.tracking is not None:
        lines.extend(
            [
                "## Tracking Diagnostics",
                "",
                f"- Tracked frames: {analysis.tracking.lost_frame_count} lost of {len(analysis.tracking.records)} total",
                "",
            ]
        )
    lines.extend(
        [
            "## Frame Summary",
            "",
            f"- Frames: {summary['frame_count']}",
            f"- Valid frames: {summary['valid_frame_count']}",
            f"- Valid fraction: {format_report_number(summary['valid_fraction'])}",
            f"- Excluded frames: {sorted(analysis.excluded_frames) if analysis.excluded_frames else 'none'}",
            "",
        ]
    )

    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(
                f"- `{warning['code']}` ({warning['severity']}): {warning['message']}"
            )
        lines.append("")

    if isinstance(metrics, dict) and metrics:
        lines.extend(
            [
                "## Metric Summary",
                "",
                "| Metric | Mean | Min | Max | Std |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for metric in SUMMARY_METRICS:
            values = metrics.get(metric)
            if isinstance(values, dict):
                lines.append(
                    "| "
                    f"{metric} | "
                    f"{format_report_number(values['mean'])} | "
                    f"{format_report_number(values['min'])} | "
                    f"{format_report_number(values['max'])} | "
                    f"{format_report_number(values['std'])} |"
                )
        lines.append("")

    if analysis.mesh:
        lines.extend(
            [
                "## Mesh Summary",
                "",
                f"- Surface area: {format_report_number(analysis.mesh.surface_area_um2)} um^2",
                f"- Volume: {format_report_number(analysis.mesh.volume_um3)} um^3",
                f"- Equivalent sphere diameter: {format_report_number(analysis.mesh.equivalent_sphere_diameter_um)} um",
                f"- Sphericity: {format_report_number(analysis.mesh.sphericity)}",
                "",
            ]
        )

    rows = analysis_rows(analysis)[: max(row_limit, 0)]
    if rows:
        lines.extend(
            [
                f"## First {len(rows)} Frame Rows",
                "",
                "| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |",
                "| ---: | :---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in rows:
            lines.append(
                "| "
                f"{row['frame_index']} | "
                f"{'yes' if row['has_contour'] else 'no'} | "
                f"{format_report_number(row['area_um2'])} | "
                f"{format_report_number(row['perimeter_um'])} | "
                f"{format_report_number(row['circularity'])} | "
                f"{format_report_number(row['deformation_index'])} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_analysis_report_markdown(
    analysis: StackAnalysis,
    destination: str | Path | TextIO,
    **kwargs,
) -> None:
    close_after = False
    if hasattr(destination, "write"):
        handle = destination
    else:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", encoding="utf-8")
        close_after = True

    try:
        handle.write(analysis_report_markdown(analysis, **kwargs))
    finally:
        if close_after:
            handle.close()


def format_report_number(value: object) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


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
