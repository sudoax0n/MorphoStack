"""Polar-DP (Viterbi) membrane contour extraction.

Transforms a 2D slice to polar coordinates centered on a seed point,
then uses dynamic programming to find the optimal membrane contour
as the brightest path through the polar image with spatial smoothness.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PolarDPResult:
    """Result of Polar-DP contour extraction for one slice."""

    contour_xy: np.ndarray | None  # Nx2 float array in original Cartesian coords
    solid_mask: np.ndarray | None  # boolean mask in original frame coordinates
    center_xy: tuple[float, float]  # seed center used
    radius_range: tuple[float, float]  # (r_min, r_max) searched
    path_cost: float  # total DP cost (lower = better fit)
    method: str  # "polar_dp"
    ok: bool


def polar_transform(
    img: np.ndarray,
    center: tuple[float, float],
    r_min: float,
    r_max: float,
    n_angles: int = 360,
    n_radii: int | None = None,
) -> np.ndarray:
    """Transform Cartesian image to polar coordinates.

    Returns a 2D array of shape (n_angles, n_radii) where each row
    is a radial profile at a different angle. Center is (x, y).
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("polar_transform expects a 2D image")
    cx, cy = float(center[0]), float(center[1])
    r_min = max(0.0, float(r_min))
    r_max = max(r_min + 1.0, float(r_max))
    n_angles = max(8, int(n_angles))
    if n_radii is None:
        n_radii = max(8, int(np.ceil(r_max - r_min)) + 1)
    n_radii = max(4, int(n_radii))

    angles = np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False)
    radii = np.linspace(r_min, r_max, n_radii)
    # Broadcast to shape (n_angles, n_radii): x = cx + r cos θ, y = cy + r sin θ
    aa = angles[:, None]
    rr = radii[None, :]
    sample_x = cx + rr * np.cos(aa)
    sample_y = cy + rr * np.sin(aa)

    try:
        from scipy.ndimage import map_coordinates

        # map_coordinates expects (row, col) = (y, x)
        coords = np.vstack([sample_y.ravel(), sample_x.ravel()])
        sampled = map_coordinates(arr, coords, order=1, mode="nearest")
        return sampled.reshape(n_angles, n_radii)
    except Exception:
        # Nearest-neighbor fallback
        h, w = arr.shape
        ix = np.clip(np.round(sample_x).astype(int), 0, w - 1)
        iy = np.clip(np.round(sample_y).astype(int), 0, h - 1)
        return arr[iy, ix]


def compute_cost_image(
    polar_img: np.ndarray,
    gradient_weight: float = 0.7,
    intensity_weight: float = 0.3,
) -> np.ndarray:
    """Compute the cost image for DP.

    Cost = -(gradient_weight * radial_gradient + intensity_weight * intensity).
    The membrane should be a high-gradient, high-intensity ridge → low cost.
    """
    pol = np.asarray(polar_img, dtype=np.float64)
    # Radial gradient along radius axis (axis=1)
    grad = np.abs(np.gradient(pol, axis=1))
    # Normalize each to [0, 1]
    def _norm(a: np.ndarray) -> np.ndarray:
        lo, hi = float(np.min(a)), float(np.max(a))
        if hi <= lo + 1e-12:
            return np.zeros_like(a)
        return (a - lo) / (hi - lo)

    g = _norm(grad)
    i = _norm(pol)
    score = gradient_weight * g + intensity_weight * i
    return -score


def viterbi_optimal_path(
    cost: np.ndarray,
    smoothness_penalty: float = 2.0,
    max_jump: int = 3,
) -> np.ndarray:
    """Find the optimal path through the cost image using Viterbi DP.

    Returns array of shape (n_angles,) with the optimal radius index
    at each angle.
    """
    c = np.asarray(cost, dtype=np.float64)
    if c.ndim != 2:
        raise ValueError("cost must be 2D (n_angles, n_radii)")
    n_angles, n_radii = c.shape
    max_jump = max(1, int(max_jump))
    pen = float(smoothness_penalty)

    acc = np.full((n_angles, n_radii), np.inf, dtype=np.float64)
    back = np.zeros((n_angles, n_radii), dtype=np.int32)
    acc[0, :] = c[0, :]

    for t in range(1, n_angles):
        for r in range(n_radii):
            r0 = max(0, r - max_jump)
            r1 = min(n_radii, r + max_jump + 1)
            prev = acc[t - 1, r0:r1]
            jumps = np.abs(np.arange(r0, r1) - r) * pen
            scores = prev + jumps
            best = int(np.argmin(scores))
            acc[t, r] = c[t, r] + scores[best]
            back[t, r] = r0 + best

    # Backtrack
    path = np.zeros(n_angles, dtype=np.int32)
    path[-1] = int(np.argmin(acc[-1, :]))
    for t in range(n_angles - 2, -1, -1):
        path[t] = back[t + 1, path[t + 1]]

    # Optional wraparound refinement: re-run first few angles with wrap constraint
    # using path[-1] as soft prior for path[0] continuity (cheap second pass).
    wrap_pen = abs(int(path[0]) - int(path[-1])) * pen
    if wrap_pen > pen * max_jump:
        # Force start near end radius and re-forward once
        r_end = int(path[-1])
        acc2 = np.full((n_angles, n_radii), np.inf, dtype=np.float64)
        back2 = np.zeros((n_angles, n_radii), dtype=np.int32)
        for r in range(n_radii):
            acc2[0, r] = c[0, r] + abs(r - r_end) * pen
        for t in range(1, n_angles):
            for r in range(n_radii):
                r0 = max(0, r - max_jump)
                r1 = min(n_radii, r + max_jump + 1)
                prev = acc2[t - 1, r0:r1]
                jumps = np.abs(np.arange(r0, r1) - r) * pen
                scores = prev + jumps
                best = int(np.argmin(scores))
                acc2[t, r] = c[t, r] + scores[best]
                back2[t, r] = r0 + best
        path2 = np.zeros(n_angles, dtype=np.int32)
        path2[-1] = int(np.argmin(acc2[-1, :]))
        for t in range(n_angles - 2, -1, -1):
            path2[t] = back2[t + 1, path2[t + 1]]
        if float(acc2[-1, path2[-1]]) < float(acc[-1, path[-1]]) + wrap_pen * 0.5:
            path = path2

    return path


