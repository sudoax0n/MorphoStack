"""Robust single-object selection for crowded membrane fields.

Threshold masks of GUVs are often hollow rings. The seed click is usually in the
dark interior, not on foreground pixels. Naive "nearest centroid" then latches
onto noise or a neighboring vesicle as Z changes.

This module picks components by:
1. Exterior contour containing the seed (ring / filled object)
2. Area consistency with a reference (seed-frame area or seed radius)
3. Rejecting merge-sized blobs and tiny noise
"""

from __future__ import annotations

from typing import Any

import numpy as np


def expected_area_from_radius(seed_radius: float) -> float:
    """Rough filled-disk area prior from UI seed radius (px)."""
    r = max(1.0, float(seed_radius))
    return float(np.pi * r * r)


def component_exterior_contains(
    sub_mask: np.ndarray,
    *,
    bbox: tuple[int, int, int, int],
    seed_x: float,
    seed_y: float,
) -> bool:
    """True if the seed lies inside the component's external contour (or on FG)."""
    ymin, ymax, xmin, xmax = bbox
    lx = int(round(seed_x)) - xmin
    ly = int(round(seed_y)) - ymin
    h, w = sub_mask.shape
    if 0 <= lx < w and 0 <= ly < h and bool(sub_mask[ly, lx]):
        return True

    try:
        import cv2
    except Exception:
        # BBox containment as weak fallback.
        return xmin <= seed_x < xmax and ymin <= seed_y < ymax

    binary = np.asarray(sub_mask, dtype=np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    # Local coordinates relative to bbox.
    pt = (float(seed_x - xmin), float(seed_y - ymin))
    best = max(contours, key=cv2.contourArea)
    if len(best) < 3:
        return False
    return float(cv2.pointPolygonTest(best, pt, False)) >= 0.0


def score_component(
    comp: dict[str, Any],
    *,
    seed_x: float,
    seed_y: float,
    ref_area: float,
    seed_radius: float,
) -> float | None:
    """Lower score is better. None = reject."""
    area = float(comp["area"])
    if area < 16:
        return None

    # Reject obvious merges (>> reference) and dust (<< reference).
    max_ratio = 2.5
    min_ratio = 0.12
    if ref_area > 0:
        if area > ref_area * max_ratio:
            return None
        if area < ref_area * min_ratio:
            return None

    cx, cy = comp["centroid"]
    dist2 = (cx - seed_x) ** 2 + (cy - seed_y) ** 2
    max_dist = max(3.0 * float(seed_radius), 40.0)
    contains = component_exterior_contains(
        comp["sub_mask"],
        bbox=comp["bbox"],
        seed_x=seed_x,
        seed_y=seed_y,
    )
    if not contains and dist2 > max_dist ** 2:
        return None

    area_term = abs(area - ref_area) / max(ref_area, 1.0)
    # Prefer containment heavily (hollow rings with center seed).
    contain_penalty = 0.0 if contains else 8.0
    dist_term = float(np.sqrt(dist2)) / max(seed_radius, 1.0)
    return contain_penalty + 2.0 * area_term + 0.35 * dist_term


def pick_component(
    components: list[dict[str, Any]],
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float = 10.0,
    ref_area: float | None = None,
) -> dict[str, Any] | None:
    """Choose the best connected component for a seed click."""
    if not components:
        return None

    if ref_area is None or ref_area <= 0:
        ref_area = expected_area_from_radius(seed_radius)

    scored: list[tuple[float, dict[str, Any]]] = []
    for comp in components:
        s = score_component(
            comp,
            seed_x=seed_x,
            seed_y=seed_y,
            ref_area=float(ref_area),
            seed_radius=seed_radius,
        )
        if s is not None:
            scored.append((s, comp))

    if scored:
        scored.sort(key=lambda t: t[0])
        return scored[0][1]

    # Soft fallback: nearest centroid among area-plausible comps.
    # In crowded fields, prefer components whose exterior contour contains
    # the seed point (hollow ring case) over pure centroid distance.
    soft: list[tuple[float, dict[str, Any]]] = []
    for comp in components:
        area = float(comp["area"])
        if ref_area > 0 and (area > ref_area * 3.5 or area < max(16.0, ref_area * 0.05)):
            continue
        cx, cy = comp["centroid"]
        dist2 = (cx - seed_x) ** 2 + (cy - seed_y) ** 2
        soft.append((dist2, comp))
    if not soft:
        return None
    soft_contain = [
        (d, c) for d, c in soft
        if component_exterior_contains(
            c["sub_mask"], bbox=c["bbox"], seed_x=seed_x, seed_y=seed_y
        )
    ]
    pool = soft_contain if soft_contain else soft
    pool.sort(key=lambda t: t[0])
    return pool[0][1]


def _dt_peak_coords(
    filled: np.ndarray,
    *,
    seed_radius: float,
    use_h_maxima: bool = True,
) -> np.ndarray:
    """Reliable DT peaks for marker-controlled watershed (thin-neck regime)."""
    from scipy import ndimage as ndi
    from skimage.feature import peak_local_max

    distance = ndi.distance_transform_edt(filled)
    min_distance = max(3, int(round(float(seed_radius) * 0.55)))
    if use_h_maxima:
        try:
            from skimage.morphology import h_maxima

            h = max(1.0, 0.22 * float(np.max(distance)))
            # Suppress shallow noise maxima before peak picking.
            suppressed = distance * (h_maxima(distance, h) > 0)
            if float(np.max(suppressed)) > 0:
                distance = suppressed + 1e-6 * ndi.distance_transform_edt(filled)
        except Exception:
            pass
    coords = peak_local_max(
        distance,
        min_distance=min_distance,
        labels=filled.astype(np.int32),
        exclude_border=False,
    )
    if coords is None:
        return np.zeros((0, 2), dtype=int)
    return np.asarray(coords)


def attempt_seeded_split(
    mask: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float = 10.0,
    force: bool = False,
) -> np.ndarray | None:
    """Marker-controlled watershed split when trustworthy multi-markers exist.

    Returns the seed-consistent child mask, or ``None`` if split is not
    trustworthy (e.g. single DT peak / broad contact). Caller should then
    consider polar-DP repair or fail closed — not invent markers.
    """
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2 or not np.any(binary):
        return None

    try:
        from scipy import ndimage as ndi
        from skimage.segmentation import watershed
    except Exception:
        return None

    try:
        filled = ndi.binary_fill_holes(binary)
    except Exception:
        filled = binary

    distance = ndi.distance_transform_edt(filled)
    coords = _dt_peak_coords(filled, seed_radius=seed_radius, use_h_maxima=True)
    if coords is None or len(coords) <= 1:
        if not force:
            return None
        # Forced path still needs ≥2 markers; inventing them over-segments.
        return None

    markers = np.zeros(filled.shape, dtype=np.int32)
    for idx, (py, px) in enumerate(coords):
        markers[int(py), int(px)] = idx + 1

    labels = watershed(-distance, markers, mask=filled)

    h, w = binary.shape
    sx = int(np.clip(round(seed_x), 0, w - 1))
    sy = int(np.clip(round(seed_y), 0, h - 1))

    seed_label = 0
    if labels[sy, sx] > 0:
        seed_label = int(labels[sy, sx])
    else:
        best_dist = float("inf")
        for py, px in coords:
            d = (float(px) - seed_x) ** 2 + (float(py) - seed_y) ** 2
            lab = int(labels[int(py), int(px)])
            if lab > 0 and d < best_dist:
                best_dist = d
                seed_label = lab

    if seed_label <= 0:
        return None

    isolated = labels == seed_label
    result = isolated & binary
    if not np.any(result):
        result = isolated
    # Reject tiny / empty children.
    if int(np.count_nonzero(result)) < 16:
        return None
    # Reject "split" that barely changed the mask (not a real separation).
    parent_area = int(np.count_nonzero(filled))
    child_area = int(np.count_nonzero(ndi.binary_fill_holes(result)))
    if parent_area > 0 and child_area > 0.92 * parent_area:
        return None
    return result


def isolate_seeded_mask(
    mask: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float = 10.0,
) -> np.ndarray:
    """Split neck-fused multi-object masks via DT watershed; keep seed's basin.

    Distance-transform peaks mark vesicle bodies; the thin neck is a saddle and
    becomes the watershed boundary. Works on solid blobs and hollow rings
    (rings are hole-filled only for marker placement; the returned mask is
    intersected with the original so membrane topology is preserved).

    Broad contacts that remain unimodal in the DT are **not** split here; the
    caller should use merge QC + polar-DP repair or fail closed.
    """
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2 or not np.any(binary):
        return binary

    split = attempt_seeded_split(
        binary,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_radius=seed_radius,
        force=False,
    )
    if split is not None:
        return split
    return binary


def pick_component_from_mask(
    mask: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float = 10.0,
    ref_area: float | None = None,
    min_area_px: int = 16,
) -> dict[str, Any] | None:
    from morphostack.core.pipeline import get_connected_components

    comps = get_connected_components(np.asarray(mask, dtype=bool), min_area_px=min_area_px)
    return pick_component(
        comps,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_radius=seed_radius,
        ref_area=ref_area,
    )


def component_mask_full(comp: dict[str, Any], shape: tuple[int, int]) -> np.ndarray:
    """Rasterize a component dict into a full-frame boolean mask."""
    out = np.zeros(shape, dtype=bool)
    ymin, ymax, xmin, xmax = comp["bbox"]
    out[ymin:ymax, xmin:xmax] = comp["sub_mask"]
    return out


def refine_component_near_point(
    comp: dict[str, Any],
    *,
    seed_x: float,
    seed_y: float,
    max_radius: float,
    ref_area: float | None = None,
) -> dict[str, Any]:
    """If a component is a multi-vesicle merge, keep only the lobe near the seed.

    Threshold often fuses touching GUV membranes into one connected component.
    Restricting to a disk around the tracked seed separates the target object
    well enough for interactive preview without a full watershed pipeline.
    """
    area = float(comp["area"])
    r = max(8.0, float(max_radius))
    # Only refine when the blob is clearly larger than a single object prior.
    if ref_area is not None and ref_area > 0 and area <= ref_area * 2.0:
        return comp
    if ref_area is None and area <= expected_area_from_radius(r) * 1.8:
        return comp

    ymin, ymax, xmin, xmax = comp["bbox"]
    sub = np.asarray(comp["sub_mask"], dtype=bool)
    h, w = sub.shape
    yy, xx = np.ogrid[0:h, 0:w]
    # Coordinates in full-image space for the disk.
    cy = yy + ymin
    cx = xx + xmin
    disk = (cx - seed_x) ** 2 + (cy - seed_y) ** 2 <= r * r
    clipped = sub & disk
    if not np.any(clipped):
        return comp

    # Re-label clipped mask; pick piece containing/near seed.
    full = np.zeros((ymax - ymin + 2, xmax - xmin + 2), dtype=bool)
    # Work in bbox-local coords for CC
    from morphostack.core.pipeline import get_connected_components

    # Build a temporary full-frame crop just for CC on clipped region
    local_mask = clipped
    # Fake components via get_connected_components expects 2d mask
    comps = get_connected_components(local_mask, min_area_px=16)
    if not comps:
        return comp

    # Shift component bboxes back to full-image coordinates
    shifted: list[dict[str, Any]] = []
    for c in comps:
        by0, by1, bx0, bx1 = c["bbox"]
        shifted.append(
            {
                "bbox": (by0 + ymin, by1 + ymin, bx0 + xmin, bx1 + xmin),
                "sub_mask": c["sub_mask"],
                "centroid": (c["centroid"][0] + xmin, c["centroid"][1] + ymin),
                "area": c["area"],
            }
        )

    picked = pick_component(
        shifted,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_radius=r,
        ref_area=ref_area if ref_area and ref_area > 0 else expected_area_from_radius(r) * 0.45,
    )
    return picked if picked is not None else comp


def contour_from_component(comp: dict[str, Any]) -> np.ndarray | None:
    """External contour in full-image coordinates (spline-smoothed)."""
    try:
        import cv2
    except Exception:
        ymin, ymax, xmin, xmax = comp["bbox"]
        return np.array(
            [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]],
            dtype=np.float64,
        )

    from morphostack.core.contours import smooth_contour_spline
    from morphostack.core.metrics import normalize_points

    binary = np.asarray(comp["sub_mask"], dtype=np.uint8) * 255
    # Close 1-2 px noise holes and membrane roughness before tracing.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if len(largest) < 3:
        return None
    pts = normalize_points(largest)
    ymin, ymax, xmin, xmax = comp["bbox"]
    pts = pts.copy()
    pts[:, 0] += xmin
    pts[:, 1] += ymin
    return smooth_contour_spline(pts)
