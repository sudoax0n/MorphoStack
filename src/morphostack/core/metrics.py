"""Geometry metrics with explicit physical units."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from morphostack.core.models import VoxelSize


@dataclass(frozen=True)
class ContourMetrics:
    area_um2: float
    perimeter_um: float
    circularity: float
    area_px2: float
    perimeter_px: float


def contour_metrics(points_xy: np.ndarray, voxel: VoxelSize) -> ContourMetrics:
    """Calculate polygon metrics for contour points in pixel coordinates."""

    pts = normalize_points(points_xy)
    if len(pts) < 3:
        raise ValueError("At least three contour points are required")

    area_px = polygon_area(pts)
    perimeter_px = polygon_perimeter(pts, x_scale=1.0, y_scale=1.0)
    area_um = polygon_area(pts * np.array([voxel.x_um, voxel.y_um]))
    perimeter_um = polygon_perimeter(pts, x_scale=voxel.x_um, y_scale=voxel.y_um)
    circularity = 0.0
    if perimeter_um > 0:
        circularity = (4.0 * np.pi * area_um) / (perimeter_um**2)

    return ContourMetrics(
        area_um2=area_um,
        perimeter_um=perimeter_um,
        circularity=circularity,
        area_px2=area_px,
        perimeter_px=perimeter_px,
    )


def normalize_points(points_xy: np.ndarray) -> np.ndarray:
    pts = np.asarray(points_xy, dtype=np.float64)
    if pts.ndim == 3 and pts.shape[1] == 1:
        pts = pts[:, 0, :]
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("Contour points must have shape (n, 2) or (n, 1, 2)")
    return pts


def polygon_area(points_xy: np.ndarray) -> float:
    pts = normalize_points(points_xy)
    x = pts[:, 0]
    y = pts[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def polygon_perimeter(points_xy: np.ndarray, *, x_scale: float, y_scale: float) -> float:
    pts = normalize_points(points_xy)
    scaled = pts * np.array([x_scale, y_scale])
    deltas = np.roll(scaled, -1, axis=0) - scaled
    return float(np.sum(np.linalg.norm(deltas, axis=1)))