def polar_to_cartesian_contour(
    path: np.ndarray,
    center: tuple[float, float],
    r_min: float,
    r_max: float,
    n_radii: int,
) -> np.ndarray:
    """Convert the optimal polar path back to Cartesian (x, y) contour points."""
    path = np.asarray(path, dtype=np.float64)
    n_angles = int(path.shape[0])
    n_radii = max(2, int(n_radii))
    radii = np.linspace(float(r_min), float(r_max), n_radii)
    # path indices → continuous radius (clamp)
    idx = np.clip(path, 0, n_radii - 1)
    r_vals = radii[idx.astype(int)]
    angles = np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False)
    cx, cy = float(center[0]), float(center[1])
    xs = cx + r_vals * np.cos(angles)
    ys = cy + r_vals * np.sin(angles)
    return np.column_stack([xs, ys]).astype(np.float64)


def contour_to_solid_mask(
    contour_xy: np.ndarray,
    shape: tuple[int, int],
) -> np.ndarray:
    """Fill a contour to produce a solid boolean mask."""
    h, w = int(shape[0]), int(shape[1])
    mask = np.zeros((h, w), dtype=bool)
    pts = np.asarray(contour_xy, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 3:
        return mask

    try:
        import cv2

        poly = np.round(pts).astype(np.int32).reshape(-1, 1, 2)
        canvas = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(canvas, [poly], 1)
        return canvas.astype(bool)
    except Exception:
        pass

    try:
        from skimage.draw import polygon as sk_polygon

        rr, cc = sk_polygon(pts[:, 1], pts[:, 0], shape=(h, w))
        mask[rr, cc] = True
        return mask
    except Exception:
        # Bounding-box fallback (weak)
        xs = np.clip(np.round(pts[:, 0]).astype(int), 0, w - 1)
        ys = np.clip(np.round(pts[:, 1]).astype(int), 0, h - 1)
        if xs.size and ys.size:
            mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] = True
        return mask


def segment_slice_polar_dp(
    slice_2d: np.ndarray,
    center_x: float,
    center_y: float,
    radius: float,
    *,
    search_band: float = 0.4,
    n_angles: int = 360,
    smoothness_penalty: float = 2.0,
    max_jump: int = 3,
) -> PolarDPResult:
    """Segment a single slice using Polar-DP.

    Args:
        slice_2d: 2D grayscale image
        center_x, center_y: seed lumen center (x, y)
        radius: approximate vesicle radius from user circle
        search_band: fraction of radius to search above/below
    """
    arr = np.asarray(slice_2d, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("segment_slice_polar_dp expects a 2D slice")
    h, w = arr.shape
    cx = float(np.clip(center_x, 0, w - 1))
    cy = float(np.clip(center_y, 0, h - 1))
    R = max(float(radius), 3.0)
    band = float(np.clip(search_band, 0.05, 0.9))
    r_min = max(1.0, R * (1.0 - band))
    r_max = max(r_min + 2.0, R * (1.0 + band))
    n_radii = max(8, int(np.ceil(r_max - r_min)) + 1)

    fail = PolarDPResult(
        None, None, (cx, cy), (r_min, r_max), float("inf"), "polar_dp", False
    )

    try:
        polar = polar_transform(arr, (cx, cy), r_min, r_max, n_angles=n_angles, n_radii=n_radii)
        cost = compute_cost_image(polar)
        path = viterbi_optimal_path(cost, smoothness_penalty=smoothness_penalty, max_jump=max_jump)
        path_cost = float(np.mean(cost[np.arange(len(path)), path]))
        contour = polar_to_cartesian_contour(path, (cx, cy), r_min, r_max, n_radii)
        solid = contour_to_solid_mask(contour, (h, w))
        if np.count_nonzero(solid) < 16:
            return fail
        # Reject empty / near-empty slices (DP always finds *some* path)
        arr_max = float(np.max(arr))
        arr_mean = float(np.mean(arr))
        if arr_max <= 1e-12:
            return fail
        path_vals = polar[np.arange(len(path)), np.clip(path, 0, polar.shape[1] - 1)]
        path_mean = float(np.mean(path_vals))
        # Cap-like / no-membrane: path not brighter than background
        if path_mean < arr_mean * 1.05 + 1e-12:
            return fail
        # Require path to sit on a real ridge (not uniform noise floor)
        if path_mean < arr_max * 0.15:
            return fail
        return PolarDPResult(
            contour_xy=contour,
            solid_mask=solid,
            center_xy=(cx, cy),
            radius_range=(r_min, r_max),
            path_cost=path_cost,
            method="polar_dp",
            ok=True,
        )
    except Exception:
        return fail
