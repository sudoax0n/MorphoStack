"""Threshold sweep helpers for comparing segmentation settings."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import numpy as np

from morphostack.core.export import SUMMARY_METRICS, analysis_run_warnings, analysis_summary
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import RectROI, StackAnalysis, ZRange, analyze_stack
from morphostack.core.profiles import DEFAULT_PROFILE

SWEEP_COLUMNS = (
    "threshold",
    "profile",
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


@dataclass(frozen=True)
class ThresholdSweepResult:
    threshold: float
    analysis: StackAnalysis
    warnings: tuple[dict[str, object], ...]


def threshold_values(start: float, stop: float, step: float) -> tuple[float, ...]:
    if step <= 0:
        raise ValueError("threshold sweep step must be greater than zero")
    if stop < start:
        raise ValueError("threshold sweep stop must be greater than or equal to start")

    values: list[float] = []
    current = float(start)
    stop_value = float(stop)
    tolerance = abs(step) * 1e-9
    while current <= stop_value + tolerance:
        values.append(round(current, 10))
        current += step
    if values and values[-1] > stop_value:
        values[-1] = stop_value
    return tuple(values)


def threshold_sweep(
    stack: np.ndarray,
    *,
    thresholds: tuple[float, ...] | list[float],
    voxel_size: VoxelSize,
    roi: RectROI | None = None,
    z_range: ZRange | None = None,
    profile: str | None = DEFAULT_PROFILE,
    prefer_opencv: bool = True,
    include_mesh: bool = False,
    voxel_source: str = "unknown",
    object_seed=None,
    source_path=None,
    calibration=None,
) -> tuple[ThresholdSweepResult, ...]:
    if not thresholds:
        raise ValueError("threshold sweep requires at least one threshold")

    results: list[ThresholdSweepResult] = []
    for threshold in thresholds:
        analysis = analyze_stack(
            stack,
            thresholds=float(threshold),
            voxel_size=voxel_size,
            roi=roi,
            z_range=z_range,
            profile=profile,
            prefer_opencv=prefer_opencv,
            include_mesh=include_mesh,
            object_seed=object_seed,
            source_path=source_path,
            calibration=calibration,
        )
        results.append(
            ThresholdSweepResult(
                threshold=float(threshold),
                analysis=analysis,
                warnings=tuple(analysis_run_warnings(analysis, voxel_source=voxel_source)),
            )
        )
    return tuple(results)


def threshold_sweep_rows(results: tuple[ThresholdSweepResult, ...] | list[ThresholdSweepResult]) -> list[dict[str, object]]:
    return [threshold_sweep_row(result) for result in results]


def threshold_sweep_row(result: ThresholdSweepResult) -> dict[str, object]:
    analysis = result.analysis
    summary = analysis_summary(analysis)
    metrics = summary["metrics"]
    row: dict[str, object] = {
        "threshold": result.threshold,
        "profile": analysis.profile,
        "frame_count": summary["frame_count"],
        "valid_frame_count": summary["valid_frame_count"],
        "valid_fraction": summary["valid_fraction"],
        "mesh_surface_area_um2": analysis.mesh.surface_area_um2 if analysis.mesh else 0.0,
        "mesh_volume_um3": analysis.mesh.volume_um3 if analysis.mesh else 0.0,
        "mesh_equivalent_sphere_diameter_um": analysis.mesh.equivalent_sphere_diameter_um if analysis.mesh else 0.0,
        "mesh_sphericity": analysis.mesh.sphericity if analysis.mesh else 0.0,
        "warning_codes": ";".join(str(warning["code"]) for warning in result.warnings),
    }
    if isinstance(metrics, dict):
        for metric in SUMMARY_METRICS:
            values = metrics.get(metric)
            if isinstance(values, dict):
                for stat in ("mean", "min", "max", "std"):
                    row[f"{metric}_{stat}"] = values[stat]
    return {column: row.get(column, "") for column in SWEEP_COLUMNS}


def best_sweep_result(results: tuple[ThresholdSweepResult, ...] | list[ThresholdSweepResult]) -> ThresholdSweepResult | None:
    if not results:
        return None
    return max(
        results,
        key=lambda result: (
            len(result.analysis.valid_frames) / len(result.analysis.frames) if result.analysis.frames else 0.0,
            -abs(result.threshold),
        ),
    )


def write_threshold_sweep_csv(
    results: tuple[ThresholdSweepResult, ...] | list[ThresholdSweepResult],
    destination: str | Path | TextIO,
) -> None:
    close_after = False
    if hasattr(destination, "write"):
        handle = destination
    else:
        handle = Path(destination).open("w", newline="", encoding="utf-8")
        close_after = True

    try:
        writer = csv.DictWriter(handle, fieldnames=SWEEP_COLUMNS)
        writer.writeheader()
        writer.writerows(threshold_sweep_rows(results))
    finally:
        if close_after:
            handle.close()
