"""Competitive local isolation prototype (Packet 02).

Seed-centred polar/star-convex proposal + multi-label random-walker adjudication.

Default product path must NOT import side effects: call only when
``seeded_vesicle.is_competitive_isolation_enabled()`` is true.

Labels:
  1 — target (seed lumen / polar interior)
  2 — exterior / background
  3+ — proposed neighbours (markers outside the polar proposal)

Multi-body, flat-probability, or multi-component outcomes fail closed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class CompetitiveIsolationResult:
    """Crop-local isolation outcome (never full-frame)."""

    solid: np.ndarray | None
    ok: bool
    method: str
    reject_reason: str | None
    target_prob_mean: float
    competitor_margin: float
    n_neighbor_labels: int
    polar_ok: bool
    details: dict[str, Any]


def _empty_reject(reason: str, **details: Any) -> CompetitiveIsolationResult:
    return CompetitiveIsolationResult(
        solid=None,
        ok=False,
        method="competitive_reject",
        reject_reason=str(reason),
        target_prob_mean=0.0,
        competitor_margin=0.0,
        n_neighbor_labels=0,
        polar_ok=bool(details.get("polar_ok", False)),
        details=dict(details),
    )


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    solid = np.asarray(mask, dtype=bool)
    try:
        from scipy.ndimage import binary_fill_holes

        solid = binary_fill_holes(solid)
    except Exception:
        pass
    return solid.astype(bool)


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    try:
        from skimage.measure import label

        labeled = label(np.asarray(mask, dtype=bool), connectivity=2)
        return labeled, int(labeled.max())
    except Exception:
        m = np.asarray(mask, dtype=bool)
        if not np.any(m):
            return np.zeros(m.shape, dtype=np.int32), 0
        return m.astype(np.int32), 1


def _disk(shape: tuple[int, int], cx: float, cy: float, r: float) -> np.ndarray:
    h, w = shape
    yy, xx = np.ogrid[:h, :w]
    return (xx - float(cx)) ** 2 + (yy - float(cy)) ** 2 <= float(r) ** 2


def _adaptive_thr(values: np.ndarray) -> float | None:
    flat = np.asarray(values, dtype=np.float64).ravel()
    if flat.size == 0:
        return None
    lo, hi = float(np.min(flat)), float(np.max(flat))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo + 1e-3:
        return None
    try:
        from skimage.filters import threshold_otsu

        thr = float(threshold_otsu(flat))
        fg_frac = float(np.mean(flat > thr))
        if 0.05 <= fg_frac <= 0.85:
            return thr
    except Exception:
        pass
    p70 = float(np.percentile(flat, 70))
    return p70 if p70 > lo + 1e-12 else None


def _radial_ridge_proposal(
    crop: np.ndarray,
    local_cx: float,
    local_cy: float,
    R: float,
    *,
    n_angles: int = 96,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Cheap star-convex proposal: one ridge radius per angle in [0.35R, 1.05R].

    Returns (solid_fill, radii) or (None, None).
    """
    h, w = crop.shape
    arr = np.asarray(crop, dtype=np.float64)
    r_lo = max(2.0, 0.35 * R)
    r_hi = max(r_lo + 2.0, 1.05 * R)
    n_r = max(8, int(math.ceil(r_hi - r_lo)) + 1)
    radii = np.linspace(r_lo, r_hi, n_r)
    angles = np.linspace(0.0, 2.0 * math.pi, n_angles, endpoint=False)
    chosen = np.full(n_angles, np.nan, dtype=np.float64)
    bg = float(np.median(arr))
    peak_floor = max(bg * 1.08, float(np.percentile(arr, 60)))
    for i, th in enumerate(angles):
        ct, st = math.cos(th), math.sin(th)
        samples = []
        for r in radii:
            x = local_cx + r * ct
            y = local_cy + r * st
            ix, iy = int(round(x)), int(round(y))
            if 0 <= ix < w and 0 <= iy < h:
                samples.append(float(arr[iy, ix]))
            else:
                samples.append(bg)
        samples_a = np.asarray(samples, dtype=np.float64)
        # First significant local max walking outward (inner membrane of target).
        # Global argmax can jump to a brighter neighbour lobe.
        j_pick = None
        for j in range(1, len(samples_a) - 1):
            if samples_a[j] < peak_floor:
                continue
            if samples_a[j] >= samples_a[j - 1] and samples_a[j] >= samples_a[j + 1]:
                j_pick = j
                break
        if j_pick is None:
            # Fallback: first sample above floor.
            above = np.where(samples_a >= peak_floor)[0]
            if above.size:
                j_pick = int(above[0])
        if j_pick is None:
            continue
        chosen[i] = float(radii[j_pick])
    if int(np.count_nonzero(np.isfinite(chosen))) < max(12, n_angles // 4):
        return None, None
    # Fill angular gaps by circular nearest-neighbor so the solid is closed.
    finite = np.isfinite(chosen)
    if not np.all(finite):
        idx = np.arange(n_angles)
        known = idx[finite]
        for i in idx[~finite]:
            d = np.minimum((known - i) % n_angles, (i - known) % n_angles)
            chosen[i] = float(chosen[known[int(np.argmin(d))]])
    # Median smooth to kill single-ray spikes into a neighbour.
    order = max(1, n_angles // 24)
    sm = chosen.copy()
    for i in range(n_angles):
        win = [chosen[(i + k) % n_angles] for k in range(-order, order + 1)]
        sm[i] = float(np.median(win))
    # Reject multi-modal / oversized radius fields (bridge signature).
    r_med = float(np.median(sm))
    r_std = float(np.std(sm))
    spike_frac = float(np.mean(sm > r_med + max(3.0, 0.22 * R)))
    meta_bad = (r_std > 0.22 * R and spike_frac >= 0.10) or (r_med > 0.95 * R and r_std > 0.18 * R)
    if meta_bad:
        return None, sm
    # Expected hollow vesicle: membrane radius should not sit at the outer
    # search limit for most rays (that engulfs neighbours inside a large R).
    if float(np.mean(sm > 0.92 * R)) >= 0.45:
        return None, sm
    # Rasterize star-convex solid.
    yy, xx = np.ogrid[:h, :w]
    dx = xx.astype(np.float64) - local_cx
    dy = yy.astype(np.float64) - local_cy
    rr = np.hypot(dx, dy)
    ang = np.mod(np.arctan2(dy, dx), 2.0 * math.pi)
    bins = np.clip((ang / (2.0 * math.pi) * n_angles).astype(int), 0, n_angles - 1)
    limit = sm[bins]
    solid = rr <= limit
    if int(np.count_nonzero(solid)) < 16:
        return None, sm
    return solid, sm


def _polar_proposal(
    crop_raw: np.ndarray,
    local_cx: float,
    local_cy: float,
    R: float,
    disk_r: float,
) -> tuple[np.ndarray | None, bool, str]:
    """Star-convex / polar membrane proposal; crop-local solid or None.

    Returns (solid, ok, source) where source is polar_dp | radial_ridge | none.
    """
    try:
        from morphostack.core.polar_dp import segment_slice_polar_dp

        n_angles = max(360, int(2.0 * math.pi * max(R, 3.0)))
        safe_band = max(0.10, min(0.25, (disk_r - R) / max(R, 1.0)))
        polar = segment_slice_polar_dp(
            crop_raw,
            local_cx,
            local_cy,
            R,
            search_band=safe_band,
            n_angles=n_angles,
            smoothness_penalty=3.0,
            max_jump=2,
        )
        if polar.ok and polar.solid_mask is not None:
            solid = np.asarray(polar.solid_mask, dtype=bool)
            if int(np.count_nonzero(solid)) >= 16:
                return solid, True, "polar_dp"
    except Exception:
        pass

    # Fallback: deterministic radial ridge (works when polar-DP ridge tests fail).
    solid, _radii = _radial_ridge_proposal(crop_raw, local_cx, local_cy, R)
    if solid is not None:
        return solid, True, "radial_ridge"
    return None, False, "none"


def _neighbor_peaks(
    fg: np.ndarray,
    polar: np.ndarray | None,
    disk: np.ndarray,
    local_cx: float,
    local_cy: float,
    R: float,
    max_neighbors: int = 4,
) -> list[tuple[float, float]]:
    """Propose neighbour marker centres from FG peaks outside the polar body."""
    from scipy import ndimage as ndi

    work = np.asarray(fg, dtype=bool) & np.asarray(disk, dtype=bool)
    if polar is not None:
        # Keep a gap so neighbour markers do not sit on the target membrane.
        try:
            dil = ndi.binary_dilation(polar, iterations=2)
        except Exception:
            dil = polar
        work = work & ~dil
    # Exclude lumen / near-seed disk so peaks are true competitors.
    work = work & ~_disk(work.shape, local_cx, local_cy, max(3.0, 0.45 * R))
    if not np.any(work):
        return []

    # Distance-transform peaks of the exterior FG as neighbour seeds.
    try:
        dt = ndi.distance_transform_edt(work)
        from skimage.feature import peak_local_max

        coords = peak_local_max(
            dt,
            min_distance=max(3, int(0.25 * R)),
            threshold_abs=max(1.5, 0.08 * R),
            num_peaks=max_neighbors,
        )
        out: list[tuple[float, float]] = []
        for y, x in coords:
            out.append((float(x), float(y)))
        if out:
            return out
    except Exception:
        pass

    # Fallback: connected-component centroids of exterior FG.
    labeled, nlab = _label_components(work)
    cents: list[tuple[float, float, int]] = []
    for lab in range(1, nlab + 1):
        ys, xs = np.where(labeled == lab)
        if ys.size < 12:
            continue
        cents.append((float(xs.mean()), float(ys.mean()), int(ys.size)))
    cents.sort(key=lambda t: -t[2])
    return [(c[0], c[1],) for c in cents[:max_neighbors]]


def _build_markers(
    shape: tuple[int, int],
    disk: np.ndarray,
    local_cx: float,
    local_cy: float,
    R: float,
    polar: np.ndarray | None,
    neighbor_xy: list[tuple[float, float]],
) -> tuple[np.ndarray, int]:
    """Return markers (int32) and neighbour label count (labels 3..)."""
    h, w = shape
    markers = np.zeros((h, w), dtype=np.int32)
    yy, xx = np.ogrid[:h, :w]
    dist2 = (xx - local_cx) ** 2 + (yy - local_cy) ** 2

    lumen_r = max(2.0, min(0.35 * R, 8.0))
    # Target: lumen + optional polar interior (eroded) for stronger competition.
    target = dist2 <= lumen_r**2
    if polar is not None:
        try:
            from scipy.ndimage import binary_erosion

            core = binary_erosion(polar, iterations=max(1, int(0.08 * R)))
            if np.count_nonzero(core) >= 8:
                target = target | core
        except Exception:
            pass
    markers[target & disk] = 1

    # Exterior: outer annulus + crop border outside the seed disk.
    outer_r = max(R * 1.05, lumen_r + 3.0)
    exterior = disk & (dist2 >= outer_r**2)
    markers[exterior] = 2
    border = 1
    markers[:border, :] = 2
    markers[-border:, :] = 2
    markers[:, :border] = 2
    markers[:, -border:] = 2

    # Neighbours: small disks at proposed peaks (label 3+).
    n_lab = 0
    nr = max(2.0, min(0.18 * R, 5.0))
    for i, (nx, ny) in enumerate(neighbor_xy):
        lab = 3 + i
        nmask = (xx - nx) ** 2 + (yy - ny) ** 2 <= nr**2
        # Do not overwrite target lumen.
        place = nmask & disk & (markers == 0)
        if np.count_nonzero(place) < 2:
            continue
        markers[place] = lab
        n_lab += 1

    markers[~disk] = 0
    return markers, n_lab


def _star_convex_project(
    solid: np.ndarray,
    local_cx: float,
    local_cy: float,
    *,
    n_angles: int = 96,
) -> np.ndarray:
    """Project a solid mask to the star-convex region about (cx, cy)."""
    h, w = solid.shape
    solid = np.asarray(solid, dtype=bool)
    angles = np.linspace(0.0, 2.0 * math.pi, n_angles, endpoint=False)
    max_r = np.zeros(n_angles, dtype=np.float64)
    ys, xs = np.where(solid)
    if ys.size == 0:
        return np.zeros_like(solid)
    dx = xs.astype(np.float64) - local_cx
    dy = ys.astype(np.float64) - local_cy
    rr = np.hypot(dx, dy)
    ang = np.mod(np.arctan2(dy, dx), 2.0 * math.pi)
    bins = np.clip((ang / (2.0 * math.pi) * n_angles).astype(int), 0, n_angles - 1)
    for i in range(n_angles):
        sel = bins == i
        if np.any(sel):
            max_r[i] = float(np.max(rr[sel]))
    # fill empty bins
    known = np.where(max_r > 0)[0]
    if known.size == 0:
        return np.zeros_like(solid)
    for i in range(n_angles):
        if max_r[i] <= 0:
            d = np.minimum((known - i) % n_angles, (i - known) % n_angles)
            max_r[i] = float(max_r[known[int(np.argmin(d))]])
    yy, xx = np.ogrid[:h, :w]
    dx = xx.astype(np.float64) - local_cx
    dy = yy.astype(np.float64) - local_cy
    rr = np.hypot(dx, dy)
    ang = np.mod(np.arctan2(dy, dx), 2.0 * math.pi)
    bins = np.clip((ang / (2.0 * math.pi) * n_angles).astype(int), 0, n_angles - 1)
    return rr <= max_r[bins]


def _hard_admissible(
    solid: np.ndarray,
    *,
    local_cx: float,
    local_cy: float,
    R: float,
    polar: np.ndarray | None,
    ref_area: float | None,
    neighbor_xy: list[tuple[float, float]] | None = None,
) -> tuple[bool, str | None, dict[str, Any]]:
    """Topology / star-convex / area admissibility (fail-closed)."""
    solid = np.asarray(solid, dtype=bool)
    area = float(np.count_nonzero(solid))
    meta: dict[str, Any] = {"area": area}
    if area < 16:
        return False, "area_too_small", meta

    # Bound by user circle: multi-body bridges often still fit a large R disk,
    # so use a tighter area cap from polar area when available.
    max_area = float(math.pi * max(R, 1.0) ** 2) * 1.15
    min_area = max(16.0, float(math.pi * max(R, 1.0) ** 2) * 0.04)
    if polar is not None:
        p_area = float(np.count_nonzero(polar))
        if p_area >= 16:
            max_area = min(max_area, p_area * 1.35)
            min_area = max(min_area, p_area * 0.35)
    if ref_area is not None and ref_area > 0:
        min_area = max(min_area, ref_area * 0.15)
        max_area = min(max_area, ref_area * 2.2)
    meta["min_area"] = min_area
    meta["max_area"] = max_area
    if area > max_area:
        return False, "area_too_large", meta
    if area < min_area:
        return False, "area_too_small", meta

    labeled, nlab = _label_components(solid)
    meta["n_components"] = nlab
    if nlab != 1:
        return False, "multi_component", meta

    # Seed must lie in exterior of the single component (lumen or on FG).
    if not _component_contains(solid, local_cx, local_cy):
        ys, xs = np.where(solid)
        scx, scy = float(xs.mean()), float(ys.mean())
        if (scx - local_cx) ** 2 + (scy - local_cy) ** 2 > (0.55 * R) ** 2:
            return False, "center_outside", meta

    # Far-mass relative to seed (lobe/bridge).
    ys, xs = np.where(solid)
    dist = np.hypot(xs.astype(np.float64) - local_cx, ys.astype(np.float64) - local_cy)
    far_frac = float(np.count_nonzero(dist > 1.15 * R) / max(ys.size, 1))
    meta["far_frac_1p15R"] = far_frac
    if far_frac >= 0.08:
        return False, "far_mass_lobe", meta

    # Multi-body DT peaks inside the candidate.
    try:
        from morphostack.core.object_select import _dt_peak_coords

        peaks = _dt_peak_coords(solid, seed_radius=max(R * 0.85, 8.0), use_h_maxima=True)
        n_peaks = int(len(peaks)) if peaks is not None else 0
    except Exception:
        n_peaks = 0
    meta["n_dt_markers"] = n_peaks
    if n_peaks >= 2:
        return False, "multi_body_markers", meta

    # Neighbour marker centres must not lie inside the accepted solid.
    if neighbor_xy:
        h, w = solid.shape
        for nx, ny in neighbor_xy:
            ix, iy = int(round(nx)), int(round(ny))
            if 0 <= ix < w and 0 <= iy < h and bool(solid[iy, ix]):
                return False, "contains_neighbor_marker", meta

    # Star-convex agreement: solid must nearly equal its star-convex projection.
    star = _star_convex_project(solid, local_cx, local_cy)
    star_area = float(np.count_nonzero(star))
    inter = float(np.count_nonzero(solid & star))
    # solid should be subset of star; extra lobes outside star-convex hull are rare,
    # but non-star solid has solid pixels that expand star differently — compare IoU.
    union = float(np.count_nonzero(solid | star))
    star_iou = inter / union if union > 0 else 0.0
    meta["star_iou"] = star_iou
    meta["star_area"] = star_area
    if star_iou < 0.82:
        return False, "non_star_convex", meta

    # Polar / radial proposal agreement: isolated target should match proposal.
    if polar is not None:
        pol = np.asarray(polar, dtype=bool)
        inter_p = float(np.count_nonzero(solid & pol))
        union_p = float(np.count_nonzero(solid | pol))
        iou = inter_p / union_p if union_p > 0 else 0.0
        solid_only = float(np.count_nonzero(solid & ~pol)) / max(area, 1.0)
        meta["polar_iou"] = iou
        meta["solid_only_frac"] = solid_only
        if solid_only >= 0.22:
            return False, "polar_disagreement", meta
        if iou < 0.45:
            return False, "polar_disagreement", meta

    return True, None, meta


def _component_contains(solid: np.ndarray, cx: float, cy: float) -> bool:
    h, w = solid.shape
    ix, iy = int(round(cx)), int(round(cy))
    if 0 <= ix < w and 0 <= iy < h and bool(solid[iy, ix]):
        return True
    try:
        import cv2

        binary = np.asarray(solid, dtype=np.uint8) * 255
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False
        best = max(contours, key=cv2.contourArea)
        return float(cv2.pointPolygonTest(best, (float(cx), float(cy)), False)) >= 0.0
    except Exception:
        ys, xs = np.where(solid)
        if ys.size == 0:
            return False
        return float(xs.min()) <= cx <= float(xs.max()) and float(ys.min()) <= cy <= float(ys.max())


def isolate_competitive(
    crop: np.ndarray,
    crop_raw: np.ndarray,
    disk: np.ndarray,
    local_cx: float,
    local_cy: float,
    R: float,
    *,
    ref_area: float | None = None,
    min_prob_margin: float = 0.12,
    min_target_prob: float = 0.45,
) -> CompetitiveIsolationResult:
    """Run polar proposal + multi-label RW adjudication on a crop-local disk.

    Returns ok=True only for a single admissible target isolation.
    """
    crop = np.asarray(crop, dtype=np.float64)
    crop_raw = np.asarray(crop_raw, dtype=np.float64)
    disk = np.asarray(disk, dtype=bool)
    if crop.ndim != 2 or crop.shape != disk.shape:
        return _empty_reject("bad_shapes")

    R = float(max(R, 3.0))
    disk_r = math.sqrt(float(np.count_nonzero(disk)) / math.pi) if np.any(disk) else R * 1.15

    polar, polar_ok, polar_src = _polar_proposal(crop_raw, local_cx, local_cy, R, disk_r)
    if not polar_ok or polar is None:
        # Without a star-convex proposal, competitive isolation cannot safely
        # separate membranes — fail closed (no legacy flood-fill).
        return _empty_reject("polar_required", polar_ok=False, polar_src=polar_src)

    # FG evidence for neighbour proposals (threshold inside disk).
    thr = _adaptive_thr(crop[disk]) if np.any(disk) else None
    fg = np.zeros(crop.shape, dtype=bool)
    if thr is not None:
        fg = (crop >= float(thr)) & disk

    neighbors = _neighbor_peaks(fg, polar, disk, local_cx, local_cy, R)
    markers, n_neigh = _build_markers(
        crop.shape, disk, local_cx, local_cy, R, polar, neighbors
    )

    if not np.any(markers == 1) or not np.any(markers == 2):
        return _empty_reject(
            "markers_incomplete", polar_ok=polar_ok, n_neighbors=n_neigh, polar_src=polar_src
        )

    try:
        from skimage.segmentation import random_walker
        from skimage.util import img_as_float
    except Exception:
        return _empty_reject("rw_unavailable", polar_ok=polar_ok)

    data = img_as_float(crop.copy())
    dmin, dmax = float(np.min(data)), float(np.max(data))
    if dmax > dmin:
        data = (data - dmin) / (dmax - dmin)

    # Edge emphasis helps membrane competition (invert so membrane = barrier).
    try:
        from skimage.filters import sobel

        elev = sobel(data)
        emax = float(np.max(elev)) if elev.size else 0.0
        if emax > 1e-12:
            data = 0.65 * data + 0.35 * (1.0 - elev / emax)
    except Exception:
        pass

    try:
        # return_full_prob: (nlabels, H, W) ordered by label id 1..K
        probs = random_walker(
            data,
            markers,
            beta=90,
            mode="bf",
            return_full_prob=True,
        )
        labels = np.argmax(probs, axis=0).astype(np.int32) + 1
        labels[~disk] = 0
        # Zero out inactive
        labels[markers == -1] = 0
    except Exception:
        try:
            labels = random_walker(data, markers, beta=90, mode="bf")
            probs = None
        except Exception:
            return _empty_reject("rw_failed", polar_ok=polar_ok, n_neighbors=n_neigh)

    solid = (labels == 1) & disk
    # Constrain to star-convex proposal before fill — cuts RW flood into neighbours.
    solid = solid & polar
    solid = _fill_holes(solid) & disk & polar
    if not np.any(solid):
        return _empty_reject(
            "empty_target",
            polar_ok=polar_ok,
            n_neighbors=n_neigh,
            polar_src=polar_src,
        )

    # Probability competition margin (when available).
    target_prob_mean = 0.0
    competitor_margin = 1.0
    if probs is not None and probs.shape[0] >= 1:
        # Label order in return_full_prob follows sorted unique positive labels.
        uniq = sorted(int(u) for u in np.unique(markers) if u > 0)
        try:
            t_idx = uniq.index(1)
        except ValueError:
            t_idx = 0
        p_tgt = probs[t_idx]
        target_prob_mean = float(np.mean(p_tgt[solid])) if np.any(solid) else 0.0
        # Competitor max mean on solid region
        comp_means = []
        for i, lab in enumerate(uniq):
            if lab == 1:
                continue
            comp_means.append(float(np.mean(probs[i][solid])))
        best_comp = max(comp_means) if comp_means else 0.0
        competitor_margin = float(target_prob_mean - best_comp)
        if target_prob_mean < min_target_prob:
            return CompetitiveIsolationResult(
                solid=None,
                ok=False,
                method="competitive_reject",
                reject_reason="low_target_prob",
                target_prob_mean=target_prob_mean,
                competitor_margin=competitor_margin,
                n_neighbor_labels=n_neigh,
                polar_ok=polar_ok,
                details={"best_comp": best_comp, "polar_src": polar_src},
            )
        if n_neigh > 0 and competitor_margin < min_prob_margin:
            return CompetitiveIsolationResult(
                solid=None,
                ok=False,
                method="competitive_reject",
                reject_reason="ambiguous_competition",
                target_prob_mean=target_prob_mean,
                competitor_margin=competitor_margin,
                n_neighbor_labels=n_neigh,
                polar_ok=polar_ok,
                details={"best_comp": best_comp, "polar_src": polar_src},
            )

    ok, reason, meta = _hard_admissible(
        solid,
        local_cx=local_cx,
        local_cy=local_cy,
        R=R,
        polar=polar,
        ref_area=ref_area,
        neighbor_xy=neighbors,
    )
    meta = dict(meta)
    meta["polar_src"] = polar_src
    if not ok:
        return CompetitiveIsolationResult(
            solid=None,
            ok=False,
            method="competitive_reject",
            reject_reason=reason,
            target_prob_mean=target_prob_mean,
            competitor_margin=competitor_margin,
            n_neighbor_labels=n_neigh,
            polar_ok=polar_ok,
            details=meta,
        )

    return CompetitiveIsolationResult(
        solid=solid,
        ok=True,
        method="competitive_polar_rw",
        reject_reason=None,
        target_prob_mean=target_prob_mean,
        competitor_margin=competitor_margin,
        n_neighbor_labels=n_neigh,
        polar_ok=polar_ok,
        details=meta,
    )
