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
    object_seed: tuple[int, int] | None = None,
) -> SegmentationPreview:
    """Threshold an image and return the largest contour-like boundary.

    If object_seed (x, y) is given, selects the component at/nearest that pixel
    instead of the largest component.
    """

    mask = np.asarray(image) >= threshold
    contour = None
    method = "fallback"

    if object_seed is not None:
        contour = selected_component_contour(mask, seed_x=object_seed[0], seed_y=object_seed[1])
        if contour is not None:
            method = "seed"
    elif prefer_opencv:
        contour = largest_opencv_contour(mask)
        if contour is not None:
            method = "opencv"

    if contour is None and object_seed is None:
        contour = largest_component_boundary(mask)

    if contour is None:
        return SegmentationPreview(threshold, None, 0.0, 0.0, 0.0, method)

    area = polygon_area(contour)
    perimeter = polygon_perimeter(contour, x_scale=1.0, y_scale=1.0)
    circularity = 0.0
    if perimeter > 0:
        circularity = float((4.0 * np.pi * area) / (perimeter**2))
    return SegmentationPreview(threshold, contour, area, perimeter, circularity, method)


def selected_component_contour(
    mask: np.ndarray,
    *,
    seed_x: int,
    seed_y: int,
    min_area_px: int = 16,
) -> np.ndarray | None:
    """Return the contour of the component at/nearest (seed_x, seed_y).

    Uses OpenCV connectedComponentsWithStats when available. Falls back to
    picking the component whose bounding-box centre is nearest the seed.
    """
    try:
        import cv2
    except Exception:
        return _seed_component_fallback(mask, seed_x=seed_x, seed_y=seed_y, min_area_px=min_area_px)

    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("selected_component_contour expects a 2D mask")

    binary = arr.astype(np.uint8) * 255
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    if n_labels <= 1:
        return None

    height, width = arr.shape
    sx = int(np.clip(seed_x, 0, width - 1))
    sy = int(np.clip(seed_y, 0, height - 1))

    # Filter out background (label 0) and tiny components.
    label_ids = [
        i for i in range(1, n_labels)
        if int(stats[i, cv2.CC_STAT_AREA]) >= min_area_px
    ]
    if not label_ids:
        return None

    # If seed falls on a foreground pixel, use that label directly.
    seed_label = int(labels[sy, sx])
    if seed_label in label_ids:
        chosen = seed_label
    else:
        # Choose the component whose centroid is nearest the seed.
        def centroid_dist(lbl: int) -> float:
            area = int(stats[lbl, cv2.CC_STAT_AREA])
            if area == 0:
                return float("inf")
            region = labels == lbl
            ys, xs = np.nonzero(region)
            cx = float(xs.mean())
            cy = float(ys.mean())
            return float((cx - sx) ** 2 + (cy - sy) ** 2)

        chosen = min(label_ids, key=centroid_dist)

    component_mask = (labels == chosen).astype(np.uint8) * 255
    contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours or len(contours[0]) < 3:
        return None
    return normalize_points(contours[0])


def _seed_component_fallback(
    mask: np.ndarray,
    *,
    seed_x: int,
    seed_y: int,
    min_area_px: int,
) -> np.ndarray | None:
    """Pure-numpy fallback for seed-based component selection."""
    arr = np.asarray(mask, dtype=bool)
    height, width = arr.shape
    sx = int(np.clip(seed_x, 0, width - 1))
    sy = int(np.clip(seed_y, 0, height - 1))

    visited = np.zeros_like(arr, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            if arr[y, x] and not visited[y, x]:
                pts = flood_component(arr, visited, y, x)
                if len(pts) >= min_area_px:
                    components.append(pts)
    if not components:
        return None

    def seed_dist(pts: list[tuple[int, int]]) -> float:
        ys = [p[0] for p in pts]
        xs = [p[1] for p in pts]
        cy = sum(ys) / len(ys)
        cx = sum(xs) / len(xs)
        return (cx - sx) ** 2 + (cy - sy) ** 2

    # If seed lands on foreground, pick that component.
    if arr[sy, sx]:
        for comp in components:
            if (sy, sx) in set(comp):
                chosen_pts = comp
                break
        else:
            chosen_pts = min(components, key=seed_dist)
    else:
        chosen_pts = min(components, key=seed_dist)

    ys_arr = [p[0] for p in chosen_pts]
    xs_arr = [p[1] for p in chosen_pts]
    xmin = float(min(xs_arr))
    xmax = float(max(xs_arr) + 1)
    ymin = float(min(ys_arr))
    ymax = float(max(ys_arr) + 1)
    return np.array([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]], dtype=np.float64)


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
    valid = [contour for contour in contours if is_candidate_object_contour(contour, arr.shape)]
    candidates = valid if valid else contours
    largest = max(candidates, key=lambda contour: float(cv2.contourArea(contour)))
    if largest is None or len(largest) < 3:
        return None
    return normalize_points(largest)


def is_candidate_object_contour(contour, shape: tuple[int, int]) -> bool:
    try:
        import cv2
    except Exception:
        return True

    height, width = shape
    x, y, w, h = cv2.boundingRect(contour)
    if w < 8 or h < 8:
        return False
    aspect = max(w / h, h / w)
    if aspect > 8:
        return False
    touches_border = x <= 1 or y <= 1 or x + w >= width - 1 or y + h >= height - 1
    if touches_border:
        return False
    area = float(cv2.contourArea(contour))
    perimeter = float(cv2.arcLength(contour, closed=True))
    if perimeter <= 0:
        return False
    circularity = float((4.0 * np.pi * area) / (perimeter**2))
    return circularity >= 0.05


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
