"""Experimental multi-scale Gaussian contour proposals with raw-image authority."""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

CONSENSUS_SIGMAS: tuple[float, ...] = (0.0, 0.75, 1.5, 3.0)
CONSENSUS_IOU_MIN = 0.75


@dataclass(frozen=True)
class ConsensusProposal:
    solid: np.ndarray | None
    sigmas: tuple[float, ...]
    candidate_count: int
    dominant_cluster_size: int
    agreement: float
    boundary_spread: float
    raw_edge_support: float
    confidence: float
    reject_reason: str | None = None


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    aa = np.asarray(a, dtype=bool)
    bb = np.asarray(b, dtype=bool)
    union = int(np.count_nonzero(aa | bb))
    if union == 0:
        return 0.0
    return float(np.count_nonzero(aa & bb)) / float(union)


def raw_edge_support(image: np.ndarray, solid: np.ndarray, disk: np.ndarray) -> float:
    from scipy.ndimage import binary_erosion, sobel

    raw = np.nan_to_num(np.asarray(image, dtype=np.float64), copy=True)
    mask = np.asarray(solid, dtype=bool)
    boundary = mask & ~binary_erosion(mask, iterations=1)
    if not np.any(boundary):
        return 0.0
    grad = np.hypot(sobel(raw, axis=0), sobel(raw, axis=1))
    scale_values = grad[np.asarray(disk, dtype=bool)]
    if scale_values.size == 0:
        return 0.0
    scale = float(np.percentile(scale_values, 95))
    if not np.isfinite(scale) or scale <= 1e-12:
        return 0.0
    return float(np.clip(np.mean(grad[boundary]) / scale, 0.0, 1.0))


def _shape_score(mask: np.ndarray, profile: str) -> float:
    from scipy.ndimage import binary_erosion
    from skimage.morphology import convex_hull_image
    from skimage.measure import perimeter_crofton

    solid = np.asarray(mask, dtype=bool)
    area = float(np.count_nonzero(solid))
    if area < 3:
        return 0.0
    perimeter = max(float(perimeter_crofton(solid, directions=4)), 1e-9)
    circularity = float(np.clip(4.0 * math.pi * area / (perimeter * perimeter), 0.0, 1.0))
    hull_area = float(np.count_nonzero(convex_hull_image(solid)))
    solidity = float(np.clip(area / max(hull_area, 1.0), 0.0, 1.0))
    boundary = solid & ~binary_erosion(solid)
    ys, xs = np.where(boundary)
    ay, ax = np.where(solid)
    if xs.size < 3 or ax.size == 0:
        radial = 0.0
    else:
        cx, cy = float(ax.mean()), float(ay.mean())
        radii = np.hypot(xs - cx, ys - cy)
        radial = float(np.clip(1.0 - np.std(radii) / max(np.mean(radii), 1e-9), 0.0, 1.0))
    if str(profile).lower() == "rbc":
        return 0.15 * circularity + 0.15 * radial + 0.70 * solidity
    return 0.55 * circularity + 0.35 * radial + 0.10 * solidity


def _dominant_cluster(candidates: list[np.ndarray]) -> list[int]:
    n = len(candidates)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            if mask_iou(candidates[i], candidates[j]) >= CONSENSUS_IOU_MIN:
                union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return max(groups.values(), key=lambda g: (len(g), -min(g))) if groups else []



