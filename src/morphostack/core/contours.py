"""Contour extraction and smoothing helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from morphostack.core.metrics import normalize_points, polygon_area, polygon_perimeter


@dataclass(frozen=True)
class SegmentationPreview:
    threshold: float
    contour: np.ndarray | None
    area_px2: float
    perimeter_px: float
    circularity: float
    method: str = "fallback"


def segmentation_preview(
    image: np.ndarray,
    threshold: float,
    *,
    prefer_opencv: bool = True,
) -> SegmentationPreview:
    """Threshold an image and return the largest contour-like boundary."""

    mask = np.asarray(image) >= threshold
    contour = None
    method = "fallback"
    if prefer_opencv:
        contour = largest_opencv_contour(mask)
        if contour is not None:
            method = "opencv"

    if contour is None:
        contour = largest_component_boundary(mask)

    if contour is None:
        return SegmentationPreview(threshold, None, 0.0, 0.0, 0.0, method)

    area = polygon_area(contour)
    perimeter = polygon_perimeter(contour, x_scale=1.0, y_scale=1.0)
    circularity = 0.0
    if perimeter > 0:
        circularity = float((4.0 * np.pi * area) / (perimeter**2))
    return SegmentationPreview(threshold, contour, area, perimeter, circularity, method)


def largest_opencv_contour(mask: np.ndarray) -> np.ndarray | None:
    """Return the largest external contour using OpenCV when installed."""

    try:
        import cv2
    except Exception:
        return None

    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("largest_opencv_contour expects a 2D mask")

    binary = (arr.astype(np.uint8)) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=lambda contour: float(cv2.contourArea(contour)))
    if largest is None or len(largest) < 3:
        return None
    return normalize_points(largest)


def largest_component_boundary(mask: np.ndarray) -> np.ndarray | None:
    """Return a rectangular boundary around the largest connected foreground component."""

    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("largest_component_boundary expects a 2D mask")

    component = largest_connected_component(arr)
    if component is None:
        return None

    ys, xs = np.where(component)
    xmin = float(xs.min())
    xmax = float(xs.max() + 1)
    ymin = float(ys.min())
    ymax = float(ys.max() + 1)
    return np.array(
        [
            [xmin, ymin],
            [xmax, ymin],
            [xmax, ymax],
            [xmin, ymax],
        ],
        dtype=np.float64,
    )


def largest_connected_component(mask: np.ndarray) -> np.ndarray | None:
    """Return the largest 4-connected foreground component as a boolean mask."""

    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("largest_connected_component expects a 2D mask")
    height, width = arr.shape
    visited = np.zeros_like(arr, dtype=bool)
    best_points: list[tuple[int, int]] = []

    for y in range(height):
        for x in range(width):
            if not arr[y, x] or visited[y, x]:
                continue
            points = flood_component(arr, visited, y, x)
            if len(points) > len(best_points):
                best_points = points

    if not best_points:
        return None

    component = np.zeros_like(arr, dtype=bool)
    ys, xs = zip(*best_points)
    component[list(ys), list(xs)] = True
    return component


def flood_component(
    mask: np.ndarray,
    visited: np.ndarray,
    start_y: int,
    start_x: int,
) -> list[tuple[int, int]]:
    queue: deque[tuple[int, int]] = deque([(start_y, start_x)])
    visited[start_y, start_x] = True
    points: list[tuple[int, int]] = []
    height, width = mask.shape

    while queue:
        y, x = queue.popleft()
        points.append((y, x))
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if ny < 0 or nx < 0 or ny >= height or nx >= width:
                continue
            if visited[ny, nx] or not mask[ny, nx]:
                continue
            visited[ny, nx] = True
            queue.append((ny, nx))
    return points


def smooth_contour_guarded(
    contour: np.ndarray,
    *,
    desired_circularity: float = 0.8,
    max_iterations: int = 100,
    tolerance: float = 1e-3,
) -> tuple[np.ndarray, float]:
    """Smooth a contour with OpenCV when available, preserving nondegenerate output."""

    pts = normalize_points(contour)
    original_circularity = contour_circularity(pts)
    if original_circularity >= desired_circularity or len(pts) < 4:
        return pts, original_circularity

    try:
        import cv2
    except Exception:
        return pts, original_circularity

    cv_contour = pts.astype(np.float32).reshape((-1, 1, 2))
    perimeter = float(cv2.arcLength(cv_contour, closed=True))
    if perimeter <= 0:
        return pts, 0.0

    epsilon_coefficient = 0.001
    last_valid = pts
    last_circularity = original_circularity
    for _ in range(max_iterations):
        epsilon = epsilon_coefficient * perimeter
        smoothed = cv2.approxPolyDP(cv_contour, epsilon, closed=True)
        if smoothed is None or len(smoothed) < 4:
            break

        smoothed_pts = normalize_points(smoothed)
        circularity = contour_circularity(smoothed_pts)
        last_valid = smoothed_pts
        last_circularity = circularity
        if circularity >= desired_circularity or abs(circularity - desired_circularity) <= tolerance:
            return smoothed_pts, circularity

        epsilon_coefficient *= 1.1

    return last_valid, last_circularity


def contour_circularity(contour: np.ndarray) -> float:
    pts = normalize_points(contour)
    if len(pts) < 3:
        return 0.0
    area = polygon_area(pts)
    perimeter = polygon_perimeter(pts, x_scale=1.0, y_scale=1.0)
    if perimeter <= 0:
        return 0.0
    return float((4.0 * np.pi * area) / (perimeter**2))
