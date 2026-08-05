"""Loop hierarchy extraction and even-odd rasterization for RBC slices."""

from __future__ import annotations

import numpy as np

from morphostack.core.metrics import normalize_points
from morphostack.core.rbc_models import RbcSliceTopology, RbcTopologyIssue


def _contour_xy(contour: np.ndarray) -> np.ndarray:
    """OpenCV contour (N,1,2) or (N,2) → float (N, 2) xy."""
    pts = np.asarray(contour, dtype=np.float64)
    if pts.ndim == 3:
        pts = pts.reshape(-1, 2)
    return normalize_points(pts)


def rasterize_rbc_topology(
    topology: RbcSliceTopology,
    shape: tuple[int, int],
) -> np.ndarray:
    """Rasterize outer/inner loops with even-odd parity into a boolean mask."""

    h, w = int(shape[0]), int(shape[1])
    out = np.zeros((h, w), dtype=np.uint8)
    if topology.outer_loop_xy is None or len(topology.outer_loop_xy) < 3:
        return out.astype(bool)

    try:
        import cv2
    except Exception:
        # Fallback: return stored occupancy when available.
        if topology.occupancy_mask is not None:
            return np.asarray(topology.occupancy_mask, dtype=bool)
        return out.astype(bool)

    outer = np.round(np.asarray(topology.outer_loop_xy, dtype=np.float64)).astype(np.int32)
    cv2.fillPoly(out, [outer.reshape(-1, 1, 2)], 1)
    for inner in topology.inner_loops_xy:
        if inner is None or len(inner) < 3:
            continue
        hole = np.round(np.asarray(inner, dtype=np.float64)).astype(np.int32)
        cv2.fillPoly(out, [hole.reshape(-1, 1, 2)], 0)
    return out.astype(bool)


def _touches_border(mask: np.ndarray) -> bool:
    m = np.asarray(mask, dtype=bool)
    if m.size == 0:
        return False
    return bool(
        np.any(m[0, :])
        or np.any(m[-1, :])
        or np.any(m[:, 0])
        or np.any(m[:, -1])
    )


