"""Export helpers for analysis results."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TextIO

from morphostack.core.pipeline import StackAnalysis

CSV_COLUMNS = (
    "frame_index",
    "threshold",
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
                "equivalent_diameter_um": metrics.equivalent_diameter_um if metrics else 0.0,
                "solidity": metrics.solidity if metrics else 0.0,
                "mesh_surface_area_um2": mesh.surface_area_um2 if mesh else 0.0,
                "mesh_volume_um3": mesh.volume_um3 if mesh else 0.0,
            }
        )
    return rows


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
