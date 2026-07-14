"""Contour and boundary metrics for promotion scoring (labelled frames only)."""

from __future__ import annotations

from typing import Any

import numpy as np


def dice_binary(pred: np.ndarray, ref: np.ndarray) -> float:
    p = np.asarray(pred, dtype=bool)
    r = np.asarray(ref, dtype=bool)
    if p.shape != r.shape:
        raise ValueError(f"shape mismatch pred={p.shape} ref={r.shape}")
    inter = float(np.logical_and(p, r).sum())
    denom = float(p.sum() + r.sum())
    if denom <= 0.0:
        return 1.0 if inter == 0.0 else 0.0
    return 2.0 * inter / denom


def jaccard_binary(pred: np.ndarray, ref: np.ndarray) -> float:
    p = np.asarray(pred, dtype=bool)
    r = np.asarray(ref, dtype=bool)
    if p.shape != r.shape:
        raise ValueError(f"shape mismatch pred={p.shape} ref={r.shape}")
    inter = float(np.logical_and(p, r).sum())
    union = float(np.logical_or(p, r).sum())
    if union <= 0.0:
        return 1.0
    return inter / union


def _boundary_coords(mask: np.ndarray) -> np.ndarray:
    """Return (N,2) yx coordinates of boundary pixels (simple morphological edge)."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return np.zeros((0, 2), dtype=np.float64)
    # Interior erosion via shift AND
    up = np.zeros_like(m)
    down = np.zeros_like(m)
    left = np.zeros_like(m)
    right = np.zeros_like(m)
    up[1:, :] = m[:-1, :]
    down[:-1, :] = m[1:, :]
    left[:, 1:] = m[:, :-1]
    right[:, :-1] = m[:, 1:]
    interior = m & up & down & left & right
    edge = m & ~interior
    ys, xs = np.nonzero(edge if edge.any() else m)
    return np.column_stack([ys.astype(np.float64), xs.astype(np.float64)])


def hausdorff95_boundary(
    pred: np.ndarray,
    ref: np.ndarray,
    *,
    pixel_size_yx_um: tuple[float, float] | None = None,
) -> float | None:
    """95th percentile bidirectional boundary distance.

    Coordinates are row/col (y, x). When ``pixel_size_yx_um`` is provided as
    ``(y_um, x_um)``, distances are returned in **µm**; otherwise in **pixels**.
    """
    pb = _boundary_coords(pred)
    rb = _boundary_coords(ref)
    if pb.size == 0 or rb.size == 0:
        return None
    if pixel_size_yx_um is not None:
        sy = float(pixel_size_yx_um[0])
        sx = float(pixel_size_yx_um[1])
        if not (sy > 0 and sx > 0):
            raise ValueError("pixel_size_yx_um must be positive")
        scale = np.array([sy, sx], dtype=np.float64)
        pb = pb * scale
        rb = rb * scale
    # Distances from pred→ref and ref→pred
    d_pr = _min_dists(pb, rb)
    d_rp = _min_dists(rb, pb)
    all_d = np.concatenate([d_pr, d_rp])
    return float(np.percentile(all_d, 95))


def _min_dists(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # a: (Na,2), b: (Nb,2)
    # For small masks OK; O(Na*Nb).
    diff = a[:, None, :] - b[None, :, :]
    dist = np.sqrt((diff * diff).sum(axis=2))
    return dist.min(axis=1)


def relative_area_error(pred_area: float, ref_area: float) -> float | None:
    if ref_area <= 0:
        return None
    return (float(pred_area) - float(ref_area)) / float(ref_area)


def summarize_frame_scores(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {"n": 0, "median": None, "worst": None, "mean": None}
    arr = np.asarray(scores, dtype=np.float64)
    return {
        "n": int(arr.size),
        "median": float(np.median(arr)),
        "worst": float(arr.min()),
        "mean": float(arr.mean()),
    }
