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
from morphostack.core.rbc_models import CalibrationAssessment
from morphostack.core.rbc_serialize import rbc_envelope_payload

CSV_COLUMNS = (
    "frame_index",
    # Legacy: effective intensity gate when applicable; empty when N/A (polar/unavailable).
    "threshold",
    "requested_threshold",
    "effective_threshold",
    "threshold_semantics",
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
    "skel_ok",
    "skel_perimeter_px",
    "skel_perimeter_um",
    "mesh_surface_area_um2",
    "mesh_volume_um3",
    "mesh_equivalent_sphere_diameter_um",
    "mesh_sphericity",
    "slice_integrated_volume_um3",
    "mesh_slice_volume_relative_difference",
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
    "slice_integrated_volume_um3",
    "mesh_slice_volume_relative_difference",
    "warning_codes",
    *tuple(f"{metric}_{stat}" for metric in SUMMARY_METRICS for stat in ("mean", "min", "max", "std")),
)


VOLUME_CROSSCHECK_WARNING_FRACTION = 0.05


def slice_volume_relative_difference(analysis: StackAnalysis) -> float | None:
    """Return the fractional disagreement between mesh and slice-integrated volume."""

    slice_volume = analysis.slice_volume
    if analysis.mesh is None or slice_volume is None or slice_volume.volume_um3 is None:
        return None
    mesh_volume = float(analysis.mesh.volume_um3)
    integrated_volume = float(slice_volume.volume_um3)
    denominator = (abs(mesh_volume) + abs(integrated_volume)) / 2.0
    if denominator <= 0.0:
        return None
    return abs(mesh_volume - integrated_volume) / denominator


def slice_volume_payload(analysis: StackAnalysis) -> dict[str, object] | None:
    """Return the auditable slice-area volume cross-check for API/report use."""

    measurement = analysis.slice_volume
    if measurement is None:
        return None
    return {
        "method": "trapezoidal_slice_area_integration",
        "volume_um3": measurement.volume_um3,
        "partial_volume_um3": measurement.partial_volume_um3,
        "relative_difference_from_mesh": slice_volume_relative_difference(analysis),
        "sampled_slice_count": measurement.sampled_slice_count,
        "valid_slice_indices": list(measurement.valid_slice_indices),
        "internal_missing_slice_indices": list(measurement.internal_missing_slice_indices),
        "coverage_fraction": measurement.coverage_fraction,
        "z_step_um": measurement.z_step_um,
        "has_internal_gaps": measurement.has_internal_gaps,
        "has_observed_start_cap": measurement.has_observed_start_cap,
        "has_observed_end_cap": measurement.has_observed_end_cap,
        "touches_stack_boundary": measurement.touches_stack_boundary,
    }