def _radial_boundary_candidate(
    view: np.ndarray,
    local_cx: float,
    local_cy: float,
    radius: float,
    *,
    n_angles: int,
) -> np.ndarray | None:
    """Vectorized first-ridge proposal for one Gaussian view."""
    from scipy.ndimage import median_filter

    arr = np.asarray(view, dtype=np.float64)
    h, w = arr.shape
    r_lo = max(2.0, 0.35 * radius)
    r_hi = max(r_lo + 2.0, 1.05 * radius)
    radii = np.linspace(r_lo, r_hi, max(8, int(math.ceil(r_hi - r_lo)) + 1))
    angles = np.linspace(0.0, 2.0 * math.pi, n_angles, endpoint=False)
    xs = np.clip(
        np.rint(local_cx + np.cos(angles)[:, None] * radii[None, :]).astype(int),
        0,
        w - 1,
    )
    ys = np.clip(
        np.rint(local_cy + np.sin(angles)[:, None] * radii[None, :]).astype(int),
        0,
        h - 1,
    )
    samples = arr[ys, xs]
    floor = max(float(np.median(arr)) * 1.08, float(np.percentile(arr, 60)))
    local_max = (
        (samples[:, 1:-1] >= floor)
        & (samples[:, 1:-1] >= samples[:, :-2])
        & (samples[:, 1:-1] >= samples[:, 2:])
    )
    has_local = np.any(local_max, axis=1)
    local_index = np.argmax(local_max, axis=1) + 1
    above = samples >= floor
    has_above = np.any(above, axis=1)
    above_index = np.argmax(above, axis=1)
    chosen_index = np.where(has_local, local_index, above_index)
    valid = has_local | has_above
    if int(np.count_nonzero(valid)) < max(12, n_angles // 4):
        return None

    chosen = radii[chosen_index].astype(np.float64)
    if not np.all(valid):
        known = np.flatnonzero(valid)
        missing = np.flatnonzero(~valid)
        delta = np.abs(known[:, None] - missing[None, :])
        circular_delta = np.minimum(delta, n_angles - delta)
        chosen[missing] = chosen[known[np.argmin(circular_delta, axis=0)]]

    order = max(1, n_angles // 24)
    smooth = median_filter(chosen, size=2 * order + 1, mode="wrap")
    r_med = float(np.median(smooth))
    r_std = float(np.std(smooth))
    spike_frac = float(np.mean(smooth > r_med + max(3.0, 0.22 * radius)))
    if (r_std > 0.22 * radius and spike_frac >= 0.10) or (
        r_med > 0.95 * radius and r_std > 0.18 * radius
    ):
        return None
    if float(np.mean(smooth > 0.92 * radius)) >= 0.45:
        return None

    yy, xx = np.ogrid[:h, :w]
    rr = np.hypot(xx.astype(np.float64) - local_cx, yy.astype(np.float64) - local_cy)
    theta = np.mod(np.arctan2(yy - local_cy, xx - local_cx), 2.0 * math.pi)
    bins = np.clip((theta / (2.0 * math.pi) * n_angles).astype(int), 0, n_angles - 1)
    solid = rr <= smooth[bins]
    return solid if int(np.count_nonzero(solid)) >= 16 else None

def propose_multiscale_consensus(
    crop_raw: np.ndarray,
    disk: np.ndarray,
    local_cx: float,
    local_cy: float,
    radius: float,
    *,
    ref_area: float | None,
    profile: str,
) -> ConsensusProposal:
    """Return a deterministic medoid proposal; all evidence is checked on raw."""
    from morphostack.core.seeded_vesicle import (
        _adaptive_threshold_sparse,
        _fill_holes,
        _gaussian,
        _pick_component_in_disk,
    )

    raw = np.asarray(crop_raw, dtype=np.float64)
    hard_disk = np.asarray(disk, dtype=bool)
    if raw.shape != hard_disk.shape or not np.any(hard_disk):
        return ConsensusProposal(None, CONSENSUS_SIGMAS, 0, 0, 0.0, 1.0, 0.0, 0.0, "invalid_crop")
    if not np.all(np.isfinite(raw[hard_disk])):
        return ConsensusProposal(None, CONSENSUS_SIGMAS, 0, 0, 0.0, 1.0, 0.0, 0.0, "non_finite_input")
    raw_values = raw[hard_disk]
    raw_threshold = _adaptive_threshold_sparse(raw_values)
    if raw_threshold is None:
        return ConsensusProposal(
            None, CONSENSUS_SIGMAS, 0, 0, 0.0, 1.0, 0.0, 0.0, "insufficient_candidates"
        )
    # Build a filled adaptive-threshold proposal when it has coherent topology;
    # otherwise use the scale-local gradient ridge to close fragmented membranes.
    # This is a composite soft-shape choice, never a circularity-only rejection.
    from scipy.ndimage import sobel
    from skimage.measure import label

    raw_labels = label((raw >= float(raw_threshold)) & hard_disk, connectivity=2)
    use_threshold_topology = int(raw_labels.max()) == 1

    candidates: list[np.ndarray] = []
    candidate_sigmas: list[float] = []
    for sigma in CONSENSUS_SIGMAS:
        view = raw if sigma == 0.0 else _gaussian(raw, sigma=sigma)
        threshold = _adaptive_threshold_sparse(view[hard_disk])
        if threshold is None:
            continue
        picked = (
            _pick_component_in_disk(
                (view >= float(threshold)) & hard_disk,
                hard_disk,
                local_cx,
                local_cy,
                radius,
                ref_area=ref_area,
                cheap=True,
            )
            if use_threshold_topology
            else None
        )
        threshold_solid = (
            None
            if picked is None
            else _fill_holes(np.asarray(picked, dtype=bool)) & hard_disk
        )
        ridge_view = np.hypot(sobel(view, axis=0), sobel(view, axis=1))
        radial_solid = _radial_boundary_candidate(
            ridge_view,
            local_cx,
            local_cy,
            radius,
            n_angles=360,
        )
        if (
            threshold_solid is not None
            and _shape_score(threshold_solid, profile) >= 0.55
        ):
            solid = threshold_solid
        else:
            solid = radial_solid if radial_solid is not None else threshold_solid
        if solid is None:
            continue
        solid = np.asarray(solid, dtype=bool) & hard_disk
        area = float(np.count_nonzero(solid))
        if area < 16:
            continue
        if ref_area is not None and ref_area > 0 and not (
            0.2 * ref_area <= area <= 2.5 * ref_area
        ):
            continue
        candidates.append(solid)
        candidate_sigmas.append(float(sigma))

    if len(candidates) < 3:
        return ConsensusProposal(
            None, tuple(candidate_sigmas), len(candidates), 0, 0.0, 1.0, 0.0, 0.0, "insufficient_candidates"
        )
    dominant = _dominant_cluster(candidates)
    if len(dominant) < 3:
        return ConsensusProposal(
            None, tuple(candidate_sigmas), len(candidates), len(dominant), 0.0, 1.0, 0.0, 0.0, "no_dominant_cluster"
        )

    scored: list[tuple[float, float, float, int]] = []
    for index in dominant:
        peers = [mask_iou(candidates[index], candidates[j]) for j in dominant if j != index]
        agreement = float(np.mean(peers)) if peers else 1.0
        edge = raw_edge_support(raw, candidates[index], hard_disk)
        shape = _shape_score(candidates[index], profile)
        score = 0.55 * agreement + 0.30 * edge + 0.15 * shape
        scored.append((score, agreement, edge, index))
    # The authoritative proposal is the cluster medoid (maximum mean IoU).
    # The weighted evidence score is retained for confidence/fail-closed gates.
    score, agreement, edge, chosen = max(scored, key=lambda item: (item[1], item[0], -item[3]))
    spread = float(np.mean([1.0 - mask_iou(candidates[chosen], candidates[j]) for j in dominant]))
    reject = None
    if agreement < CONSENSUS_IOU_MIN or edge < 0.05 or score < 0.50:
        reject = "weak_consensus_evidence"
    return ConsensusProposal(
        None if reject else candidates[chosen],
        tuple(candidate_sigmas),
        len(candidates),
        len(dominant),
        agreement,
        spread,
        edge,
        float(score),
        reject,
    )
