"""Non-interactive segmentation primitives."""

from __future__ import annotations

import numpy as np


def threshold_mask(image: np.ndarray, threshold: float) -> np.ndarray:
    """Return a boolean mask where pixels are above or equal to threshold."""

    return np.asarray(image) >= threshold


def apply_rect_roi(
    stack: np.ndarray,
    *,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
) -> np.ndarray:
    """Mask everything outside a rectangular ROI on all stack frames."""

    arr = np.asarray(stack).copy()
    if arr.ndim < 3:
        raise ValueError("ROI application expects a stack with at least 3 dimensions")

    height, width = arr.shape[1], arr.shape[2]
    x0 = max(0, min(width, xmin))
    x1 = max(0, min(width, xmax))
    y0 = max(0, min(height, ymin))
    y1 = max(0, min(height, ymax))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("ROI bounds must define a non-empty rectangle")

    mask = np.zeros((height, width), dtype=bool)
    mask[y0:y1, x0:x1] = True
    if arr.ndim == 3:
        arr[:, ~mask] = 0
    else:
        arr[:, ~mask, :] = 0
    return arr