def analysis_rows(analysis: StackAnalysis) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    slice_volume = analysis.slice_volume
    integrated_volume = slice_volume.volume_um3 if slice_volume is not None else None
    volume_difference = slice_volume_relative_difference(analysis)
    # RBC authority-safe mesh columns: blank when 3D not validated.
    rbc_env = rbc_envelope_payload(analysis)
    rbc_mesh_allowed = False
    if rbc_env is None:
        rbc_mesh_allowed = True  # non-RBC uses legacy mesh fields
    else:
        measured = rbc_env.get("measured") if isinstance(rbc_env, dict) else None
        if isinstance(measured, dict) and measured.get("volume_um3") is not None:
            rbc_mesh_allowed = True
    for frame in analysis.frames:
        metrics = frame.metrics
        mesh = analysis.mesh if rbc_mesh_allowed else None
        excluded = frame.frame_index in analysis.excluded_frames
        def _csv_num(v: float | None) -> float | str:
            if v is None:
                return ""
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return ""
            if fv != fv:  # NaN
                return ""
            return fv

        req = getattr(frame, "requested_threshold", None)
        eff = getattr(frame, "effective_threshold", None)
        sem = getattr(frame, "threshold_semantics", None) or "global_intensity"
        legacy = frame.threshold
        # For RBC, deformation_index is legacy bbox-only; still exported under the
        # same column name for CSV compatibility but should not be primary report.
        di = metrics.deformation_index if metrics else 0.0
        rows.append(
            {
                "frame_index": frame.frame_index,
                "threshold": _csv_num(legacy if legacy is not None else None),
                "requested_threshold": _csv_num(req if req is not None else legacy),
                "effective_threshold": _csv_num(eff),
                "threshold_semantics": sem,
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
                "deformation_index": di,
                "extent": metrics.extent if metrics else 0.0,
                "equivalent_diameter_um": metrics.equivalent_diameter_um if metrics else 0.0,
                "solidity": metrics.solidity if metrics else 0.0,
                "skel_ok": bool(frame.skel_ok),
                "skel_perimeter_px": frame.skel_perimeter_px if frame.skel_perimeter_px is not None else 0.0,
                "skel_perimeter_um": frame.skel_perimeter_um if frame.skel_perimeter_um is not None else 0.0,
                "mesh_surface_area_um2": mesh.surface_area_um2 if mesh else 0.0,
                "mesh_volume_um3": mesh.volume_um3 if mesh else 0.0,
                "mesh_equivalent_sphere_diameter_um": mesh.equivalent_sphere_diameter_um if mesh else 0.0,
                "mesh_sphericity": mesh.sphericity if mesh else 0.0,
                "slice_integrated_volume_um3": integrated_volume,
                "mesh_slice_volume_relative_difference": volume_difference,
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

    slice_volume = analysis.slice_volume
    if slice_volume is not None:
        if slice_volume.has_internal_gaps:
            warnings.append(
                {
                    "code": "slice_volume_internal_gap",
                    "severity": "warning",
                    "message": "Slice-integrated volume was withheld because contour slices are missing inside the object; no gap interpolation was performed.",
                    "frame_indices": list(slice_volume.internal_missing_slice_indices),
                }
            )
        if slice_volume.touches_stack_boundary:
            warnings.append(
                {
                    "code": "slice_volume_stack_boundary",
                    "severity": "warning",
                    "message": "The segmented object reaches the selected stack boundary; slice-integrated volume may omit a pole or cap.",
                }
            )
        if slice_volume.sampled_slice_count < 8:
            warnings.append(
                {
                    "code": "sparse_z_sampling",
                    "severity": "warning",
                    "message": f"Only {slice_volume.sampled_slice_count} segmented Z slices support the 3D measurement; use at least 8-10 slices for a stronger volume cross-check.",
                }
            )
        volume_difference = slice_volume_relative_difference(analysis)
        if volume_difference is not None and volume_difference > VOLUME_CROSSCHECK_WARNING_FRACTION:
            warnings.append(
                {
                    "code": "mesh_slice_volume_disagreement",
                    "severity": "warning",
                    "message": f"3D mesh volume and slice-integrated volume differ by {volume_difference:.1%}; review calibration, stack coverage, and contours.",
                    "relative_difference": volume_difference,
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
                    "Selected component touches the ROI or full-FOV crop boundary on "
                    f"{len(boundary_frames)} frame(s); area may be clipped by the "
                    "analysis window (not the seed search disk)."
                ),
                "frame_indices": boundary_frames,
            }
        )

    seed_disk_frames = [
        record.frame_index for record in diagnostics.records if getattr(record, "touches_seed_disk", False)
    ]
    if seed_disk_frames:
        warnings.append(
            {
                "code": "seed_disk_clip",
                "severity": "info",
                "message": (
                    "Selected component reaches the seed/search disk boundary on "
                    f"{len(seed_disk_frames)} frame(s); the hard circle prior may be "
                    "clipping the membrane contour. This is distinct from ROI/FOV clipping."
                ),
                "frame_indices": seed_disk_frames,
            }
        )

    # Accepted frames with merge/contact suspicion (compat + explicit flag).
    merge_frames = [
        record.frame_index
        for record in diagnostics.records
        if record.likely_neighbor_merge or getattr(record, "merge_suspect", False)
    ]
    if merge_frames:
        warnings.append(
            {
                "code": "likely_neighbor_merge",
                "severity": "warning",
                "message": (
                    "Suspected neighbor contact or merge on "
                    f"{len(merge_frames)} accepted frame(s) (area jump and/or seeded "
                    "merge QC). This is a safety suspicion, not a confirmed biological "
                    "doublet. Metrics and mesh may be contaminated — review contours."
                ),
                "frame_indices": merge_frames,
            }
        )

    # Untracked frames where a suspected merge was rejected for safety.
    merge_rejected_frames = [
        record.frame_index
        for record in diagnostics.records
        if getattr(record, "merge_rejected", False)
        or getattr(record, "loss_reason", None) == "merge_rejected"
    ]
    if merge_rejected_frames:
        warnings.append(
            {
                "code": "merge_suspect_rejected",
                "severity": "warning",
                "message": (
                    "Suspected contact/merge was rejected for safety on "
                    f"{len(merge_rejected_frames)} frame(s); no contour was accepted. "
                    "This is not a confirmed two-vesicle biological call — re-seed, "
                    "tighten ROI, or inspect the stack manually."
                ),
                "frame_indices": merge_rejected_frames,
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
    # Seeded Standard path ignores the UI intensity slider for contours; tell the user.
    seeded_methods = {
        getattr(frame.preview, "method", "")
        for frame in analysis.frames
        if frame.contour is not None
    }
    if any(
        str(m).startswith("circle_seed") or str(m).startswith("polar")
        for m in seeded_methods
    ):
        warnings.append(
            {
                "code": "seeded_adaptive_threshold",
                "severity": "info",
                "message": (
                    "Seeded vesicle/RBC analysis uses per-slice adaptive local intensity "
                    "gates (or polar ridge paths) inside the seed disk — not the UI slider. "
                    "See requested_threshold, effective_threshold (null when N/A), and "
                    "threshold_semantics. Legacy field `threshold` equals the effective "
                    "gate when one was used, else null. Provisional fast preview still "
                    "uses the UI/global threshold and may disagree."
                ),
            }
        )
    rbc_env = rbc_envelope_payload(analysis)
    if rbc_env is not None:
        issues = rbc_env.get("qc_issues") if isinstance(rbc_env, dict) else None
        if isinstance(issues, list) and issues:
            warnings.append(
                {
                    "code": "rbc_qc",
                    "severity": "warning",
                    "message": (
                        f"RBC capability {rbc_env.get('capability')}, authority "
                        f"{rbc_env.get('authority')}: {', '.join(str(i) for i in issues)}"
                    ),
                    "qc_issues": list(issues),
                    "capability": rbc_env.get("capability"),
                    "authority": rbc_env.get("authority"),
                }
            )
        elif rbc_env.get("capability") == "PIXEL_PREVIEW":
            warnings.append(
                {
                    "code": "rbc_pixel_preview",
                    "severity": "warning",
                    "message": (
                        "RBC physical morphometry is withheld (PIXEL_PREVIEW). "
                        "Check calibration, seed, and stack completeness."
                    ),
                    "capability": rbc_env.get("capability"),
                    "authority": rbc_env.get("authority"),
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


def _seeded_adaptive_threshold_used(analysis: StackAnalysis, object_seed: ObjectSeed | None) -> bool:
    """True when frame thresholds are local adaptive gates, not the UI slider."""
    if object_seed is None:
        return False
    if analysis.profile not in ("vesicle", "rbc"):
        return False
    for frame in analysis.frames:
        method = getattr(frame.preview, "method", "") or ""
        if method.startswith("circle_seed") or method.startswith("polar"):
            return True
    return False


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
    calibration: CalibrationAssessment | None = None,
) -> dict[str, object]:
    mesh = None
    if analysis.mesh:
        mesh = {
            "surface_area_um2": analysis.mesh.surface_area_um2,
            "volume_um3": analysis.mesh.volume_um3,
            "equivalent_sphere_diameter_um": analysis.mesh.equivalent_sphere_diameter_um,
            "sphericity": analysis.mesh.sphericity,
        }
    # RBC: never present legacy mesh as measured when QC withheld 3D.
    rbc_payload = rbc_envelope_payload(analysis, calibration=calibration)
    if rbc_payload is not None:
        measured = rbc_payload.get("measured") if isinstance(rbc_payload, dict) else None
        measured_vol = None
        if isinstance(measured, dict):
            measured_vol = measured.get("volume_um3")
        if measured_vol is None:
            mesh = None
    seeded_adaptive = _seeded_adaptive_threshold_used(analysis, object_seed)
    # Run-level semantics: per-frame fields are authoritative for polar/unavailable.
    run_semantics = "seeded_adaptive_local" if seeded_adaptive else "global_intensity"
    return {
        "morphostack_version": __version__,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path,
        "source_sha256": source_sha256,
        "profile": analysis.profile,
        # Legacy run-level key: still the UI/CLI requested value for old clients.
        "threshold": threshold,
        "requested_threshold": threshold,
        "threshold_semantics": run_semantics,
        "threshold_contract_version": "1",
        "threshold_field_notes": {
            "threshold": (
                "Legacy compatibility. Manifest root: requested UI/CLI value only. "
                "On each CSV/API frame row: effective intensity gate when one produced "
                "the contour; null/empty when polar ridge or unavailable. "
                "Never treat root threshold as the seeded per-frame gate."
            ),
            "requested_threshold": (
                "UI/CLI request for this run (may be unused by seeded adaptive / polar)."
            ),
            "effective_threshold": (
                "Numeric only when an intensity gate produced that frame result; "
                "JSON null / CSV empty for polar_ridge or seeded_unavailable."
            ),
            "threshold_semantics": (
                "ui_starting_guess | display_global | provisional_global | "
                "global_intensity | seeded_adaptive_local | polar_ridge | seeded_unavailable"
            ),
            "threshold_suggestion": (
                "Optional full suggestion record (scope/domain/method); not authoritative "
                "for seeded exact contours."
            ),
        },
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
        "slice_volume": slice_volume_payload(analysis),
        "summary": analysis_summary(analysis),
        "warnings": analysis_run_warnings(analysis, voxel_source=voxel_source),
        "object_seed": object_seed_payload(object_seed),
        "tracking": tracking_diagnostics_payload(analysis.tracking),
        "columns": list(CSV_COLUMNS),
        "rbc": rbc_payload,
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
        "slice_integrated_volume_um3": analysis.slice_volume.volume_um3 if analysis.slice_volume and analysis.slice_volume.volume_um3 is not None else "",
        "mesh_slice_volume_relative_difference": slice_volume_relative_difference(analysis) if slice_volume_relative_difference(analysis) is not None else "",
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
        f"- Requested threshold (UI/CLI): `{threshold}`",
        f"- Threshold semantics (run): "
        f"`{'seeded_adaptive_local' if object_seed is not None and analysis.profile in ('vesicle', 'rbc') else 'global_intensity'}`",
        f"- Note: per-frame `effective_threshold` is the intensity gate when used; "
        f"polar/unavailable frames leave it empty. Legacy `threshold` column matches "
        f"effective when applicable.",
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
                f"- 3D mesh surface area: {format_report_number(analysis.mesh.surface_area_um2)} um^2",
                f"- 3D mesh volume: {format_report_number(analysis.mesh.volume_um3)} um^3",
                f"- Slice-integrated volume (trapezoidal): {format_report_number(analysis.slice_volume.volume_um3) if analysis.slice_volume and analysis.slice_volume.volume_um3 is not None else 'withheld (incomplete contour coverage)'} um^3",
                f"- Mesh/slice volume difference: {format_report_number(slice_volume_relative_difference(analysis) * 100.0) + '%' if slice_volume_relative_difference(analysis) is not None else 'not available'}",
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
