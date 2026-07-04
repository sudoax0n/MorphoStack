"""Non-interactive segmentation primitives."""

from __future__ import annotations

import numpy as np


def threshold_mask(image: np.ndarray, threshold: float) -> np.ndarray:
    """Return a boolean mask where pixels are above or equal to threshold."""

    return np.asarray(image) >= threshold


def suggest_threshold(stack: np.ndarray, *, method: str = "auto") -> tuple[float, str]:
    """Suggest an intensity threshold for a stack."""

    arr = np.asarray(stack)
    if arr.size == 0:
        raise ValueError("Cannot suggest a threshold for an empty stack")

    values = arr.astype(np.float64).ravel()
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("Cannot suggest a threshold for non-finite image data")

    normalized_method = method.strip().lower()
    if normalized_method not in {"auto", "otsu", "percentile"}:
        raise ValueError("threshold method must be auto, otsu, or percentile")
    if float(np.min(values)) == float(np.max(values)):
        return float(values[0]), "constant"

    if normalized_method in {"auto", "otsu"}:
        threshold = otsu_threshold(values)
        if threshold is not None:
            return threshold, "otsu"
        if normalized_method == "otsu":
            raise RuntimeError("Otsu thresholding requires scikit-image")

    return float(np.percentile(values, 75)), "percentile"


def otsu_threshold(values: np.ndarray) -> float | None:
    try:
        from skimage.filters import threshold_otsu
    except Exception:
        return None
    return float(threshold_otsu(values))


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
