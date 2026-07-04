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
    bbox_width_um: float
    bbox_height_um: float
    aspect_ratio: float
    elongation: float
    extent: float
    equivalent_diameter_um: float
    solidity: float


def contour_metrics(points_xy: np.ndarray, voxel: VoxelSize) -> ContourMetrics:
    """Calculate polygon metrics for contour points in pixel coordinates."""

    pts = normalize_points(points_xy)
    if len(pts) < 3:
        raise ValueError("At least three contour points are required")

    area_px = polygon_area(pts)
    perimeter_px = polygon_perimeter(pts, x_scale=1.0, y_scale=1.0)
    scaled_pts = pts * np.array([voxel.x_um, voxel.y_um])
    area_um = polygon_area(scaled_pts)
    perimeter_um = polygon_perimeter(pts, x_scale=voxel.x_um, y_scale=voxel.y_um)
    circularity = 0.0
    if perimeter_um > 0:
        circularity = (4.0 * np.pi * area_um) / (perimeter_um**2)
    bbox_width_um, bbox_height_um = bounding_box_size(scaled_pts)
    aspect_ratio = 0.0
    elongation = 0.0
    if min(bbox_width_um, bbox_height_um) > 0:
        major = max(bbox_width_um, bbox_height_um)
        minor = min(bbox_width_um, bbox_height_um)
        aspect_ratio = major / minor
        elongation = 1.0 - (minor / major)
    bbox_area_um = bbox_width_um * bbox_height_um
    extent = area_um / bbox_area_um if bbox_area_um > 0 else 0.0
    equivalent_diameter_um = 0.0
    if area_um > 0:
        equivalent_diameter_um = float(np.sqrt((4.0 * area_um) / np.pi))
    hull_area_um = polygon_area(convex_hull(scaled_pts))
    solidity = area_um / hull_area_um if hull_area_um > 0 else 0.0

    return ContourMetrics(
        area_um2=area_um,
        perimeter_um=perimeter_um,
        circularity=circularity,
        area_px2=area_px,
        perimeter_px=perimeter_px,
        bbox_width_um=bbox_width_um,
        bbox_height_um=bbox_height_um,
        aspect_ratio=aspect_ratio,
        elongation=elongation,
        extent=extent,
        equivalent_diameter_um=equivalent_diameter_um,
        solidity=solidity,
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


def bounding_box_size(points_xy: np.ndarray) -> tuple[float, float]:
    pts = normalize_points(points_xy)
    xmin = float(np.min(pts[:, 0]))
    xmax = float(np.max(pts[:, 0]))
    ymin = float(np.min(pts[:, 1]))
    ymax = float(np.max(pts[:, 1]))
    return xmax - xmin, ymax - ymin


def convex_hull(points_xy: np.ndarray) -> np.ndarray:
    """Return the convex hull vertices using Andrew's monotonic chain algorithm."""

    pts = normalize_points(points_xy)
    unique = sorted({(float(x), float(y)) for x, y in pts})
    if len(unique) <= 1:
        return np.asarray(unique, dtype=np.float64)

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return np.asarray(lower[:-1] + upper[:-1], dtype=np.float64)


def cross(
    origin: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])
