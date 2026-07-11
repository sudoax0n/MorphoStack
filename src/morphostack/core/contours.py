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
    seed_radius: float = 10.0,
    ref_area: float | None = None,
) -> SegmentationPreview:
    """Threshold an image and return the largest contour-like boundary.

    If object_seed (x, y) is given, selects the component matching the seed
    (containment + area prior) instead of the largest component.
    """

    mask = np.asarray(image) >= threshold
    contour = None
    method = "fallback"

    if object_seed is not None:
        contour = selected_component_contour(
            mask,
            seed_x=object_seed[0],
            seed_y=object_seed[1],
            seed_radius=seed_radius,
            ref_area=ref_area,
        )
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
    seed_radius: float = 10.0,
    ref_area: float | None = None,
) -> np.ndarray | None:
    """Return the contour of the component best matching the seed.

    Prefers exterior contours that contain the seed (hollow GUV rings), with
    area consistency against ``ref_area`` / ``seed_radius``. On fused multi-
    vesicle masks, distance-transform watershed splits necks before pick so
    the contour does not wrap a neighbor. Rejects merge-sized blobs and dust.
    """
    from morphostack.core.object_select import (
        contour_from_component,
        isolate_seeded_mask,
        pick_component_from_mask,
    )

    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("selected_component_contour expects a 2D mask")

    # Split neck-fused multi-vesicle blobs before component selection.
    arr = isolate_seeded_mask(
        arr,
        seed_x=float(seed_x),
        seed_y=float(seed_y),
        seed_radius=float(seed_radius),
    )

    comp = pick_component_from_mask(
        arr,
        seed_x=float(seed_x),
        seed_y=float(seed_y),
        seed_radius=float(seed_radius),
        ref_area=ref_area,
        min_area_px=min_area_px,
    )
    if comp is None:
        return _seed_component_fallback(mask, seed_x=seed_x, seed_y=seed_y, min_area_px=min_area_px)
    return contour_from_component(comp)


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
    # Close 1-2 px noise holes before tracing (geometry only; no mask Gaussian).
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    valid = [contour for contour in contours if is_candidate_object_contour(contour, arr.shape)]
    candidates = valid if valid else contours
    largest = max(candidates, key=lambda contour: float(cv2.contourArea(contour)))
    if largest is None or len(largest) < 3:
        return None
    pts = normalize_points(largest)
    return smooth_contour_spline(pts)


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


def _arc_length_resample(xy: np.ndarray, target_spacing: float = 1.0) -> np.ndarray:
    """Resample a closed contour to uniform arc-length spacing."""
    pts = np.asarray(xy, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 3 or pts.shape[1] < 2:
        return pts
    # Drop duplicate closing vertex if present.
    if np.allclose(pts[0], pts[-1], atol=1e-9):
        pts = pts[:-1]
    if len(pts) < 3:
        return np.asarray(xy, dtype=np.float64)

    closed = np.vstack([pts, pts[0:1]])
    seg = np.hypot(np.diff(closed[:, 0]), np.diff(closed[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total <= 1e-12:
        return pts
    n_pts = max(8, int(round(total / max(float(target_spacing), 1e-6))))
    t_new = np.linspace(0.0, total, n_pts, endpoint=False)
    x_new = np.interp(t_new, cum, closed[:, 0])
    y_new = np.interp(t_new, cum, closed[:, 1])
    return np.column_stack([x_new, y_new])


def smooth_contour_spline(
    xy: np.ndarray,
    *,
    sigma_px: float = 1.5,
    target_spacing: float = 0.75,
) -> np.ndarray:
    """Periodic cubic B-spline smooth on arc-length-resampled points.

    Uses the noise-budget rule ``s ≈ M · σ²`` (research: contour_smoothing_method).
    Falls back to the original points if the fit fails or scipy is unavailable.
    Tiny contours (perimeter ≲ 24 px) are left unsmoothed — high ``s`` relative to
    object scale collapses them toward a point.
    """
    pts_in = normalize_points(xy)
    if len(pts_in) < 4:
        return pts_in

    peri_in = polygon_perimeter(pts_in, x_scale=1.0, y_scale=1.0)
    if peri_in < 24.0:
        return pts_in

    # Cap σ by object scale so small contours (test fixtures / tiny vesicles)
    # are not over-smoothed into severe area shrinkage. For R≳30 px membranes,
    # 0.08·R ≥ 1.5 and the default noise budget applies fully.
    char_r = peri_in / (2.0 * np.pi)
    sigma_eff = min(float(sigma_px), max(0.35, 0.08 * char_r))

    try:
        from scipy.interpolate import splev, splprep
    except Exception:
        return pts_in

    pts = _arc_length_resample(pts_in, target_spacing=float(target_spacing))
    m = len(pts)
    if m < 6:
        return pts_in

    s_target = float(m) * (sigma_eff ** 2)
    try:
        # per=True: closed curve; last sample is unused by FITPACK periodic mode.
        tck, _ = splprep(
            [pts[:, 0], pts[:, 1]],
            per=True,
            k=3,
            s=s_target,
        )
        # Evaluate at 2x points for stable perimeter integration.
        u_eval = np.linspace(0.0, 1.0, m * 2, endpoint=False)
        xs, ys = splev(u_eval, tck)
        out = np.column_stack([np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)])
        if len(out) < 3 or not np.all(np.isfinite(out)):
            return pts_in
        # Reject degenerate collapse (all points nearly identical).
        span = float(np.ptp(out[:, 0]) + np.ptp(out[:, 1]))
        if span < 1e-3:
            return pts_in
        return out
    except Exception:
        return pts_in


def smooth_contour_guarded(
    contour: np.ndarray,
    *,
    desired_circularity: float = 0.8,
    max_iterations: int = 100,
    tolerance: float = 1e-3,
    sigma_px: float = 1.5,
) -> tuple[np.ndarray, float]:
    """Smooth a closed contour with periodic cubic B-spline (noise-budget).

    ``desired_circularity`` / ``max_iterations`` / ``tolerance`` are retained for
    API compatibility; smoothing is a single spline pass (no polyline simplify).
    """
    del max_iterations, tolerance  # API compat; spline uses noise budget not RDP loop
    pts = normalize_points(contour)
    original_circularity = contour_circularity(pts)
    if original_circularity >= desired_circularity or len(pts) < 4:
        return pts, original_circularity

    smoothed = smooth_contour_spline(pts, sigma_px=sigma_px)
    if len(smoothed) < 3:
        return pts, original_circularity
    circ = contour_circularity(smoothed)
    if circ <= 0.0:
        return pts, original_circularity
    return smoothed, circ


def contour_circularity(contour: np.ndarray) -> float:
    pts = normalize_points(contour)
    if len(pts) < 3:
        return 0.0
    area = polygon_area(pts)
    perimeter = polygon_perimeter(pts, x_scale=1.0, y_scale=1.0)
    if perimeter <= 0:
        return 0.0
    return float((4.0 * np.pi * area) / (perimeter**2))