def extract_rbc_slice_topology(
    mask: np.ndarray,
    *,
    frame_index: int,
    method: str = "",
    center_xy: tuple[float, float] | None = None,
    merge_suspect: bool = False,
    min_area_px: float = 16.0,
) -> RbcSliceTopology:
    """Extract one outer loop and zero or more hole loops from a binary mask.

    Multiple significant outer components or unsupported nesting fail closed.
    """

    binary = np.asarray(mask, dtype=bool)
    issues: list[RbcTopologyIssue] = []

    if binary.ndim != 2:
        raise ValueError("extract_rbc_slice_topology expects a 2D mask")

    if not np.any(binary):
        return RbcSliceTopology(
            frame_index=int(frame_index),
            outer_loop_xy=None,
            inner_loops_xy=(),
            occupancy_mask=None,
            issues=(RbcTopologyIssue.EMPTY,),
            ok=False,
            method=method,
            center_xy=center_xy,
            area_px=0.0,
            merge_suspect=bool(merge_suspect),
        )

    try:
        import cv2
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("OpenCV is required for RBC topology extraction") from exc

    u8 = (binary.astype(np.uint8) * 255)
    contours, hierarchy = cv2.findContours(u8, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if not contours or hierarchy is None:
        return RbcSliceTopology(
            frame_index=int(frame_index),
            outer_loop_xy=None,
            inner_loops_xy=(),
            occupancy_mask=None,
            issues=(RbcTopologyIssue.EMPTY,),
            ok=False,
            method=method,
            center_xy=center_xy,
            merge_suspect=bool(merge_suspect),
        )

    hier = hierarchy[0]
    roots = [i for i in range(len(contours)) if int(hier[i][3]) == -1]
    # Prefer mask pixel count for significance: OpenCV contour area under-counts
    # small digital objects relative to the binary occupancy area.
    mask_area = float(np.count_nonzero(binary))
    if mask_area < float(min_area_px) and not roots:
        return RbcSliceTopology(
            frame_index=int(frame_index),
            outer_loop_xy=None,
            inner_loops_xy=(),
            occupancy_mask=None,
            issues=(RbcTopologyIssue.EMPTY,),
            ok=False,
            method=method,
            center_xy=center_xy,
            merge_suspect=bool(merge_suspect),
        )
    # Keep any root with contour area >= 1 px; multi-root uses contour area ranking.
    significant_roots = [
        i for i in roots if float(cv2.contourArea(contours[i])) >= 1.0
    ]
    if not significant_roots:
        # Fall back to largest contour as outer if hierarchy roots filtered oddly.
        areas = [float(cv2.contourArea(c)) for c in contours]
        best = int(np.argmax(areas)) if areas else -1
        if best < 0 or areas[best] < 1.0:
            return RbcSliceTopology(
                frame_index=int(frame_index),
                outer_loop_xy=None,
                inner_loops_xy=(),
                occupancy_mask=None,
                issues=(RbcTopologyIssue.EMPTY,),
                ok=False,
                method=method,
                center_xy=center_xy,
                merge_suspect=bool(merge_suspect),
            )
        significant_roots = [best]
    if len(significant_roots) > 1:
        # Ambiguous only when multiple roots are both material vs mask area.
        material = [
            i
            for i in significant_roots
            if float(cv2.contourArea(contours[i])) >= max(4.0, 0.15 * mask_area)
        ]
        if len(material) > 1:
            return RbcSliceTopology(
                frame_index=int(frame_index),
                outer_loop_xy=None,
                inner_loops_xy=(),
                occupancy_mask=None,
                issues=(RbcTopologyIssue.MULTIPLE_OUTER_COMPONENTS,),
                ok=False,
                method=method,
                center_xy=center_xy,
                merge_suspect=True,
            )
        significant_roots = material or [
            max(significant_roots, key=lambda i: float(cv2.contourArea(contours[i])))
        ]

    root = significant_roots[0]
    outer_xy = _contour_xy(contours[root])
    inners: list[np.ndarray] = []
    child = int(hier[root][2])
    while child != -1:
        if float(cv2.contourArea(contours[child])) >= 4.0:
            # Grandchildren would be islands inside holes — unsupported for measured occupancy.
            gchild = int(hier[child][2])
            if gchild != -1 and float(cv2.contourArea(contours[gchild])) >= 4.0:
                return RbcSliceTopology(
                    frame_index=int(frame_index),
                    outer_loop_xy=outer_xy,
                    inner_loops_xy=(),
                    occupancy_mask=None,
                    issues=(RbcTopologyIssue.UNSUPPORTED_NESTING,),
                    ok=False,
                    method=method,
                    center_xy=center_xy,
                    merge_suspect=bool(merge_suspect),
                )
            inners.append(_contour_xy(contours[child]))
        child = int(hier[child][0])

    topo = RbcSliceTopology(
        frame_index=int(frame_index),
        outer_loop_xy=outer_xy,
        inner_loops_xy=tuple(inners),
        occupancy_mask=None,
        issues=(),
        ok=True,
        method=method,
        center_xy=center_xy,
        merge_suspect=bool(merge_suspect),
    )
    rebuilt = rasterize_rbc_topology(topo, binary.shape)
    # Tolerate 1-px contour discretization differences on the boundary.
    xor = np.logical_xor(rebuilt, binary)
    mismatch_frac = float(np.count_nonzero(xor)) / float(max(binary.size, 1))
    if mismatch_frac > 0.02 and int(np.count_nonzero(xor)) > 32:
        issues.append(RbcTopologyIssue.RASTER_MISMATCH)
        # Prefer the source mask when hierarchy parse drifted.
        occupancy = binary.copy()
    else:
        occupancy = rebuilt

    if _touches_border(occupancy):
        issues.append(RbcTopologyIssue.LATERAL_CLIPPING)

    area = float(np.count_nonzero(occupancy))
    if center_xy is None and area > 0:
        ys, xs = np.where(occupancy)
        center_xy = (float(xs.mean()), float(ys.mean()))

    ok = RbcTopologyIssue.MULTIPLE_OUTER_COMPONENTS not in issues and RbcTopologyIssue.UNSUPPORTED_NESTING not in issues
    # Clipping and mild raster mismatch are reported but do not alone void the slice;
    # Phase 3 QC decides capability. Nested/multi-outer already returned above.
    if RbcTopologyIssue.RASTER_MISMATCH in issues and mismatch_frac > 0.08:
        ok = False

    # Use occupancy pixel count (not contour area) for the empty-size gate.
    return RbcSliceTopology(
        frame_index=int(frame_index),
        outer_loop_xy=outer_xy,
        inner_loops_xy=tuple(inners),
        occupancy_mask=occupancy,
        issues=tuple(issues),
        ok=ok and area >= max(4.0, float(min_area_px) * 0.25),
        method=method,
        center_xy=center_xy,
        area_px=area,
        merge_suspect=bool(merge_suspect),
    )
