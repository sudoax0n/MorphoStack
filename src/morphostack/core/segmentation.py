"""Non-interactive segmentation primitives."""

from __future__ import annotations

from typing import Any

import numpy as np

# Cap for Otsu / percentile suggestion so large Z-stacks never materialize a
# full float64 ravel or full-volume boolean masks (OOM on ~1e8+ voxels).
_DEFAULT_MAX_SAMPLES = 2_000_000
_DEFAULT_SAMPLE_SEED = 0

# Threshold contract schema version (suggestion / preview / export).
THRESHOLD_CONTRACT_VERSION = "1"


def threshold_mask(image: np.ndarray, threshold: float) -> np.ndarray:
    """Return a boolean mask where pixels are above or equal to threshold."""

    return np.asarray(image) >= threshold


def _sample_intensity_values(
    stack: np.ndarray,
    *,
    max_samples: int = _DEFAULT_MAX_SAMPLES,
    seed: int = _DEFAULT_SAMPLE_SEED,
) -> np.ndarray:
    """Return a float64 sample of intensities without copying the full volume.

    For stacks larger than ``max_samples``, draws a fixed-seed random subset
    (with a light non-zero enrichment pass when the first draw is mostly zero)
    so threshold suggestion stays O(max_samples) in extra memory.
    """

    if max_samples < 1:
        raise ValueError("max_samples must be at least 1")

    flat = np.ravel(np.asarray(stack))
    n = int(flat.size)
    if n == 0:
        return np.empty(0, dtype=np.float64)

    if n <= max_samples:
        sample = np.asarray(flat, dtype=np.float64)
    else:
        rng = np.random.default_rng(seed)
        # replace=False is fine: Generator.choice uses a hash-set path when
        # size << n, so we only allocate the index vector (~max_samples).
        idx = rng.choice(n, size=max_samples, replace=False)
        # Sort for better sequential reads on large arrays.
        idx.sort()
        sample = np.asarray(flat[idx], dtype=np.float64)

        # Membrane stacks are often mostly background zeros. If the draw is
        # nearly all zero, replace some zero slots with positives from a second
        # draw so Otsu still sees foreground while keeping background mass.
        positive = sample[sample > 0]
        min_positive = max(16, max_samples // 50)
        if positive.size < min_positive:
            extra_idx = rng.choice(n, size=max_samples, replace=False)
            extra = np.asarray(flat[extra_idx], dtype=np.float64)
            extra_pos = extra[extra > 0]
            if extra_pos.size:
                zero_idx = np.flatnonzero(sample <= 0)
                need = min(min_positive - int(positive.size), int(extra_pos.size), int(zero_idx.size))
                if need > 0:
                    sample = sample.copy()
                    sample[zero_idx[:need]] = extra_pos[:need]

    if np.issubdtype(flat.dtype, np.floating):
        finite = np.isfinite(sample)
        if not bool(np.all(finite)):
            sample = sample[finite]
    return sample


def suggest_threshold(
    stack: np.ndarray,
    *,
    method: str = "auto",
    max_samples: int = _DEFAULT_MAX_SAMPLES,
    seed: int = _DEFAULT_SAMPLE_SEED,
) -> tuple[float, str]:
    """Suggest an intensity threshold for a stack.

    Large volumes are subsampled (see ``max_samples``) so suggestion never
    allocates a full-stack float64 buffer or full-size boolean masks.

    Numerical algorithm is frozen for Milestone A contract work; use
    :func:`suggest_threshold_report` for schema metadata without changing values.
    """

    threshold, used_method, _meta = suggest_threshold_report(
        stack, method=method, max_samples=max_samples, seed=seed
    )
    return threshold, used_method


def suggest_threshold_report(
    stack: np.ndarray,
    *,
    method: str = "auto",
    max_samples: int = _DEFAULT_MAX_SAMPLES,
    seed: int = _DEFAULT_SAMPLE_SEED,
    suggestion_scope: str = "stack_sample",
    source_path: str = "",
    source_revision: str | None = None,
    source_identity_kind: str | None = None,
    z_range: dict[str, int] | None = None,
    roi: dict[str, int] | None = None,
    frame: int | None = None,
) -> tuple[float, str, dict[str, Any]]:
    """Return ``(threshold, method, domain_meta)`` with contract metadata.

    Sampling and Otsu/percentile selection match :func:`suggest_threshold`.
    ``suggestion_scope`` is recorded only; only ``stack_sample`` is implemented
    (current_slice / roi_current_slice are not silently substituted).

    ``source_revision`` is the tracking/cache-style identity when known
    (``path:…|m…|s…`` or ``session:{id}``). Ephemeral uploads must pass
    ``None`` — never a bare filename. Optional ``source_identity_kind`` is
    ``path`` | ``session`` | ``upload_ephemeral``.
    """

    scope = (suggestion_scope or "stack_sample").strip().lower()
    if scope not in {"stack_sample", "current_slice", "roi_current_slice"}:
        raise ValueError(
            "suggestion_scope must be stack_sample, current_slice, or roi_current_slice"
        )
    if scope != "stack_sample":
        # Contract: do not silently substitute; Milestone A keeps stack_sample only.
        raise ValueError(
            f"suggestion_scope={scope!r} is not implemented yet; use stack_sample"
        )

    arr = np.asarray(stack)
    if arr.size == 0:
        raise ValueError("Cannot suggest a threshold for an empty stack")

    values = _sample_intensity_values(arr, max_samples=max_samples, seed=seed)
    if values.size == 0:
        raise ValueError("Cannot suggest a threshold for non-finite image data")

    normalized_method = method.strip().lower()
    if normalized_method not in {"auto", "otsu", "percentile"}:
        raise ValueError("threshold method must be auto, otsu, or percentile")
    if float(np.min(values)) == float(np.max(values)):
        thr, used = float(values[0]), "constant"
    elif normalized_method == "auto":
        robust = robust_otsu_threshold(values)
        if robust is not None:
            thr, used = robust, "robust_otsu"
        else:
            threshold = otsu_threshold(values)
            if threshold is not None:
                thr, used = threshold, "otsu"
            else:
                thr, used = float(np.percentile(values, 75)), "percentile"
    elif normalized_method == "otsu":
        threshold = otsu_threshold(values)
        if threshold is None:
            raise RuntimeError("Otsu thresholding requires scikit-image")
        thr, used = threshold, "otsu"
    else:
        thr, used = float(np.percentile(values, 75)), "percentile"

    dtype_name = str(arr.dtype)
    warnings: list[str] = [
        "Single global starting guess; intensity may vary across Z.",
        "Seeded exact analysis uses a per-frame local gate or ridge method.",
    ]
    if used == "robust_otsu":
        warnings.append(
            "robust_otsu currently filters intensities with 0 < value < 250; "
            "this may exclude valid 16-bit membrane values "
            "(known gap; not fixed in Milestone A)."
        )

    domain: dict[str, Any] = {
        "frame": frame if scope != "stack_sample" else None,
        "z_range": z_range,
        "roi": roi,
        "n_voxels_total": int(arr.size),
        "n_samples": int(values.size),
        "sample_seed": int(seed),
        "max_samples": int(max_samples),
        "dtype": dtype_name,
        "finite_only": True,
    }
    rev = source_revision  # may be None (ephemeral upload)
    kind = source_identity_kind
    if kind is None:
        if rev is None:
            kind = "unknown"
        elif str(rev).startswith("session:"):
            kind = "session"
        elif str(rev).startswith("path:"):
            kind = "path"
        else:
            kind = "unknown"
    if rev is None and kind == "upload_ephemeral":
        warnings.append(
            "Ephemeral multipart upload: source_revision is null "
            "(filename is display-only, not a cache/tracking identity)."
        )

    meta: dict[str, Any] = {
        "threshold_contract_version": THRESHOLD_CONTRACT_VERSION,
        "source_path": source_path,
        "source_revision": rev,
        "source_identity_kind": kind,
        "threshold": float(thr),
        "method": used,
        "threshold_semantics": "ui_starting_guess",
        "suggestion_scope": scope,
        "histogram_domain": domain,
        "authoritative_for": [],
        "not_authoritative_for": [
            "seeded_exact_contour",
            "seeded_exact_mask",
            "per_frame_adaptive_threshold",
        ],
        "warnings": warnings,
    }
    return float(thr), used, meta


def otsu_threshold(values: np.ndarray) -> float | None:
    try:
        from skimage.filters import threshold_otsu
    except Exception:
        return None
    return float(threshold_otsu(values))


def robust_otsu_threshold(values: np.ndarray) -> float | None:
    """Otsu threshold after removing zeros and saturated annotation-like pixels."""

    try:
        from skimage.filters import threshold_otsu
    except Exception:
        return None

    arr = np.asarray(values, dtype=np.float64)
    # Filter non-finite without assuming callers already did (cheap on samples).
    finite_mask = np.isfinite(arr)
    finite = arr if bool(np.all(finite_mask)) else arr[finite_mask]
    if finite.size == 0:
        return None

    # Single combined range filter (sample-sized; never full-volume).
    robust = finite[(finite > 0) & (finite < 250)]
    if robust.size < 16 or float(np.min(robust)) == float(np.max(robust)):
        return None
    threshold = float(threshold_otsu(robust))
    full = otsu_threshold(finite)
    if full is not None and full > threshold * 2.0 and threshold > 0:
        return threshold
    return full if full is not None else threshold


def _clamp_rect_roi_bounds(
    height: int,
    width: int,
    *,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
) -> tuple[int, int, int, int]:
    """Clamp inclusive-exclusive ROI bounds to an image plane; reject empty rects."""

    x0 = max(0, min(width, xmin))
    x1 = max(0, min(width, xmax))
    y0 = max(0, min(height, ymin))
    y1 = max(0, min(height, ymax))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("ROI bounds must define a non-empty rectangle")
    return x0, x1, y0, y1


def apply_rect_roi(
    stack: np.ndarray,
    *,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
) -> np.ndarray:
    """Mask everything outside a rectangular ROI on all stack frames.

    Full-stack path used by analyze/mesh. Prefer :func:`crop_rect_roi_2d` or
    :func:`apply_rect_roi_2d` for single-plane preview work.
    """

    arr = np.asarray(stack).copy()
    if arr.ndim < 3:
        raise ValueError("ROI application expects a stack with at least 3 dimensions")

    height, width = arr.shape[1], arr.shape[2]
    x0, x1, y0, y1 = _clamp_rect_roi_bounds(
        height, width, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax
    )

    mask = np.zeros((height, width), dtype=bool)
    mask[y0:y1, x0:x1] = True
    if arr.ndim == 3:
        arr[:, ~mask] = 0
    else:
        arr[:, ~mask, :] = 0
    return arr


def crop_rect_roi_2d(
    frame: np.ndarray,
    *,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
) -> np.ndarray:
    """Crop a single 2D plane to a rectangular ROI (no full-stack copy)."""

    arr = np.asarray(frame)
    if arr.ndim != 2:
        raise ValueError("2D ROI crop expects a single plane shaped as (y, x)")
    height, width = arr.shape
    x0, x1, y0, y1 = _clamp_rect_roi_bounds(
        height, width, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax
    )
    # Contiguous for fast PIL / OpenCV consumers; crop is a small copy vs full Z.
    return np.ascontiguousarray(arr[y0:y1, x0:x1])


def apply_rect_roi_2d(
    frame: np.ndarray,
    *,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
) -> np.ndarray:
    """Zero-mask outside a rectangular ROI on one 2D plane only."""

    arr = np.asarray(frame)
    if arr.ndim != 2:
        raise ValueError("2D ROI mask expects a single plane shaped as (y, x)")
    height, width = arr.shape
    x0, x1, y0, y1 = _clamp_rect_roi_bounds(
        height, width, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax
    )
    out = arr.copy()
    mask = np.zeros((height, width), dtype=bool)
    mask[y0:y1, x0:x1] = True
    out[~mask] = 0
    return out


def apply_z_range(stack: np.ndarray, *, zmin: int, zmax: int) -> np.ndarray:
    """Return a stack trimmed to an inclusive-exclusive Z slice range."""

    arr = np.asarray(stack)
    if arr.ndim < 3:
        raise ValueError("Z range trimming expects a stack with at least 3 dimensions")

    frame_count = arr.shape[0]
    z0 = max(0, min(frame_count, zmin))
    z1 = max(0, min(frame_count, zmax))
    if z1 <= z0:
        raise ValueError("Z range bounds must define at least one frame")
    return arr[z0:z1]
