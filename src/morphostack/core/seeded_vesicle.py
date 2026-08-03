"""Circle-constrained single-vesicle segmentation (Fiji / LimeSeg model).

The user circle radius R is law (OvalRoi-style). Segmentation is restricted to a
hard disk around the seed center so neighboring membranes cannot merge in.
Contours and solid masks are always returned in full-frame coordinates; crop is
compute-only.

Z tracking reuses the same R on every slice, updates the center to the contour
centroid (GUVs float), and applies IoU + multi-feature continuity gates.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import numpy as np

from morphostack.core.metrics import normalize_points, polygon_area, polygon_perimeter
from morphostack.core.slice_qc import SliceQC


@dataclass(frozen=True)
class SeededSliceResult:
    contour_xy: np.ndarray | None  # (N, 2) full-image coords x,y
    solid_mask: np.ndarray | None  # full-frame bool or None
    center_xy: tuple[float, float]
    area_px: float
    perimeter_px: float
    method: str
    ok: bool
    # Optional QC (diagnostics / merge suspicion). Never replaces the contour.
    merge_suspect: bool = False
    qc: SliceQC | None = None
    # Actual intensity gate used for this slice when method is threshold-based
    # (adaptive local Otsu/percentile inside the seed disk). None for polar_dp
    # and other non-threshold methods. Not the UI slider value.
    effective_threshold: float | None = None
    # Full-image XY center of the search/seed disk used for this frame (clipping
    # diagnostics). Distinct from center_xy when the contour centroid drifts.
    search_center_xy: tuple[float, float] | None = None
    consensus_sigmas: tuple[float, ...] | None = None
    consensus_candidate_count: int | None = None
    consensus_dominant_cluster_size: int | None = None
    consensus_agreement: float | None = None
    consensus_boundary_spread: float | None = None
    consensus_raw_edge_support: float | None = None
    consensus_confidence: float | None = None
    consensus_reject_reason: str | None = None


def effective_seed_radius(seed_radius: float | None) -> float:
    """User circle radius; floor 15 only when radius is missing/invalid."""
    if seed_radius is None:
        return 15.0
    r = float(seed_radius)
    if not np.isfinite(r) or r <= 0.0:
        return 15.0
    return r


def _gaussian(image: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    try:
        from skimage.filters import gaussian

        return gaussian(np.asarray(image, dtype=np.float64), sigma=sigma, preserve_range=True)
    except Exception:
        return np.asarray(image, dtype=np.float64)


# Production bilateral: skimage only (Packet 05 OpenCV experiment REJECTED / Packet 10 deleted).
# Historical reject evidence: architecture-reset packet-05-bilateral/.


def _bilateral(img: np.ndarray, sigma_spatial: float = 1.5) -> np.ndarray:
    """Edge-preserving bilateral filter (skimage denoise_bilateral).

    Peak-normalizes, filters, then restores peak. On failure falls back to Gaussian.
    """
    try:
        from skimage.restoration import denoise_bilateral

        img_f = np.asarray(img, dtype=np.float64)
        peak = float(np.max(img_f)) if img_f.size else 0.0
        if peak > 0:
            img_f = img_f / peak
        # sigma_color=None -> image.std() on the normalized image (skimage default).
        out = denoise_bilateral(img_f, sigma_spatial=float(sigma_spatial), channel_axis=None)
        return np.asarray(out, dtype=np.float64) * (peak if peak > 0 else 1.0)
    except Exception:
        return _gaussian(img, sigma=float(sigma_spatial))


# ---------------------------------------------------------------------------
# Neutral exact-path stage counters (Packet 01 profiling / attribution).
# Opt-in staged-QC / MorphGAC-skip science switches deleted (Packet 06 REJECT / Packet 10).
# ---------------------------------------------------------------------------


@dataclass
class ExactPathCounters:
    """Process-local counters for segment_slice_seeded attribution."""

    segment_calls: int = 0
    morphgac_calls: int = 0
    morphgac_skipped_clean: int = 0
    full_qc_skipped_clean: int = 0
    split_attempts: int = 0
    polar_repair_attempts: int = 0
    merge_rejects: int = 0
    accepted: int = 0
    clean_frame_hits: int = 0
    suspicion_escalations: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "segment_calls": int(self.segment_calls),
            "morphgac_calls": int(self.morphgac_calls),
            "morphgac_skipped_clean": int(self.morphgac_skipped_clean),
            "full_qc_skipped_clean": int(self.full_qc_skipped_clean),
            "split_attempts": int(self.split_attempts),
            "polar_repair_attempts": int(self.polar_repair_attempts),
            "merge_rejects": int(self.merge_rejects),
            "accepted": int(self.accepted),
            "clean_frame_hits": int(self.clean_frame_hits),
            "suspicion_escalations": int(self.suspicion_escalations),
        }

    def reset(self) -> None:
        self.segment_calls = 0
        self.morphgac_calls = 0
        self.morphgac_skipped_clean = 0
        self.full_qc_skipped_clean = 0
        self.split_attempts = 0
        self.polar_repair_attempts = 0
        self.merge_rejects = 0
        self.accepted = 0
        self.clean_frame_hits = 0
        self.suspicion_escalations = 0


_EXACT_PATH_COUNTERS = ExactPathCounters()


def reset_exact_path_counters() -> None:
    _EXACT_PATH_COUNTERS.reset()


def get_exact_path_counters() -> dict[str, int]:
    return _EXACT_PATH_COUNTERS.as_dict()


def reset_qc_refinement_counters() -> None:
    from morphostack.core.slice_qc import reset_qc_stage_counters

    reset_exact_path_counters()
    reset_qc_stage_counters()


def get_qc_refinement_counters() -> dict[str, int]:
    from morphostack.core.slice_qc import get_qc_stage_counters

    out = dict(get_qc_stage_counters())
    out.update(get_exact_path_counters())
    return out


# ---------------------------------------------------------------------------
# Packet 02 / 11 — competitive polar + multi-label RW isolation
# ---------------------------------------------------------------------------
# Production default: OFF (legacy). Packet 11 exposes request/job-scoped opt-in;
# do not flip this process-global around concurrent API work.
# Prefer explicit ``competitive_isolation=`` on segment/track/extend.

_COMPETITIVE_ISOLATION_ENABLED: bool = False

# Distinct cache/job identity tokens (never share entries across variants).
SEEDED_EXACT_MODE_LEGACY: str = "seeded_exact_legacy"
SEEDED_EXACT_MODE_COMPETITIVE: str = "seeded_exact_competitive_v1"
SEEDED_EXACT_MODE_MULTISCALE: str = "seeded_exact_multiscale_consensus_v1"
# Honest UI/API warning (Packet 05/11 real-data gate incomplete).
COMPETITIVE_TRACKING_WARNING: str = "Touching-vesicle real-data sign-off incomplete."


def set_competitive_isolation_enabled(enabled: bool = True) -> bool:
    """Process-global test/diagnostic switch. Prefer request-scoped args in API."""
    global _COMPETITIVE_ISOLATION_ENABLED
    _COMPETITIVE_ISOLATION_ENABLED = bool(enabled)
    return _COMPETITIVE_ISOLATION_ENABLED


def is_competitive_isolation_enabled() -> bool:
    return bool(_COMPETITIVE_ISOLATION_ENABLED)


def exact_tracking_mode_token(competitive: bool, multiscale_consensus: bool = False) -> str:
    """Stable tracking_mode for TrackingCacheKey / manifests."""
    if competitive and multiscale_consensus:
        raise ValueError("competitive and multi-scale consensus modes are mutually exclusive")
    if multiscale_consensus:
        return SEEDED_EXACT_MODE_MULTISCALE
    return SEEDED_EXACT_MODE_COMPETITIVE if competitive else SEEDED_EXACT_MODE_LEGACY


def competitive_from_tracking_mode(mode: str | None) -> bool:
    """True only for the explicit competitive experimental mode token."""
    token = str(mode or "").strip()
    return token == SEEDED_EXACT_MODE_COMPETITIVE


def multiscale_from_tracking_mode(mode: str | None) -> bool:
    return str(mode or "").strip() == SEEDED_EXACT_MODE_MULTISCALE


def resolve_competitive_isolation(competitive_isolation: bool | None) -> bool:
    """Resolve segment/track competitive flag (explicit arg wins over process global)."""
    if competitive_isolation is not None:
        return bool(competitive_isolation)
    return is_competitive_isolation_enabled()


# ---------------------------------------------------------------------------
# Tracking recovery Packet 01 — neutral stage/decision instrumentation
# ---------------------------------------------------------------------------
# Off by default. When disabled, scientific outputs must match the uninstrumented
# path bit-for-bit (no extra allocations on the hot path beyond a bool load).
# When enabled, records stage timings, association decisions, frame commits, and
# optional cache/job observe events without changing masks/methods/statuses.


@dataclass
class _TrackingInstrState:
    """Mutable process-local collector (enabled sessions only)."""

    enabled: bool = False
    stages: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    events: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    segment_calls: int = 0
    wall_t0: float | None = None

    def clear(self) -> None:
        self.stages = defaultdict(list)
        self.events = []
        self.decisions = []
        self.frames = []
        self.segment_calls = 0
        self.wall_t0 = None


_INSTR_LOCK = threading.Lock()
_INSTR = _TrackingInstrState()
# Module-level flag: one bool load on the hot path (no attribute/lock when off).
_INSTR_ENABLED: bool = False


def enable_tracking_instrumentation(enabled: bool = True) -> bool:
    """Enable or disable neutral tracking instrumentation. Returns new state."""
    global _INSTR_ENABLED
    with _INSTR_LOCK:
        _INSTR.enabled = bool(enabled)
        _INSTR_ENABLED = _INSTR.enabled
        if not _INSTR.enabled:
            _INSTR.clear()
        elif _INSTR.wall_t0 is None:
            _INSTR.wall_t0 = time.perf_counter()
        return _INSTR.enabled


def is_tracking_instrumentation_enabled() -> bool:
    return _INSTR_ENABLED


def reset_tracking_instrumentation() -> None:
    """Clear collected events/timings; leaves enabled flag unchanged."""
    global _INSTR_ENABLED
    with _INSTR_LOCK:
        was = _INSTR.enabled
        _INSTR.clear()
        if was:
            _INSTR.wall_t0 = time.perf_counter()
            _INSTR.enabled = True
            _INSTR_ENABLED = True
        else:
            _INSTR_ENABLED = False


def _instr_on() -> bool:
    return _INSTR_ENABLED


def _instr_record_stage(name: str, ms: float, **extra: Any) -> None:
    """Accumulate stage timing without locking (GIL-safe list append).

    Sparse ``emit_event`` markers are rare and take the lock.
    """
    if not _INSTR_ENABLED:
        return
    _INSTR.stages[str(name)].append(float(ms))
    if not extra.get("emit_event"):
        return
    with _INSTR_LOCK:
        if not _INSTR.enabled:
            return
        ev: dict[str, Any] = {
            "kind": "stage",
            "stage": str(name),
            "ms": float(ms),
        }
        for k, v in extra.items():
            if k != "emit_event":
                ev[k] = v
        if _INSTR.wall_t0 is not None:
            ev["t_ms"] = (time.perf_counter() - _INSTR.wall_t0) * 1000.0
        _INSTR.events.append(ev)


def _instr_record_event(kind: str, **payload: Any) -> None:
    """Observe-only event (cache/job/track). No-op when instrumentation is off."""
    if not _INSTR_ENABLED:
        return
    with _INSTR_LOCK:
        if not _INSTR.enabled:
            return
        ev: dict[str, Any] = {"kind": str(kind)}
        if _INSTR.wall_t0 is not None:
            ev["t_ms"] = (time.perf_counter() - _INSTR.wall_t0) * 1000.0
        ev.update(payload)
        _INSTR.events.append(ev)


def record_tracking_observe_event(kind: str, **payload: Any) -> None:
    """Public observe hook for cache/job layers (no science side effects)."""
    _instr_record_event(kind, **payload)


def _instr_qc_snapshot(qc: SliceQC | None) -> dict[str, Any] | None:
    if qc is None:
        return None
    return {
        "circularity": float(qc.circularity),
        "eta": float(qc.eta),
        "edge_support": float(qc.edge_support),
        "inlier_frac": float(qc.inlier_frac),
        "defect_depth_norm": float(qc.defect_depth_norm),
        "flat_contact_frac": float(qc.flat_contact_frac),
        "delta_bic": float(qc.delta_bic),
        "n_dt_markers": int(qc.n_dt_markers),
        "merge_suspect": bool(qc.merge_suspect),
        "strong_two_circle": bool(qc.strong_two_circle),
        "fitted_radius": float(qc.fitted_radius),
        "cheap": bool(qc.cheap),
    }


def _instr_result_snapshot(res: SeededSliceResult) -> dict[str, Any]:
    return {
        "ok": bool(res.ok),
        "method": str(res.method),
        "area_px": float(res.area_px),
        "center": [float(res.center_xy[0]), float(res.center_xy[1])],
        "merge_suspect": bool(res.merge_suspect),
        "qc": _instr_qc_snapshot(res.qc),
        "effective_threshold": (
            float(res.effective_threshold) if res.effective_threshold is not None else None
        ),
    }


def _instr_mask_fingerprint(mask: np.ndarray | None) -> str | None:
    """Stable content fingerprint for scientific parity checks."""
    if mask is None:
        return None
    arr = np.ascontiguousarray(np.asarray(mask, dtype=np.uint8))
    digest = hashlib.sha256(arr.tobytes()).hexdigest()[:16]
    return f"{arr.shape[0]}x{arr.shape[1]}:{digest}"


def scientific_result_fingerprint(res: SeededSliceResult) -> dict[str, Any]:
    """JSON-safe scientific identity of one slice result (for off/on parity)."""
    return {
        "ok": bool(res.ok),
        "method": str(res.method),
        "area_px": float(res.area_px),
        "perimeter_px": float(res.perimeter_px),
        "center": [float(res.center_xy[0]), float(res.center_xy[1])],
        "merge_suspect": bool(res.merge_suspect),
        "mask_fp": _instr_mask_fingerprint(res.solid_mask),
        "qc": _instr_qc_snapshot(res.qc),
        "effective_threshold": (
            float(res.effective_threshold) if res.effective_threshold is not None else None
        ),
    }


def get_tracking_instrumentation() -> dict[str, Any]:
    """Return a JSON-safe snapshot of the current instrumentation collector."""
    with _INSTR_LOCK:
        stage_summary: dict[str, Any] = {}
        for name, vals in sorted(_INSTR.stages.items()):
            if not vals:
                continue
            a = np.asarray(vals, dtype=np.float64)
            stage_summary[name] = {
                "n": int(a.size),
                "sum_ms": float(a.sum()),
                "mean_ms": float(a.mean()),
                "median_ms": float(np.median(a)),
                "p95_ms": float(np.percentile(a, 95)) if a.size else 0.0,
                "max_ms": float(a.max()),
                "min_ms": float(a.min()),
            }
        return {
            "enabled": bool(_INSTR.enabled),
            "segment_calls": int(_INSTR.segment_calls),
            "stage_summary": stage_summary,
            "decision_count": len(_INSTR.decisions),
            "frame_count": len(_INSTR.frames),
            "event_count": len(_INSTR.events),
            "decisions": list(_INSTR.decisions),
            "frames": list(_INSTR.frames),
            "events": list(_INSTR.events),
        }


def _crop_bounds(
    shape: tuple[int, int],
    cx: float,
    cy: float,
    radius: float,
) -> tuple[int, int, int, int]:
    """Crop half-size = max(R * 1.8, 40) — compute only."""
    h, w = shape
    half = int(np.ceil(max(float(radius) * 1.8, 40.0)))
    x0 = max(0, int(np.floor(cx - half)))
    x1 = min(w, int(np.ceil(cx + half)))
    y0 = max(0, int(np.floor(cy - half)))
    y1 = min(h, int(np.ceil(cy + half)))
    if x1 <= x0 + 4:
        x0, x1 = 0, w
    if y1 <= y0 + 4:
        y0, y1 = 0, h
    return y0, y1, x0, x1


def _disk_mask(shape: tuple[int, int], cx: float, cy: float, radius: float) -> np.ndarray:
    h, w = shape
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= float(radius) ** 2


def _mask_iou(mask_a: np.ndarray | None, mask_b: np.ndarray | None) -> float:
    """Intersection-over-Union between two boolean masks. Returns 0.0 if either is None."""
    if mask_a is None or mask_b is None:
        return 0.0
    a = np.asarray(mask_a, dtype=bool)
    b = np.asarray(mask_b, dtype=bool)
    if a.shape != b.shape:
        return 0.0
    intersection = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 0.0
    return intersection / union


def _centroid_gate_distance(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    jump_px: float | None,
    jump_um: float | None,
    voxel_x_um: float,
    voxel_y_um: float,
) -> tuple[float, float]:
    """Return (distance, limit) in consistent units (µm when jump_um set, else px)."""
    dx = float(a[0]) - float(b[0])
    dy = float(a[1]) - float(b[1])
    if jump_um is not None:
        dist = math.hypot(dx * float(voxel_x_um), dy * float(voxel_y_um))
        return dist, float(jump_um)
    dist = math.hypot(dx, dy)
    return dist, float(jump_px if jump_px is not None else 1.0)


def _tracking_score(
    prev_result: SeededSliceResult | None,
    candidate: SeededSliceResult,
    max_centroid_jump_px: float,
    *,
    max_centroid_jump_um: float | None = None,
    voxel_x_um: float = 1.0,
    voxel_y_um: float = 1.0,
) -> float:
    """Composite tracking score in [0, 1]. Higher = more likely same object.

    IoU + centroid remain dominant. Shape integrity (circularity continuity + QC
    quality) is a capped tie-breaker — never a force toward "rounder" neighbors.
    Absolute circularity alone does not dominate.
    """
    if prev_result is None or not prev_result.ok:
        return 1.0  # no previous reference, accept by default

    iou = _mask_iou(prev_result.solid_mask, candidate.solid_mask)

    dist, limit = _centroid_gate_distance(
        candidate.center_xy,
        prev_result.center_xy,
        jump_px=max_centroid_jump_px,
        jump_um=max_centroid_jump_um,
        voxel_x_um=voxel_x_um,
        voxel_y_um=voxel_y_um,
    )
    centroid_score = 1.0 - min(dist / max(float(limit), 1e-9), 1.0)

    r_prev = math.sqrt(prev_result.area_px / math.pi) if prev_result.area_px > 0 else 1.0
    r_new = math.sqrt(candidate.area_px / math.pi) if candidate.area_px > 0 else 0.0
    radius_score = max(0.0, 1.0 - abs(r_new - r_prev) / max(r_prev, 1.0))

    circ_prev = 4.0 * math.pi * prev_result.area_px / max(prev_result.perimeter_px**2, 1e-12)
    circ_new = 4.0 * math.pi * candidate.area_px / max(candidate.perimeter_px**2, 1e-12)
    shape_score = max(0.0, 1.0 - abs(circ_new - circ_prev))

    # Soft QC integrity (≤12% weight total with shape_score still modest).
    qc_term = 1.0
    if candidate.qc is not None:
        qc_term = candidate.qc.quality_score
        if candidate.merge_suspect:
            qc_term *= 0.55
    elif candidate.merge_suspect:
        qc_term = 0.45

    # Weights: IoU/centroid/radius stay primary; shape+QC are capped helpers.
    return (
        0.42 * iou
        + 0.20 * centroid_score
        + 0.18 * radius_score
        + 0.10 * shape_score
        + 0.10 * qc_term
    )


def _is_vesicle_cap(
    slice_2d: np.ndarray,
    solid_mask: np.ndarray | None,
    disk_mask: np.ndarray,
    threshold: float = 1.2,
) -> bool:
    """Detect if this slice is at a vesicle pole (cap).

    True when the membrane boundary is not significantly brighter than a *local*
    exterior annulus. Whole-disk background is avoided: in crowded FOVs bright
    neighbours inflate the disk mean and cause false caps (Packet 02).
    """
    if solid_mask is None or np.count_nonzero(solid_mask) == 0:
        return False
    arr = np.asarray(slice_2d, dtype=np.float64)
    solid = np.asarray(solid_mask, dtype=bool)
    disk = np.asarray(disk_mask, dtype=bool)
    if solid.shape != arr.shape or disk.shape != arr.shape:
        return False
    # Restrict solid to disk for fair comparison
    solid_in = solid & disk
    if np.count_nonzero(solid_in) == 0:
        return False

    # Extract boundary ring of width ~3 pixels using binary erosion to represent
    # the true membrane, avoiding the dark vesicle lumen from diluting the fg signal.
    from scipy.ndimage import binary_dilation, binary_erosion

    struct = np.ones((3, 3), dtype=bool)
    eroded = binary_erosion(solid_in, structure=struct, iterations=3)
    if np.count_nonzero(solid_in & ~eroded) == 0:
        eroded = binary_erosion(solid_in, structure=struct, iterations=1)
    boundary = solid_in & ~eroded
    if np.count_nonzero(boundary) > 0:
        fg_val = float(np.mean(arr[boundary]))
    else:
        fg_val = float(np.mean(arr[solid_in]))

    # Local exterior annulus (just outside the solid), not the whole crop disk.
    exterior = binary_dilation(solid_in, structure=struct, iterations=4) & ~solid_in
    bg_mask = exterior & disk
    if np.count_nonzero(bg_mask) < 16:
        bg_mask = exterior
    if np.count_nonzero(bg_mask) < 12:
        bg_mask = disk & ~solid_in
    if np.count_nonzero(bg_mask) == 0:
        return False

    bg_mean = float(np.mean(arr[bg_mask]))
    # Inclusive threshold: synthetic poles use membrane≈1.2× flat exterior and
    # must still register as caps (see test_cap_detection_stops_at_pole).
    return fg_val <= bg_mean * float(threshold)


def _adaptive_threshold_sparse(values: np.ndarray) -> float | None:
    """Threshold for sparse bright rings / objects (most pixels dark).

    Prefer Otsu when it yields a sensible FG fraction; otherwise percentile /
    positive-pixel stats. Returns None when the disk is uniform.
    """
    flat = np.asarray(values, dtype=np.float64).ravel()
    if flat.size == 0:
        return None
    lo = float(np.min(flat))
    hi = float(np.max(flat))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo + 1e-3:
        return None  # empty / uniform crop — do not paint the whole disk

    thr_otsu: float | None = None
    try:
        from skimage.filters import threshold_otsu

        thr_otsu = float(threshold_otsu(flat))
    except Exception:
        thr_otsu = None

    if thr_otsu is not None:
        fg_fraction = float(np.mean(flat > thr_otsu))
        # Semantic Otsu failure: almost all FG or almost none
        if 0.05 <= fg_fraction <= 0.85:
            return thr_otsu
        # Otsu merged FG/BG — try percentile instead
        p70 = float(np.percentile(flat, 70))
        if p70 > lo + 1e-12:
            return p70
        # else fall through

    # Percentile / positive-pixel fallbacks
    p70 = float(np.percentile(flat, 70))
    if p70 > lo + 1e-12:
        return p70

    med = float(np.median(flat))
    p99 = float(np.percentile(flat, 99))
    floor = med + max(1e-9, 0.05 * (p99 - med))
    pos = flat[flat > floor]
    if pos.size >= 12:
        return float(np.percentile(pos, 20))
    return float(med + 0.3 * max(p99 - med, 0.0))


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    solid = np.asarray(mask, dtype=bool)
    try:
        from scipy.ndimage import binary_fill_holes

        solid = binary_fill_holes(solid)
    except Exception:
        pass
    return solid.astype(bool)


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Return labeled mask and label count (labels 1..n)."""
    try:
        from skimage.measure import label

        labeled = label(np.asarray(mask, dtype=bool), connectivity=2)
        return labeled, int(labeled.max())
    except Exception:
        pass
    try:
        from scipy.ndimage import label as nd_label

        labeled, n = nd_label(np.asarray(mask, dtype=bool))
        return labeled, int(n)
    except Exception:
        m = np.asarray(mask, dtype=bool)
        if not np.any(m):
            return np.zeros(m.shape, dtype=np.int32), 0
        return m.astype(np.int32), 1


def _component_exterior_contains(
    solid: np.ndarray,
    cx: float,
    cy: float,
) -> bool:
    """True if (cx,cy) is on FG or inside exterior contour of solid blob."""
    h, w = solid.shape
    ix = int(round(cx))
    iy = int(round(cy))
    if 0 <= ix < w and 0 <= iy < h and bool(solid[iy, ix]):
        return True
    try:
        import cv2
    except Exception:
        ys, xs = np.where(solid)
        if ys.size == 0:
            return False
        return float(xs.min()) <= cx <= float(xs.max()) and float(ys.min()) <= cy <= float(ys.max())

    binary = np.asarray(solid, dtype=np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    best = max(contours, key=cv2.contourArea)
    if len(best) < 3:
        return False
    return float(cv2.pointPolygonTest(best, (float(cx), float(cy)), False)) >= 0.0


def _pick_component_in_disk(
    fg_mask: np.ndarray,
    disk: np.ndarray,
    local_cx: float,
    local_cy: float,
    R: float,
    ref_area: float | None = None,
    cheap: bool = False,
) -> np.ndarray | None:
    """Pick CC inside disk: prefer exterior containing seed, area near ref/R.

    Neck-fused multi-vesicle masks are split via DT watershed before labeling
    so the seed's vesicle is isolated from a connecting neighbor.
    """
    masked = np.asarray(fg_mask, dtype=bool) & np.asarray(disk, dtype=bool)
    if not np.any(masked):
        return None

    # Split fused blobs at thin necks before connected-component pick.
    if not cheap:
        try:
            from morphostack.core.object_select import isolate_seeded_mask

            masked = isolate_seeded_mask(
                masked,
                seed_x=float(local_cx),
                seed_y=float(local_cy),
                seed_radius=float(R),
            )
        except Exception:
            pass

    labeled, nlab = _label_components(masked)
    if nlab <= 0:
        return None

    max_area = float(np.pi * max(R, 1.0) ** 2) * 1.5
    min_area = max(16.0, float(np.pi * max(R, 1.0) ** 2) * 0.04)
    target = float(ref_area) if ref_area is not None and ref_area > 0 else float(np.pi * max(R, 1.0) ** 2)
    if ref_area is not None and ref_area > 0:
        min_area = max(min_area, ref_area * 0.2)
        max_area = min(max_area, ref_area * 2.5)

    scored: list[tuple[float, np.ndarray]] = []

    for lab in range(1, nlab + 1):
        comp = labeled == lab
        solid = _fill_holes(comp)
        solid_area = float(np.count_nonzero(solid))
        if solid_area < min_area or solid_area > max_area:
            continue
        contains = _component_exterior_contains(solid, local_cx, local_cy)
        ys, xs = np.where(solid)
        if ys.size == 0:
            continue
        scx, scy = float(xs.mean()), float(ys.mean())
        dist = float(np.hypot(scx - local_cx, scy - local_cy))
        area_term = abs(solid_area - target) / max(target, 1.0)
        score = area_term + 0.15 * (dist / max(R, 1.0)) + (0.0 if contains else 2.5)
        scored.append((score, solid))

    if not scored:
        return None
    scored.sort(key=lambda t: t[0])
    return scored[0][1]


def _contour_from_solid(solid: np.ndarray) -> np.ndarray | None:
    from morphostack.core.contours import smooth_contour_spline

    try:
        import cv2
    except Exception:
        cv2 = None  # type: ignore

    if cv2 is not None:
        binary = np.asarray(solid, dtype=np.uint8) * 255
        # Close 1-2 px noise holes and membrane roughness before tracing.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            if len(largest) >= 3:
                return smooth_contour_spline(normalize_points(largest))

    try:
        from skimage.measure import find_contours
    except Exception:
        return None
    contours = find_contours(np.asarray(solid, dtype=np.float64), 0.5)
    if not contours:
        return None
    best = max(contours, key=lambda c: c.shape[0])
    if best.shape[0] < 5:
        return None
    xy = np.column_stack([best[:, 1], best[:, 0]]).astype(np.float64)
    return smooth_contour_spline(normalize_points(xy))


def _refine_contour_morphgac(
    slice_2d: np.ndarray,
    initial_mask: np.ndarray,
    iterations: int = 25,
    smoothing: int = 1,
    balloon: float = 0.0,
    disk_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Refine a coarse binary mask using MorphGAC. Falls back to initial_mask."""
    initial = np.asarray(initial_mask, dtype=bool)
    try:
        from skimage.segmentation import inverse_gaussian_gradient, morphological_geodesic_active_contour

        img_f = np.asarray(slice_2d, dtype=np.float64)
        peak = float(np.max(img_f)) if img_f.size else 0.0
        if peak > 0:
            img_f = img_f / peak
        gimage = inverse_gaussian_gradient(img_f, alpha=100.0, sigma=2.0)
        # Clamp gradient to disk so the active contour cannot feel neighbor membranes.
        if disk_mask is not None:
            gimage = gimage * np.asarray(disk_mask, dtype=np.float64)
        refined = morphological_geodesic_active_contour(
            gimage,
            num_iter=max(5, int(iterations)),
            init_level_set=initial.astype(np.float64),
            smoothing=int(smoothing),
            balloon=float(balloon),
        ).astype(bool)
        refined_area = int(np.count_nonzero(refined))
        initial_area = max(1, int(np.count_nonzero(initial)))
        if refined_area < initial_area * 0.3 or refined_area > initial_area * 3.0:
            return initial
        if refined_area < 16:
            return initial
        return refined
    except Exception:
        return initial


def _result_from_solid(
    solid_local: np.ndarray,
    *,
    y0: int,
    x0: int,
    full_shape: tuple[int, int],
    fallback_center: tuple[float, float],
    method: str,
    qc: SliceQC | None = None,
    merge_suspect: bool = False,
    effective_threshold: float | None = None,
    search_center_xy: tuple[float, float] | None = None,
) -> SeededSliceResult:
    h, w = full_shape
    search_c = search_center_xy if search_center_xy is not None else fallback_center
    contour_local = _contour_from_solid(solid_local)
    if contour_local is None or len(contour_local) < 3:
        return SeededSliceResult(
            None,
            None,
            fallback_center,
            0.0,
            0.0,
            "circle_seed_fail",
            False,
            search_center_xy=search_c,
        )
    contour = contour_local.copy()
    contour[:, 0] += x0
    contour[:, 1] += y0
    solid_full = np.zeros((h, w), dtype=bool)
    solid_full[y0 : y0 + solid_local.shape[0], x0 : x0 + solid_local.shape[1]] = solid_local
    area = float(polygon_area(contour))
    # Crofton perimeter is less biased than polygon arc length for digital objects.
    try:
        from skimage.measure import perimeter_crofton

        peri = float(perimeter_crofton(np.asarray(solid_local, dtype=bool), directions=4))
    except Exception:
        peri = float(polygon_perimeter(contour, x_scale=1.0, y_scale=1.0))
    cx = float(np.mean(contour[:, 0]))
    cy = float(np.mean(contour[:, 1]))
    return SeededSliceResult(
        contour,
        solid_full,
        (cx, cy),
        area,
        peri,
        method,
        True,
        merge_suspect=bool(merge_suspect),
        qc=qc,
        effective_threshold=(
            float(effective_threshold) if effective_threshold is not None else None
        ),
        search_center_xy=search_c,
    )


def _try_rw_ws_in_disk(
    crop: np.ndarray,
    disk: np.ndarray,
    local_cx: float,
    local_cy: float,
    R: float,
) -> np.ndarray | None:
    """Optional RW/watershed inside disk; always AND with disk mask."""
    try:
        from skimage.filters import sobel
        from skimage.segmentation import random_walker, watershed
        from skimage.util import img_as_float
    except Exception:
        return None

    h, w = crop.shape
    markers = np.zeros((h, w), dtype=np.int32)
    yy, xx = np.ogrid[:h, :w]
    lumen_r = max(2.0, min(6.0, R * 0.15))
    lumen = (xx - local_cx) ** 2 + (yy - local_cy) ** 2 <= lumen_r**2
    outer = disk & ((xx - local_cx) ** 2 + (yy - local_cy) ** 2 >= (R * 1.05) ** 2)
    markers[lumen & disk] = 1
    markers[outer] = 2
    border = 1
    markers[:border, :] = 2
    markers[-border:, :] = 2
    markers[:, :border] = 2
    markers[:, -border:] = 2
    markers[~disk] = 0
    if not np.any(markers == 1) or not np.any(markers == 2):
        return None

    data = img_as_float(np.asarray(crop, dtype=np.float64))
    dmin, dmax = float(np.min(data)), float(np.max(data))
    if dmax > dmin:
        data = (data - dmin) / (dmax - dmin)

    labels = None
    try:
        labels = random_walker(data, markers, beta=50, mode="bf")
    except Exception:
        try:
            elev = sobel(np.asarray(crop, dtype=np.float64))
            labels = watershed(elev, markers)
        except Exception:
            return None

    solid = (labels == 1) & disk
    solid = _fill_holes(solid) & disk
    max_area = float(np.pi * max(R, 1.0) ** 2) * 1.5
    area = float(np.count_nonzero(solid))
    if area < 16 or area > max_area:
        return None
    if not _component_exterior_contains(solid, local_cx, local_cy):
        ys, xs = np.where(solid)
        if ys.size == 0:
            return None
        scx, scy = float(xs.mean()), float(ys.mean())
        if (scx - local_cx) ** 2 + (scy - local_cy) ** 2 > (0.6 * R) ** 2:
            return None
    return solid


def _candidate_accepted(
    cand: SeededSliceResult,
    *,
    prev: SeededSliceResult | None,
    ref_area: float,
    max_area_ratio: float,
    jump: float,
    expected_center: tuple[float, float] | None = None,
    expected_center_tolerance: float | None = None,
    search_radius: float | None = None,
    nominal_radius: float | None = None,
    jump_um: float | None = None,
    voxel_x_um: float = 1.0,
    voxel_y_um: float = 1.0,
) -> bool:
    """IoU hard floor + multi-feature score with conservative gap recovery.

    Unresolved merge suspicion fails closed (track gap preferred over neighbor steal).
    Low circularity alone is never a hard reject.
    """
    if not cand.ok:
        return False

    # Expanded search radius validation to prevent neighbor steal
    if search_radius is not None and nominal_radius is not None and search_radius > 1.01 * nominal_radius:
        # 1. Validate against prior/expected center: center drift must be bounded
        target_c = expected_center if expected_center is not None else (prev.center_xy if (prev and prev.ok) else None)
        if target_c is not None:
            dist = math.hypot(cand.center_xy[0] - target_c[0], cand.center_xy[1] - target_c[1])
            if dist > 0.8 * nominal_radius:
                return False

        # 2. Validate against neighbor-contamination / shape QC (e.g. flat contact, convexity defect)
        if cand.qc is not None:
            if cand.qc.strong_two_circle or cand.qc.n_dt_markers >= 2 or cand.qc.delta_bic <= -5.0:
                return False
            if cand.qc.flat_contact_frac >= 0.10 or cand.qc.defect_depth_norm > 0.06:
                return False
            if cand.merge_suspect:
                return False
        elif cand.merge_suspect:
            return False

        # 3. Validate against sudden area expansion (neighbor merge) while preserving shrink
        if prev is not None and prev.ok and cand.area_px > 1.4 * prev.area_px:
            return False

    # Fail closed only on composite multi-object evidence (not every soft
    # merge_suspect — legitimate flat/concave singles may carry a weak flag).
    if cand.merge_suspect:
        if cand.qc is None:
            return False
        from morphostack.core.slice_qc import fail_closed

        if fail_closed(cand.qc):
            return False
        # Soft residual flag: continue with IoU/area/centroid gates below.
    if expected_center is not None and expected_center_tolerance is not None:
        expected_dist = math.hypot(
            cand.center_xy[0] - expected_center[0],
            cand.center_xy[1] - expected_center[1],
        )
        if expected_dist > max(float(expected_center_tolerance), 1.0):
            return False

        # Prevent backward reacquisition of neighbor after a gap
        if prev is not None and prev.ok and prev.center_xy is not None:
            dx_p = expected_center[0] - prev.center_xy[0]
            dy_p = expected_center[1] - prev.center_xy[1]
            step_x = cand.center_xy[0] - prev.center_xy[0]
            step_y = cand.center_xy[1] - prev.center_xy[1]
            p_dist = math.hypot(dx_p, dy_p)
            if p_dist > 1.0:
                dot = step_x * dx_p + step_y * dy_p
                if dot < -0.1 * p_dist**2:
                    return False
    if prev is not None and prev.ok and prev.center_xy is not None:
        dist, limit = _centroid_gate_distance(
            cand.center_xy,
            prev.center_xy,
            jump_px=jump,
            jump_um=jump_um,
            voxel_x_um=voxel_x_um,
            voxel_y_um=voxel_y_um,
        )
        if dist > limit:
            return False
    # Absolute area ceiling (loose safety net for merges)
    if cand.area_px > max_area_ratio * ref_area * 1.5:
        return False
    if prev is not None and prev.ok and prev.solid_mask is not None:
        iou = _mask_iou(prev.solid_mask, cand.solid_mask)
        # Phase 1: no-overlap jump to a different object
        if iou < 0.15:
            return False
        # Gradual broad-contact walk: area growth + neighbour-directed center
        # shift (relative to recent accepted scale, not raw seed radius alone).
        if prev.area_px > 0 and cand.area_px > 1.28 * prev.area_px:
            center_shift = math.hypot(
                cand.center_xy[0] - prev.center_xy[0],
                cand.center_xy[1] - prev.center_xy[1],
            )
            r_prev = math.sqrt(prev.area_px / math.pi) if prev.area_px > 0 else 1.0
            # Neighbour-directed expansion: growth + substantial center walk.
            if center_shift > 0.35 * r_prev and iou < 0.55:
                return False
            if cand.qc is not None and center_shift > 0.25 * r_prev:
                contactish = (
                    cand.qc.flat_contact_frac >= 0.10
                    or cand.qc.defect_depth_norm > 0.06
                    or cand.qc.n_dt_markers >= 2
                    or cand.qc.strong_two_circle
                )
                if contactish:
                    return False
        # Veto helper: weak edge + poor residual + shape collapse vs prev → merge steal risk
        # (composite; circularity alone is not a hard reject).
        if cand.qc is not None and prev.qc is not None:
            if (
                cand.qc.edge_support < 0.40
                and cand.qc.eta > max(0.10, 1.5 * prev.qc.eta)
                and cand.qc.circularity < max(0.65, prev.qc.circularity - 0.18)
            ):
                return False
    score = _tracking_score(
        prev,
        cand,
        jump,
        max_centroid_jump_um=jump_um,
        voxel_x_um=voxel_x_um,
        voxel_y_um=voxel_y_um,
    )
    return score >= 0.30


def _per_frame_velocity(
    recent_centers: list[tuple[float, float, int]],
) -> tuple[float, float] | None:
    """Per-frame (dx, dy) from last two indexed centers; None if unavailable."""
    if len(recent_centers) < 2:
        return None
    prev = recent_centers[-2]
    curr = recent_centers[-1]
    frame_gap = abs(int(curr[2]) - int(prev[2]))
    if frame_gap <= 0:
        return None
    dx = (float(curr[0]) - float(prev[0])) / frame_gap
    dy = (float(curr[1]) - float(prev[1])) / frame_gap
    return dx, dy


# A gap is evidence loss, not permission to restart object selection. Two
# missing slices still permit a predicted recovery; a third ends the chain.
MAX_CONSECUTIVE_TRACK_GAPS = 2


def _gap_reacquisition_tolerance(
    velocity: tuple[float, float] | None,
    *,
    gap_count: int,
    radius: float,
) -> float:
    """Conservative distance around the motion prediction after a gap."""
    if velocity is None:
        return max(3.0, min(0.5 * float(radius), 6.0))
    speed = math.hypot(float(velocity[0]), float(velocity[1]))
    predicted_step = speed * max(1, int(gap_count) + 1)
    return max(3.0, min(0.5 * float(radius), 0.75 * predicted_step + 2.0))

def segment_slice_seeded(
    frame: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float | None = None,
    crop_radius: float | None = None,  # legacy alias for seed_radius
    refine: bool = True,
    ref_area: float | None = None,
    fast_preview: bool = False,
    competitive_isolation: bool | None = None,
    multiscale_consensus: bool = False,
    profile: str = "vesicle",
) -> SeededSliceResult:
    """Segment one slice with a user circle (cx, cy, R) in full-image coords.

    ``fast_preview`` is an explicit, display-only opt-in. It keeps the same
    crop, hard disk, adaptive threshold, and component selection logic, but
    skips the costly bilateral denoise and MorphGAC refinement. Leave it
    false for analysis and tracking so scientific results retain their current
    behaviour.

    ``competitive_isolation``: when True, use Packet 02 polar/RW isolation for
    this call only. When None, fall back to the process-global test flag
    (default off). API/jobs must pass an explicit bool — never toggle the global
    around concurrent requests.
    """
    _instr = _INSTR_ENABLED
    _t_seg0 = time.perf_counter() if _instr else 0.0
    if _instr:
        _INSTR.segment_calls += 1

    arr = np.asarray(frame)
    if arr.ndim != 2:
        raise ValueError("segment_slice_seeded expects a 2D frame")
    h, w = arr.shape
    sx = float(np.clip(seed_x, 0, w - 1))
    sy = float(np.clip(seed_y, 0, h - 1))

    R = effective_seed_radius(seed_radius if seed_radius is not None else crop_radius)
    use_competitive = resolve_competitive_isolation(competitive_isolation)
    use_consensus = bool(multiscale_consensus)
    if use_competitive and use_consensus:
        raise ValueError("competitive and multi-scale consensus modes are mutually exclusive")

    y0, y1, x0, x1 = _crop_bounds((h, w), sx, sy, R)
    crop_raw = np.asarray(arr[y0:y1, x0:x1], dtype=np.float64)
    # Interactive rendering needs a faithful local selection quickly; the
    # expensive edge-preserving filter is reserved for scientific results.
    if fast_preview or use_consensus:
        crop = crop_raw
    else:
        if _instr:
            _t0 = time.perf_counter()
        crop = _bilateral(crop_raw, sigma_spatial=1.5)
        if _instr:
            _instr_record_stage("bilateral", (time.perf_counter() - _t0) * 1000.0)

    local_cx = sx - x0
    local_cy = sy - y0
    disk_r = R * 1.15
    disk = _disk_mask(crop.shape, local_cx, local_cy, disk_r)

    solid: np.ndarray | None = None
    method = "circle_seed_fail"
    # Provenance: intensity gate actually applied for threshold-based methods.
    effective_threshold: float | None = None
    thr: float | None = None
    competitive_used = False
    use_competitive = resolve_competitive_isolation(competitive_isolation)
    use_consensus = bool(multiscale_consensus)
    if use_competitive and use_consensus:
        raise ValueError("competitive and multi-scale consensus modes are mutually exclusive")
    consensus = None

    if not fast_preview and use_consensus:
        from morphostack.core.multiscale_consensus import (
            mask_iou as _consensus_iou,
            propose_multiscale_consensus,
            raw_edge_support as _raw_edge_support,
        )

        consensus = propose_multiscale_consensus(
            crop_raw, disk, local_cx, local_cy, R, ref_area=ref_area, profile=profile
        )
        if consensus.solid is None:
            return SeededSliceResult(
                None, None, (sx, sy), 0.0, 0.0, "multiscale_consensus_reject", False,
                consensus_sigmas=consensus.sigmas,
                consensus_candidate_count=consensus.candidate_count,
                consensus_dominant_cluster_size=consensus.dominant_cluster_size,
                consensus_agreement=consensus.agreement,
                consensus_boundary_spread=consensus.boundary_spread,
                consensus_raw_edge_support=consensus.raw_edge_support,
                consensus_confidence=consensus.confidence,
                consensus_reject_reason=consensus.reject_reason,
            )
        solid = np.asarray(consensus.solid, dtype=bool) & disk
        method = "multiscale_consensus"
        effective_threshold = None
        if refine:
            _EXACT_PATH_COUNTERS.morphgac_calls += 1
            refined = _refine_contour_morphgac(
                crop_raw,
                solid,
                iterations=5,
                smoothing=0,
                disk_mask=disk,
            ) & disk
            refined_iou = _consensus_iou(solid, refined)
            refined_edge = _raw_edge_support(crop_raw, refined, disk)
            if refined_iou >= 0.75 and refined_edge >= consensus.raw_edge_support - 0.05:
                solid = refined
                method = "multiscale_consensus_morphgac"

    # Packet 02/11: request-scoped competitive polar + multi-label RW path.
    # When enabled, threshold/CC is no longer authoritative isolation.
    if not fast_preview and use_competitive:
        from morphostack.core.competitive_isolation import isolate_competitive

        if _instr:
            _t0 = time.perf_counter()
        cres = isolate_competitive(
            crop,
            crop_raw,
            disk,
            local_cx,
            local_cy,
            R,
            ref_area=ref_area,
        )
        if _instr:
            _instr_record_stage(
                "competitive_isolation",
                (time.perf_counter() - _t0) * 1000.0,
                ok=bool(cres.ok),
                reason=cres.reject_reason,
            )
            if _INSTR_ENABLED:
                _instr_record_event(
                    "competitive_decision",
                    ok=bool(cres.ok),
                    method=str(cres.method),
                    reject_reason=cres.reject_reason,
                    target_prob_mean=float(cres.target_prob_mean),
                    competitor_margin=float(cres.competitor_margin),
                    n_neighbor_labels=int(cres.n_neighbor_labels),
                    polar_ok=bool(cres.polar_ok),
                )
        competitive_used = True
        if cres.ok and cres.solid is not None:
            solid = np.asarray(cres.solid, dtype=bool) & disk
            method = str(cres.method)
            effective_threshold = None
        else:
            # Fail closed: do not fall through to unsafe threshold pick.
            if _instr:
                _instr_record_stage(
                    "segment_total",
                    (time.perf_counter() - _t_seg0) * 1000.0,
                    method="circle_seed_merge_reject",
                    ok=False,
                )
            return SeededSliceResult(
                None,
                None,
                (sx, sy),
                0.0,
                0.0,
                "circle_seed_merge_reject",
                False,
                merge_suspect=True,
            )

    if not competitive_used and not use_consensus:
        # Primary (legacy default): adaptive threshold inside hard disk.
        disk_vals = crop[disk]
        if _instr:
            _t0 = time.perf_counter()
        thr = _adaptive_threshold_sparse(disk_vals)
        if _instr:
            _instr_record_stage("adaptive_threshold", (time.perf_counter() - _t0) * 1000.0)

        if thr is not None:
            used_thr = float(thr)
            fg = (crop >= used_thr) & disk
            disk_area = float(np.count_nonzero(disk))
            fg_area = float(np.count_nonzero(fg))
            if fg_area > 0.92 * disk_area and disk_area > 0:
                p_hi = float(np.percentile(disk_vals, 92))
                if p_hi > float(np.min(disk_vals)) + 1e-12:
                    used_thr = p_hi
                    fg = (crop >= used_thr) & disk
                    fg_area = float(np.count_nonzero(fg))
            if fg_area > 0:
                if _instr:
                    _t0 = time.perf_counter()
                solid = _pick_component_in_disk(
                    fg, disk, local_cx, local_cy, R, ref_area=ref_area, cheap=fast_preview
                )
                if _instr:
                    _instr_record_stage("pick_component", (time.perf_counter() - _t0) * 1000.0)
                if solid is not None:
                    method = "circle_seed"
                    effective_threshold = used_thr

        # Polar-DP fallback only when threshold/CC path produced nothing.
        if solid is None:
            try:
                from morphostack.core.polar_dp import segment_slice_polar_dp

                # n_angles: at least 1 px arc spacing to avoid jagged Viterbi paths.
                _n_angles = max(360, int(2.0 * np.pi * R))
                # Clamp search band to disk boundary so Viterbi cannot reach neighbor membranes.
                _safe_band = max(0.10, min(0.20, (disk_r - R) / max(R, 1.0)))
                if _instr:
                    _t0 = time.perf_counter()
                polar = segment_slice_polar_dp(
                    crop_raw,
                    local_cx,
                    local_cy,
                    R,
                    search_band=_safe_band,
                    n_angles=_n_angles,
                    smoothness_penalty=3.0,
                    max_jump=2,
                )
                if _instr:
                    _instr_record_stage("polar_dp", (time.perf_counter() - _t0) * 1000.0)
                if polar.ok and polar.solid_mask is not None:
                    solid = np.asarray(polar.solid_mask, dtype=bool) & disk
                    if np.count_nonzero(solid) >= 16:
                        method = "polar_dp"
                        effective_threshold = None  # ridge path; no intensity gate
                    else:
                        solid = None
            except Exception:
                solid = None

        if solid is None and thr is not None:
            if _instr:
                _t0 = time.perf_counter()
            solid = _try_rw_ws_in_disk(crop, disk, local_cx, local_cy, R)
            if _instr:
                _instr_record_stage("rw_ws", (time.perf_counter() - _t0) * 1000.0)
            if solid is not None:
                sa = float(np.count_nonzero(solid))
                if ref_area is not None and ref_area > 0 and (sa < ref_area * 0.2 or sa > ref_area * 2.5):
                    solid = None
                else:
                    method = "circle_seed_rw"
                    effective_threshold = float(thr)

    if solid is None:
        if _instr:
            _instr_record_stage("segment_total", (time.perf_counter() - _t_seg0) * 1000.0, method="circle_seed_fail", ok=False)
        return SeededSliceResult(None, None, (sx, sy), 0.0, 0.0, "circle_seed_fail", False)

    solid = _fill_holes(solid) & disk
    if not np.any(solid):
        if _instr:
            _instr_record_stage("segment_total", (time.perf_counter() - _t_seg0) * 1000.0, method="circle_seed_fail", ok=False)
        return SeededSliceResult(None, None, (sx, sy), 0.0, 0.0, "circle_seed_fail", False)

    # --- Post-segmentation QC + fail-closed contact handling (exact path) ---
    # Production path (Packet 06 REJECT / Packet 10 deleted opt-in gates):
    #   full RANSAC/two-circle/DT QC; MorphGAC when refine=True (except competitive
    #   isolation, which already hard-gated multi-body); fail-closed retained.
    # fast_preview: cheap diagnostics only; never run full RANSAC/two-circle/repair.
    from morphostack.core.slice_qc import (
        accept_as_is,
        cheap_suspicion_flags,
        compute_slice_qc,
        fail_closed,
        is_clean_frame_pre_refine,
        repair_improves,
        should_attempt_polar_repair,
        should_attempt_split,
    )

    _EXACT_PATH_COUNTERS.segment_calls += 1
    qc_img = crop_raw if (fast_preview or use_consensus) else crop
    clean_pre_refine = False
    suspicion: tuple[str, ...] = ()

    def _run_qc(mask_in: np.ndarray, image_in: np.ndarray, *, cheap: bool) -> SliceQC:
        if _instr:
            _t0 = time.perf_counter()
        out_qc = compute_slice_qc(
            mask_in,
            image_in,
            seed_x=local_cx,
            seed_y=local_cy,
            seed_radius=R,
            cheap=cheap,
        )
        if _instr:
            _instr_record_stage(
                "qc_cheap" if cheap else "qc_full",
                (time.perf_counter() - _t0) * 1000.0,
            )
        return out_qc

    def _reject_merge(qc_obj: SliceQC) -> SeededSliceResult:
        if _instr:
            _instr_record_stage(
                "segment_total",
                (time.perf_counter() - _t_seg0) * 1000.0,
                method="circle_seed_merge_reject",
                ok=False,
            )
            _instr_record_event(
                "qc_decision",
                decision="merge_reject",
                method="circle_seed_merge_reject",
                qc=_instr_qc_snapshot(qc_obj),
            )
        return SeededSliceResult(
            None,
            None,
            (sx, sy),
            0.0,
            0.0,
            "circle_seed_merge_reject",
            False,
            merge_suspect=True,
            qc=qc_obj,
            consensus_sigmas=consensus.sigmas if consensus is not None else None,
            consensus_candidate_count=(
                consensus.candidate_count if consensus is not None else None
            ),
            consensus_dominant_cluster_size=(
                consensus.dominant_cluster_size if consensus is not None else None
            ),
            consensus_agreement=consensus.agreement if consensus is not None else None,
            consensus_boundary_spread=(
                consensus.boundary_spread if consensus is not None else None
            ),
            consensus_raw_edge_support=(
                consensus.raw_edge_support if consensus is not None else None
            ),
            consensus_confidence=consensus.confidence if consensus is not None else None,
            consensus_reject_reason=(
                consensus.reject_reason if consensus is not None else None
            ),
        )

    if fast_preview:
        qc = _run_qc(solid, qc_img, cheap=True)
    else:
        # Full QC only (no staged cheap-first gate — experiment deleted).
        qc = _run_qc(solid, crop_raw if use_consensus else crop, cheap=False)
        suspicion = cheap_suspicion_flags(
            qc,
            solid,
            seed_x=local_cx,
            seed_y=local_cy,
            seed_radius=R,
            ref_area=ref_area,
        )
        clean_pre_refine = is_clean_frame_pre_refine(suspicion)

        # Competitive isolation already applied hard multi-body / star-convex gates.
        # Do not re-run legacy split/polar repair or discard the solid on soft QC —
        # that destroyed continuity (Packet 02 R20 flip-flop / false reject).
        if use_consensus:
            if fail_closed(qc):
                _EXACT_PATH_COUNTERS.merge_rejects += 1
                return _reject_merge(qc)
        elif competitive_used:
            pass
        elif not clean_pre_refine and not accept_as_is(qc):

            # 1) Thin-neck / multi-marker: marker-controlled watershed child only.
            if should_attempt_split(qc):
                try:
                    from morphostack.core.object_select import attempt_seeded_split

                    _EXACT_PATH_COUNTERS.split_attempts += 1
                    if _instr:
                        _t0 = time.perf_counter()
                    split = attempt_seeded_split(
                        solid,
                        seed_x=local_cx,
                        seed_y=local_cy,
                        seed_radius=R,
                    )
                    if _instr:
                        _instr_record_stage(
                            "attempt_seeded_split",
                            (time.perf_counter() - _t0) * 1000.0,
                        )
                except Exception:
                    split = None
                if split is not None:
                    split = _fill_holes(np.asarray(split, dtype=bool)) & disk
                    if np.count_nonzero(split) >= 16:
                        qc_split = _run_qc(split, crop, cheap=False)
                        if repair_improves(qc, qc_split) or not qc_split.merge_suspect:
                            solid = split
                            qc = qc_split
                            method = method + "_split" if not method.endswith("_split") else method

            # 2) Broad-contact / unimodal merge: polar-DP as *primary repair*, not
            #    unconditional first step. Accept only if QC improves.
            if should_attempt_polar_repair(qc) and qc.merge_suspect:
                try:
                    from morphostack.core.polar_dp import segment_slice_polar_dp

                    _EXACT_PATH_COUNTERS.polar_repair_attempts += 1
                    _n_angles = max(360, int(2.0 * np.pi * R))
                    _safe_band = max(0.10, min(0.20, (disk_r - R) / max(R, 1.0)))
                    if _instr:
                        _t0 = time.perf_counter()
                    polar = segment_slice_polar_dp(
                        crop_raw,
                        local_cx,
                        local_cy,
                        R,
                        search_band=_safe_band,
                        n_angles=_n_angles,
                        smoothness_penalty=3.0,
                        max_jump=2,
                    )
                    if _instr:
                        _instr_record_stage(
                            "polar_repair",
                            (time.perf_counter() - _t0) * 1000.0,
                        )
                    if polar.ok and polar.solid_mask is not None:
                        repaired = np.asarray(polar.solid_mask, dtype=bool) & disk
                        repaired = _fill_holes(repaired) & disk
                        if np.count_nonzero(repaired) >= 16:
                            qc_rep = _run_qc(repaired, crop, cheap=False)
                            # Centroid drift guard relative to current proposal.
                            ys, xs = np.where(repaired)
                            rcx, rcy = float(xs.mean()), float(ys.mean())
                            ys0, xs0 = np.where(solid)
                            ocx, ocy = float(xs0.mean()), float(ys0.mean())
                            drift = math.hypot(rcx - ocx, rcy - ocy)
                            if drift <= 0.20 * R and repair_improves(qc, qc_rep):
                                solid = repaired
                                qc = qc_rep
                                method = "polar_dp_repair"
                except Exception:
                    pass

            # 3) Fail closed: unresolved strong merge → no contour (track gap).
            if fail_closed(qc):
                _EXACT_PATH_COUNTERS.merge_rejects += 1
                return _reject_merge(qc)
        elif clean_pre_refine and float(qc.edge_support) < 0.25:
            # Cheap-path collapsed membrane (fail_closed ignores cheap bundles).
            _EXACT_PATH_COUNTERS.merge_rejects += 1
            return _reject_merge(qc)

    # MorphGAC when refine=True. Competitive isolation already hard-gated
    # multi-body/star-convex; skip MorphGAC there (Packet 02 continuity).
    # Packet 06 MorphGAC-skip-when-clean switch deleted (science REJECT).
    run_morphgac = bool(refine and not fast_preview)
    if run_morphgac and (competitive_used or use_consensus):
        run_morphgac = False
        _EXACT_PATH_COUNTERS.morphgac_skipped_clean += 1

    if run_morphgac:
        _EXACT_PATH_COUNTERS.morphgac_calls += 1
        if _instr:
            _t0 = time.perf_counter()
        solid = _refine_contour_morphgac(crop, solid, disk_mask=disk) & disk
        if _instr:
            _instr_record_stage("morphgac", (time.perf_counter() - _t0) * 1000.0)
        if not np.any(solid):
            if _instr:
                _instr_record_stage(
                    "segment_total",
                    (time.perf_counter() - _t_seg0) * 1000.0,
                    method="circle_seed_fail",
                    ok=False,
                )
            return SeededSliceResult(None, None, (sx, sy), 0.0, 0.0, "circle_seed_fail", False)
        # Stage 5: full post-refine QC whenever MorphGAC runs.
        qc = _run_qc(solid, crop, cheap=False)
        if fail_closed(qc):
            _EXACT_PATH_COUNTERS.merge_rejects += 1
            return _reject_merge(qc)

    # Final identity guard: composite multi-body evidence only.
    # Seed radius is not biological ground truth — scale far-mass against
    # max(user R, area-derived radius from ref_area when available).
    # Competitive path already applied star-convex / multi-body hard gates.
    if solid is not None and not fast_preview and qc is not None and not competitive_used:
        from morphostack.core.slice_qc import fail_closed as _fail_closed

        if _fail_closed(qc):
            _EXACT_PATH_COUNTERS.merge_rejects += 1
            return _reject_merge(qc)
        solid_area = float(np.count_nonzero(solid))
        r_area = math.sqrt(max(solid_area, 1.0) / math.pi)
        r_ref = (
            math.sqrt(float(ref_area) / math.pi)
            if ref_area is not None and ref_area > 0
            else float(R)
        )
        # Prefer recent/object scale over undersized seed alone.
        scale_r = max(float(R), r_ref * 0.85, r_area * 0.55)
        far_limit = scale_r * 1.25
        n_peaks = int(qc.n_dt_markers)
        if n_peaks < 2:
            try:
                from morphostack.core.object_select import _dt_peak_coords

                peaks = _dt_peak_coords(solid, seed_radius=scale_r, use_h_maxima=True)
                n_peaks = int(len(peaks)) if peaks is not None else 0
            except Exception:
                pass
        far_frac = 0.0
        try:
            ys, xs = np.where(np.asarray(solid, dtype=bool))
            if ys.size > 0:
                dist = np.hypot(
                    xs.astype(np.float64) - local_cx, ys.astype(np.float64) - local_cy
                )
                far_frac = float(np.count_nonzero(dist > far_limit)) / float(ys.size)
        except Exception:
            far_frac = 0.0
        # Cheap QC leaves unfitted placeholders (eta=0.25, flat/defect=0); do not
        # treat those as real contact geometry or radial residual evidence.
        if qc.cheap:
            contact_geo = False
            peaks_plus = n_peaks >= 2 and far_frac >= 0.10
            far_plus = far_frac >= 0.12 and n_peaks >= 2
        else:
            contact_geo = qc.flat_contact_frac >= 0.10 or qc.defect_depth_norm > 0.06
            # n_peaks alone is not enough (noisy / mildly concave singles).
            peaks_plus = n_peaks >= 2 and (
                far_frac >= 0.10 or contact_geo or qc.strong_two_circle or qc.eta > 0.09
            )
            # Far mass alone is not enough (underestimated seed R); need second cue.
            far_plus = far_frac >= 0.12 and (
                n_peaks >= 2 or contact_geo or qc.strong_two_circle or qc.delta_bic <= -5.0
            )
        if peaks_plus or far_plus:
            _EXACT_PATH_COUNTERS.merge_rejects += 1
            return _reject_merge(qc)

    # Polar repair overwrites method; clear intensity gate if repair was polar.
    if method == "polar_dp_repair":
        effective_threshold = None

    if not fast_preview:
        _EXACT_PATH_COUNTERS.accepted += 1

    if _instr:
        _instr_record_stage(
            "segment_total",
            (time.perf_counter() - _t_seg0) * 1000.0,
            method=method,
            ok=True,
        )

    final_result = _result_from_solid(
        solid,
        y0=y0,
        x0=x0,
        full_shape=(h, w),
        fallback_center=(sx, sy),
        method=method,
        qc=qc,
        merge_suspect=bool(qc.merge_suspect) if qc is not None else False,
        effective_threshold=effective_threshold,
    )
    if consensus is not None:
        return replace(
            final_result,
            consensus_sigmas=consensus.sigmas,
            consensus_candidate_count=consensus.candidate_count,
            consensus_dominant_cluster_size=consensus.dominant_cluster_size,
            consensus_agreement=consensus.agreement,
            consensus_boundary_spread=consensus.boundary_spread,
            consensus_raw_edge_support=consensus.raw_edge_support,
            consensus_confidence=consensus.confidence,
            consensus_reject_reason=consensus.reject_reason,
        )
    return final_result


# Bump when exact seeded association, QC, gap, or segment decisions change.
# Included in TrackingCacheKey so process-local caches cannot serve stale science.
# Packet 06 keeps production gates off (reference full QC + MorphGAC); no v2 bump.
EXACT_TRACKING_ALGORITHM_VERSION: str = "1"

# Canonical *default* mode token (legacy / non-competitive). Competitive uses
# :data:`SEEDED_EXACT_MODE_COMPETITIVE` via request/job-scoped opt-in (Packet 11).
# Renamed from historical ``seeded_exact`` so variant keys never collide.
EXACT_TRACKING_MODE: str = SEEDED_EXACT_MODE_LEGACY

# Progress marker on :class:`TrackProgressEvent` after a frame is committed.
TrackProgressMarker = Literal["partial", "complete", "cancelled"]

# Optional cooperative cancel predicate: return True to stop at the next safe boundary.
CancelCheck = Callable[[], bool]

# Optional progress callback. Invoked only after a frame is written to track state.
ProgressCallback = Callable[["TrackProgressEvent"], None]

# Live scheduling hints: constants or callables re-read at safe Z boundaries.
DirectionPriorityHint = int | Callable[[], int | None] | None
TargetFrameHint = int | Callable[[], int | None] | None


@dataclass(frozen=True)
class TrackProposalState:
    """Small deterministic per-frontier state for rigid-translation proposals.

    Prediction only proposes seed centres and gates association — it never
    creates an accepted mask without a real segmentation pass.
    """

    cx: float
    cy: float
    radius: float
    area_px: float
    vx: float = 0.0
    vy: float = 0.0
    frame_index: int = 0

    def predict_center(self, *, steps: int = 1) -> tuple[float, float]:
        s = max(1, int(steps))
        return (float(self.cx) + float(self.vx) * s, float(self.cy) + float(self.vy) * s)

    def with_accepted(
        self,
        *,
        center_xy: tuple[float, float],
        area_px: float,
        frame_index: int,
        seed_radius: float,
    ) -> TrackProposalState:
        """Update state after an accepted frame (EMA area, finite-diff velocity)."""
        cx, cy = float(center_xy[0]), float(center_xy[1])
        area = max(float(area_px), 1.0)
        r_obs = float(np.sqrt(area / np.pi)) if area > 1.0 else float(seed_radius)
        # Keep radius near user R while tracking observed scale for proposals.
        r_seed = max(float(seed_radius), 1.0)
        radius = float(max(0.5 * r_seed, min(1.6 * r_seed, r_obs)))
        df = int(frame_index) - int(self.frame_index)
        if df != 0:
            vx = (cx - float(self.cx)) / float(df)
            vy = (cy - float(self.cy)) / float(df)
        else:
            vx, vy = float(self.vx), float(self.vy)
        area_ema = 0.7 * float(self.area_px) + 0.3 * area
        return TrackProposalState(
            cx=cx,
            cy=cy,
            radius=radius,
            area_px=max(area_ema, 1.0),
            vx=float(vx),
            vy=float(vy),
            frame_index=int(frame_index),
        )


def proposal_state_from_result(
    result: SeededSliceResult,
    *,
    frame_index: int,
    seed_radius: float,
    prior: TrackProposalState | None = None,
) -> TrackProposalState:
    """Build or update proposal state from an accepted (or seed) result."""
    r0 = max(float(seed_radius), 1.0)
    area = max(float(result.area_px), 1.0)
    r_obs = float(np.sqrt(area / np.pi)) if area > 1.0 else r0
    radius = float(max(0.5 * r0, min(1.6 * r0, r_obs)))
    base = TrackProposalState(
        cx=float(result.center_xy[0]),
        cy=float(result.center_xy[1]),
        radius=radius,
        area_px=area,
        vx=0.0,
        vy=0.0,
        frame_index=int(frame_index),
    )
    if prior is None:
        return base
    return prior.with_accepted(
        center_xy=result.center_xy,
        area_px=result.area_px,
        frame_index=frame_index,
        seed_radius=seed_radius,
    )


def proposal_attempt_centers(
    state: TrackProposalState,
    *,
    gap_count: int,
    seed_xy: tuple[float, float],
    seed_result_center: tuple[float, float] | None,
    include_seed_fallback: bool,
) -> list[tuple[float, float]]:
    """Ordered proposal centres: rigid prediction first; seed only as fallback.

    Identity is never accepted from prediction alone — callers still segment and
    run association gates on each proposal.
    """
    steps = max(1, int(gap_count) + 1)
    predicted = state.predict_center(steps=steps)
    last = (float(state.cx), float(state.cy))
    ordered: list[tuple[float, float]] = [predicted, last]
    if gap_count > 0:
        # After a loss, do not offer the original seed (neighbour steal risk).
        return _dedupe_centers(ordered)
    if include_seed_fallback:
        ordered.append((float(seed_xy[0]), float(seed_xy[1])))
        if seed_result_center is not None:
            ordered.append((float(seed_result_center[0]), float(seed_result_center[1])))
    return _dedupe_centers(ordered)


def _dedupe_centers(centers: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for cx, cy in centers:
        if any(abs(cx - ox) < 1e-6 and abs(cy - oy) < 1e-6 for ox, oy in out):
            continue
        out.append((float(cx), float(cy)))
    return out


def _resolve_direction_priority(hint: DirectionPriorityHint) -> int | None:
    """Resolve +1 / -1 / None; callables are evaluated at safe Z boundaries."""
    value = hint() if callable(hint) else hint
    if value is None:
        return None
    ival = int(value)
    if ival not in (-1, 1):
        raise ValueError("direction_priority must be None, +1, or -1")
    return ival


def _resolve_target_frame(hint: TargetFrameHint, *, n: int) -> int | None:
    """Resolve optional target Z; callables are evaluated at safe Z boundaries."""
    value = hint() if callable(hint) else hint
    if value is None:
        return None
    ival = int(value)
    if ival < 0 or ival >= n:
        raise ValueError("target_frame out of range")
    return ival


@dataclass(frozen=True)
class TrackProgressEvent:
    """Immutable progress snapshot published after a frame result is committed.

    Does not expose internal mutable walk lists. Array fields on ``result`` are
    non-writeable views of the committed buffers so callbacks cannot mutate core
    state in place.
    """

    frame_index: int
    result: SeededSliceResult
    reached_low_z: int
    reached_high_z: int
    marker: TrackProgressMarker


class TrackingCancelled(Exception):
    """Cooperative cancellation of progressive seeded tracking.

    Raised at a safe Z boundary or before starting another retry candidate.
    ``results`` is a full-length list: committed frames keep their values;
    unvisited slots are ``circle_seed_unreached``. Never represents a completed
    track — callers/services must map this to a cancelled/partial job state.
    """

    def __init__(
        self,
        results: list[SeededSliceResult],
        *,
        reached_low_z: int,
        reached_high_z: int,
        message: str = "seeded tracking cancelled",
    ) -> None:
        super().__init__(message)
        self.results = results
        self.reached_low_z = int(reached_low_z)
        self.reached_high_z = int(reached_high_z)


def _result_for_progress(res: SeededSliceResult) -> SeededSliceResult:
    """Return a frozen result with non-writeable array views (shared buffers)."""
    contour = res.contour_xy
    mask = res.solid_mask
    if contour is not None:
        contour = contour.view()
        contour.flags.writeable = False
    if mask is not None:
        mask = mask.view()
        mask.flags.writeable = False
    if contour is res.contour_xy and mask is res.solid_mask:
        return res
    return replace(res, contour_xy=contour, solid_mask=mask)


def _frontiers_from_results(
    results: list[SeededSliceResult | None],
    *,
    seed_frame: int,
) -> tuple[int, int]:
    """Inclusive min/max of committed (non-None) frame indices; seed if empty."""
    committed = [i for i, r in enumerate(results) if r is not None]
    if not committed:
        return seed_frame, seed_frame
    return min(committed), max(committed)


def _materialize_track_results(
    results: list[SeededSliceResult | None],
    *,
    n: int,
    seed_x: float,
    seed_y: float,
) -> list[SeededSliceResult]:
    out: list[SeededSliceResult] = []
    for i in range(n):
        r = results[i] if i < len(results) else None
        if r is None:
            out.append(
                SeededSliceResult(
                    None, None, (seed_x, seed_y), 0.0, 0.0, "circle_seed_unreached", False
                )
            )
        else:
            out.append(r)
    return out


def _raise_if_cancelled(
    cancel_check: CancelCheck | None,
    results: list[SeededSliceResult | None],
    *,
    n: int,
    seed_x: float,
    seed_y: float,
    seed_frame: int,
) -> None:
    if cancel_check is None or not cancel_check():
        return
    low, high = _frontiers_from_results(results, seed_frame=seed_frame)
    raise TrackingCancelled(
        _materialize_track_results(results, n=n, seed_x=seed_x, seed_y=seed_y),
        reached_low_z=low,
        reached_high_z=high,
    )


def _emit_track_progress(
    on_progress: ProgressCallback | None,
    *,
    frame_index: int,
    result: SeededSliceResult,
    results: list[SeededSliceResult | None],
    seed_frame: int,
    marker: TrackProgressMarker,
) -> None:
    """Invoke progress callback after commit. Exceptions propagate; state stays consistent."""
    if on_progress is None and not _INSTR_ENABLED:
        return
    low, high = _frontiers_from_results(results, seed_frame=seed_frame)
    if _INSTR_ENABLED:
        # Lightweight frame row (no full QC blob — QC is available on SeededSliceResult).
        _INSTR.frames.append(
            {
                "frame_index": int(frame_index),
                "marker": str(marker),
                "reached_low_z": int(low),
                "reached_high_z": int(high),
                "ok": bool(result.ok),
                "method": str(result.method),
                "area_px": float(result.area_px),
                "center": [float(result.center_xy[0]), float(result.center_xy[1])],
                "merge_suspect": bool(result.merge_suspect),
                "n_dt_markers": int(result.qc.n_dt_markers) if result.qc is not None else None,
                "eta": float(result.qc.eta) if result.qc is not None else None,
            }
        )
    if on_progress is None:
        return
    event = TrackProgressEvent(
        frame_index=int(frame_index),
        result=_result_for_progress(result),
        reached_low_z=low,
        reached_high_z=high,
        marker=marker,
    )
    # Policy: do not swallow callback errors. The frame is already committed, so
    # re-raising cannot corrupt track state; callers see a consistent partial list
    # if they catch and materialize, or the exception stops the walk.
    on_progress(event)


def _instr_record_association(
    *,
    z: int,
    accepted: bool,
    cand: SeededSliceResult,
    search_radius: float | None,
    seed_x: float,
    seed_y: float,
    gap_count: int,
) -> None:
    if not _INSTR_ENABLED:
        return
    # Lightweight decision row (no full QC blob) — QC lives on accepted frames.
    _INSTR.decisions.append(
        {
            "z": int(z),
            "accepted": bool(accepted),
            "search_radius": float(search_radius) if search_radius is not None else None,
            "attempt_center": [float(seed_x), float(seed_y)],
            "gap_count": int(gap_count),
            "ok": bool(cand.ok),
            "method": str(cand.method),
            "area_px": float(cand.area_px),
            "center": [float(cand.center_xy[0]), float(cand.center_xy[1])],
            "merge_suspect": bool(cand.merge_suspect),
        }
    )


def track_seeded_vesicle_stack(
    stack: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_frame: int,
    seed_radius: float | None = None,
    max_centroid_jump_px: float | None = None,
    max_centroid_jump_um: float | None = None,
    voxel_x_um: float = 1.0,
    voxel_y_um: float = 1.0,
    max_area_ratio: float = 2.2,
    min_area_ratio: float = 0.25,
    target_frame: TargetFrameHint = None,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    direction_priority: DirectionPriorityHint = None,
    competitive_isolation: bool | None = None,
    multiscale_consensus: bool = False,
    profile: str = "vesicle",
) -> list[SeededSliceResult]:
    """Z tracking with user circle radius R.

    When ``max_centroid_jump_um`` is set, centroid gates use physical XY distance
    ``hypot(dx*voxel_x_um, dy*voxel_y_um)``. Otherwise pixel-space ``max_centroid_jump_px``
    (or an internal default) is used.

    If ``target_frame`` is set (interactive preview), only walks seed_frame → target
    (one direction). Full analyze uses ``target_frame=None`` for bidirectional walk.

    Optional progressive controls (all default ``None`` — identical to legacy callers):

    - ``on_progress``: called only after a frame is committed to the returned list.
      Callback exceptions propagate; committed state is not rolled back or mutated.
    - ``cancel_check``: cooperative predicate checked at safe Z boundaries and
      before each retry candidate / segment call. When true, raises
      :class:`TrackingCancelled` with a partial (never complete) result list.
    - ``direction_priority``: for full bidirectional walks, ``+1`` / ``-1`` chooses
      the next legal frontier. May be a callable re-read at each safe Z boundary
      so live reprioritization changes only scheduling (never teleports Z).
      Constant ``None`` keeps legacy order (``+1`` then ``-1``).
    - ``target_frame``: may also be a callable re-read at safe Z boundaries so a
      unidirectional stop can extend toward a farther target without a new walk.
    - ``competitive_isolation``: request-scoped Packet 02/11 experimental path.
      Default None uses process-global test flag (off). Jobs pass an explicit bool.

    Uninterruptible stage: once ``segment_slice_seeded`` begins for a candidate it
    runs to completion; cancel is acknowledged before the next candidate/Z.

    Cache/job identity for this path uses
    :data:`EXACT_TRACKING_ALGORITHM_VERSION` and
    :func:`exact_tracking_mode_token`.
    """
    del min_area_ratio  # replaced by IoU + multi-feature score; keep param for API compat
    use_competitive = resolve_competitive_isolation(competitive_isolation)
    use_consensus = bool(multiscale_consensus)
    if use_competitive and use_consensus:
        raise ValueError("competitive and multi-scale consensus modes are mutually exclusive")
    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("track_seeded_vesicle_stack expects (z, y, x)")
    n = arr.shape[0]
    if seed_frame < 0 or seed_frame >= n:
        raise ValueError("seed_frame out of range")
    # Validate static hints once; callables re-validated when resolved.
    if not callable(target_frame):
        _resolve_target_frame(target_frame, n=n)
    if not callable(direction_priority):
        _resolve_direction_priority(direction_priority)

    R = effective_seed_radius(seed_radius)
    results: list[SeededSliceResult | None] = [None] * n

    # Cancel before any segmentation work.
    _raise_if_cancelled(
        cancel_check,
        results,
        n=n,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_frame=seed_frame,
    )

    first = segment_slice_seeded(
        arr[seed_frame],
        seed_x=seed_x,
        seed_y=seed_y,
        seed_radius=R,
        competitive_isolation=use_competitive,
        multiscale_consensus=use_consensus,
        profile=profile,
    )
    results[seed_frame] = first
    if not first.ok:
        fail_list = [
            SeededSliceResult(None, None, (seed_x, seed_y), 0.0, 0.0, "circle_seed_fail", False)
            for _ in range(n)
        ]
        if use_consensus:
            fail_list[seed_frame] = first
        # Seed commit is the only real result; publish then return (legacy shape).
        _emit_track_progress(
            on_progress,
            frame_index=seed_frame,
            result=first,
            results=results,
            seed_frame=seed_frame,
            marker="complete",
        )
        return fail_list

    _emit_track_progress(
        on_progress,
        frame_index=seed_frame,
        result=first,
        results=results,
        seed_frame=seed_frame,
        marker="partial",
    )
    # Chronological last commit (not max-Z frontier) for the terminal complete event.
    last_committed_z = seed_frame
    last_committed_res: SeededSliceResult = first

    seed_ref_area = max(first.area_px, 1.0)
    jump_um = float(max_centroid_jump_um) if max_centroid_jump_um is not None else None
    jump = max_centroid_jump_px
    if jump_um is None and jump is None:
        jump = max(1.25 * R, 60.0)
    elif jump is None:
        jump = max(1.25 * R, 60.0)  # unused when jump_um set; kept for API symmetry

    def _commit_frame(z: int, res: SeededSliceResult) -> None:
        nonlocal last_committed_z, last_committed_res
        results[z] = res
        last_committed_z = int(z)
        last_committed_res = res
        _emit_track_progress(
            on_progress,
            frame_index=z,
            result=res,
            results=results,
            seed_frame=seed_frame,
            marker="partial",
        )

    def _new_walk_state(direction: int) -> dict[str, Any]:
        prop0 = proposal_state_from_result(first, frame_index=seed_frame, seed_radius=R)
        return {
            "direction": int(direction),
            "proposal": prop0,
            "ref_area": float(seed_ref_area),
            "anchor_x": float(seed_x),
            "anchor_y": float(seed_y),
            "recent_centers": [(prop0.cx, prop0.cy, seed_frame)],
            "last_valid": first,
            "gap_count": 0,
            "z": seed_frame + int(direction),
            "active": True,
        }

    def _advance_one(state: dict[str, Any], stop_at: int | None) -> None:
        """Advance one legal Z step (or deactivate the frontier). Mutates ``state``."""
        direction = int(state["direction"])
        z = int(state["z"])
        if not (0 <= z < n):
            state["active"] = False
            return
        if stop_at is not None:
            if direction > 0 and z > stop_at:
                state["active"] = False
                return
            if direction < 0 and z < stop_at:
                state["active"] = False
                return

        # Safe Z boundary: before starting work on this frame.
        _raise_if_cancelled(
            cancel_check,
            results,
            n=n,
            seed_x=seed_x,
            seed_y=seed_y,
            seed_frame=seed_frame,
        )

        ref_area = float(state["ref_area"])
        prop: TrackProposalState = state["proposal"]
        cx, cy = float(prop.cx), float(prop.cy)
        recent_centers: list[tuple[float, float, int]] = state["recent_centers"]
        last_valid = state["last_valid"]
        gap_count = int(state["gap_count"])

        # Rigid translation proposal from deterministic center/radius/area state.
        # Sync velocity from recent_centers when available (same as prior path).
        vel = _per_frame_velocity(recent_centers)
        if vel is not None:
            prop = TrackProposalState(
                cx=prop.cx,
                cy=prop.cy,
                radius=prop.radius,
                area_px=prop.area_px,
                vx=float(vel[0]),
                vy=float(vel[1]),
                frame_index=prop.frame_index,
            )
            state["proposal"] = prop

        attempts = proposal_attempt_centers(
            prop,
            gap_count=gap_count,
            seed_xy=(float(seed_x), float(seed_y)),
            seed_result_center=(float(first.center_xy[0]), float(first.center_xy[1])),
            include_seed_fallback=True,
        )
        predicted = prop.predict_center(steps=max(1, gap_count + 1))

        prev_z = z - direction
        prev = results[prev_z] if 0 <= prev_z < n else None
        association_prev = prev if (prev is not None and prev.ok) else last_valid
        # Prediction gates association after gaps only — never auto-accepts.
        expected_center = predicted if gap_count > 0 else None
        expected_tolerance = (
            _gap_reacquisition_tolerance(vel, gap_count=gap_count, radius=R)
            if gap_count > 0
            else None
        )
        res: SeededSliceResult | None = None
        for use_r in (R, R * 1.35, R * 1.6):
            for tx, ty in attempts:
                # Before beginning another retry candidate (uninterruptible
                # once segment_slice_seeded starts).
                _raise_if_cancelled(
                    cancel_check,
                    results,
                    n=n,
                    seed_x=seed_x,
                    seed_y=seed_y,
                    seed_frame=seed_frame,
                )
                cand = segment_slice_seeded(
                    arr[z],
                    seed_x=tx,
                    seed_y=ty,
                    seed_radius=use_r,
                    ref_area=ref_area,
                    competitive_isolation=use_competitive,
                    multiscale_consensus=use_consensus,
                    profile=profile,
                )
                accepted = _candidate_accepted(
                    cand,
                    prev=association_prev,
                    ref_area=ref_area,
                    max_area_ratio=max_area_ratio,
                    jump=(jump if jump is not None else 60.0) * (gap_count + 1),
                    jump_um=(jump_um * (gap_count + 1) if jump_um is not None else None),
                    voxel_x_um=float(voxel_x_um),
                    voxel_y_um=float(voxel_y_um),
                    expected_center=expected_center,
                    expected_center_tolerance=expected_tolerance,
                    search_radius=use_r,
                    nominal_radius=R,
                )
                if accepted and use_consensus:
                    anchor_dist = math.hypot(
                        cand.center_xy[0] - float(seed_x), cand.center_xy[1] - float(seed_y)
                    )
                    anchor_frac = 0.50 if R < 30.0 else 0.30
                    accepted = anchor_dist <= max(6.0, anchor_frac * R)
                _instr_record_association(
                    z=z,
                    accepted=accepted,
                    cand=cand,
                    search_radius=use_r,
                    seed_x=tx,
                    seed_y=ty,
                    gap_count=gap_count,
                )
                if not accepted:
                    continue
                res = cand
                break
            if res is not None:
                break

        if res is None:
            gap_res = SeededSliceResult(
                None, None, (cx, cy), 0.0, 0.0, "circle_seed_gap", False
            )
            _commit_frame(z, gap_res)
            if _instr_on():
                _instr_record_event("gap", z=int(z), gap_count=int(gap_count) + 1)
            gap_count += 1
            if gap_count > MAX_CONSECUTIVE_TRACK_GAPS:
                state["active"] = False
                return
            state["gap_count"] = gap_count
            state["z"] = z + direction
            return

        # Cap stop: membrane signal collapsed vs local background.
        # Competitive fills can look "dim vs crowded exterior" while area stays
        # stable mid-band — require intensity collapse *and* area collapse so we
        # do not abort a healthy track (Packet 02 false-cap at Z57/Z58).
        curr_r = np.sqrt(res.area_px / np.pi) if res.area_px > 10.0 else R
        disk_r = max(curr_r * 1.35, curr_r + 15.0)
        full_disk = _disk_mask(arr[z].shape, res.center_xy[0], res.center_xy[1], disk_r)
        intensity_cap = _is_vesicle_cap(arr[z], res.solid_mask, full_disk)
        area_stable = float(res.area_px) >= 0.55 * float(ref_area) if ref_area > 0 else False
        is_cap = bool(intensity_cap) and not (
            str(res.method).startswith(("competitive", "multiscale_consensus")) and area_stable
        )
        if is_cap:
            cap_res = SeededSliceResult(
                res.contour_xy,
                res.solid_mask,
                res.center_xy,
                res.area_px,
                res.perimeter_px,
                "cap_detected",
                False,
                merge_suspect=res.merge_suspect,
                qc=res.qc,
                effective_threshold=res.effective_threshold,
            )
            _commit_frame(z, cap_res)
            if _instr_on():
                _instr_record_event("cap", z=int(z), method="cap_detected")
            state["active"] = False
            return

        _commit_frame(z, res)
        prop = prop.with_accepted(
            center_xy=res.center_xy,
            area_px=res.area_px,
            frame_index=z,
            seed_radius=R,
        )
        recent_centers.append((prop.cx, prop.cy, z))
        if len(recent_centers) > 3:
            recent_centers = recent_centers[-3:]
        state["proposal"] = prop
        state["last_valid"] = res
        state["recent_centers"] = recent_centers
        state["ref_area"] = float(prop.area_px)
        state["gap_count"] = 0
        state["z"] = z + direction

    initial_target = _resolve_target_frame(target_frame, n=n)

    if initial_target is None and not callable(target_frame):
        # Full bidirectional: interleave one Z at a time, re-reading direction
        # priority at each safe boundary so live reprioritization only changes
        # the next legal frontier (no Z teleport). Constant +1 then -1 order
        # when priority stays +1/None matches legacy sequential walks.
        states = {+1: _new_walk_state(+1), -1: _new_walk_state(-1)}
        while states[+1]["active"] or states[-1]["active"]:
            prefer = _resolve_direction_priority(direction_priority)
            if prefer is None:
                prefer = 1
            advanced = False
            for d in (prefer, -prefer):
                st = states[d]
                if not st["active"]:
                    continue
                _advance_one(st, stop_at=None)
                advanced = True
                break
            if not advanced:
                break
    else:
        # Unidirectional toward target; stop_at re-read each step when callable.
        tf0 = _resolve_target_frame(target_frame, n=n)
        if tf0 is not None and tf0 != seed_frame:
            direction = 1 if tf0 > seed_frame else -1
            state = _new_walk_state(direction)
            while state["active"]:
                tf = _resolve_target_frame(target_frame, n=n)
                if tf is None:
                    break
                # If live target flipped to the other side, stop this frontier
                # (full bidirectional path is used when target starts as None).
                if direction > 0 and tf < seed_frame:
                    break
                if direction < 0 and tf > seed_frame:
                    break
                _advance_one(state, stop_at=tf)

    out = _materialize_track_results(results, n=n, seed_x=seed_x, seed_y=seed_y)
    if on_progress is not None:
        # Terminal complete reuses the chronological last partial commit
        # (e.g. low-Z after default bidirectional or direction_priority=+1 second walk).
        _emit_track_progress(
            on_progress,
            frame_index=last_committed_z,
            result=last_committed_res,
            results=results,
            seed_frame=seed_frame,
            marker="complete",
        )
    return out


def furthest_accepted_frontier(
    results: list[SeededSliceResult],
    *,
    seed_frame: int,
    direction: int,
) -> int | None:
    """Inclusive furthest accepted (ok) Z from the seed along ``direction`` (±1)."""
    n = len(results)
    if seed_frame < 0 or seed_frame >= n:
        return None
    furthest: int | None = seed_frame if results[seed_frame].ok else None
    if direction > 0:
        for z in range(seed_frame, n):
            if results[z].ok:
                furthest = z
            elif z > seed_frame and results[z].method == "circle_seed_unreached":
                break
    else:
        for z in range(seed_frame, -1, -1):
            if results[z].ok:
                furthest = z
            elif z < seed_frame and results[z].method == "circle_seed_unreached":
                break
    return furthest


def frame_is_terminal_exact(result: SeededSliceResult | None) -> bool:
    """True when a cache slot is already an exact commit (not an unreached placeholder)."""
    if result is None:
        return False
    if result.ok:
        return True
    return str(result.method) != "circle_seed_unreached"


def extend_track(
    stack: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_frame: int,
    seed_radius: float | None = None,
    target_frame: TargetFrameHint,
    cached_results: list[SeededSliceResult],
    max_centroid_jump_px: float | None = None,
    max_centroid_jump_um: float | None = None,
    voxel_x_um: float = 1.0,
    voxel_y_um: float = 1.0,
    max_area_ratio: float = 2.2,
    min_area_ratio: float = 0.25,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    direction_priority: DirectionPriorityHint = None,
    competitive_isolation: bool | None = None,
    multiscale_consensus: bool = False,
    profile: str = "vesicle",
) -> list[SeededSliceResult]:
    """Extend a previously cached tracking result toward ``target_frame``.

    Progressive controls match :func:`track_seeded_vesicle_stack`. Extends from
    the closest accepted frontier in the target direction; does not resegment
    already accepted frames. ``target_frame`` may be a live callable re-read at
    each safe Z boundary. ``direction_priority`` is accepted for API symmetry
    and ignored for single-direction extension. ``competitive_isolation`` must
    match the variant that produced ``cached_results``.
    """
    del min_area_ratio  # API compat; gating uses IoU + score
    del direction_priority  # single-direction extension; scheduling fixed by target
    use_competitive = resolve_competitive_isolation(competitive_isolation)
    use_consensus = bool(multiscale_consensus)
    if use_competitive and use_consensus:
        raise ValueError("competitive and multi-scale consensus modes are mutually exclusive")
    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("extend_track expects (z, y, x)")
    n = arr.shape[0]
    if seed_frame < 0 or seed_frame >= n:
        raise ValueError("seed_frame out of range")
    if not callable(target_frame):
        _resolve_target_frame(target_frame, n=n)

    results: list[SeededSliceResult] = list(cached_results)
    while len(results) < n:
        results.append(
            SeededSliceResult(
                None, None, (seed_x, seed_y), 0.0, 0.0, "circle_seed_unreached", False
            )
        )
    if len(results) > n:
        results = results[:n]

    # Work on a nullable-compatible view for cancel materialization helpers.
    results_opt: list[SeededSliceResult | None] = list(results)

    tf0 = _resolve_target_frame(target_frame, n=n)
    if tf0 is None or tf0 == seed_frame:
        return results

    existing = results[tf0]
    if frame_is_terminal_exact(existing):
        return results

    direction = 1 if tf0 > seed_frame else -1

    furthest_ok = furthest_accepted_frontier(
        results, seed_frame=seed_frame, direction=direction
    )

    if furthest_ok is None:
        return track_seeded_vesicle_stack(
            arr,
            seed_x=seed_x,
            seed_y=seed_y,
            seed_frame=seed_frame,
            seed_radius=seed_radius,
            max_centroid_jump_px=max_centroid_jump_px,
            max_centroid_jump_um=max_centroid_jump_um,
            voxel_x_um=voxel_x_um,
            voxel_y_um=voxel_y_um,
            max_area_ratio=max_area_ratio,
            target_frame=target_frame,
            on_progress=on_progress,
            cancel_check=cancel_check,
            competitive_isolation=use_competitive,
            multiscale_consensus=use_consensus,
            profile=profile,
        )

    if (direction > 0 and furthest_ok >= tf0) or (
        direction < 0 and furthest_ok <= tf0
    ):
        return results

    _raise_if_cancelled(
        cancel_check,
        results_opt,
        n=n,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_frame=seed_frame,
    )

    R = effective_seed_radius(seed_radius)
    jump_um = float(max_centroid_jump_um) if max_centroid_jump_um is not None else None
    jump = max_centroid_jump_px
    if jump is None:
        jump = max(1.25 * R, 60.0)

    start = results[furthest_ok]
    prop = proposal_state_from_result(start, frame_index=furthest_ok, seed_radius=R)
    ref_area = max(float(prop.area_px), 1.0)
    recent_centers: list[tuple[float, float, int]] = []
    last_valid = start
    if direction > 0:
        for z in range(max(seed_frame, furthest_ok - 2), furthest_ok + 1):
            if results[z].ok:
                recent_centers.append((results[z].center_xy[0], results[z].center_xy[1], z))
    else:
        for z in range(min(seed_frame, furthest_ok + 2), furthest_ok - 1, -1):
            if results[z].ok:
                recent_centers.append((results[z].center_xy[0], results[z].center_xy[1], z))
    if not recent_centers:
        recent_centers.append((prop.cx, prop.cy, furthest_ok))
    seed_center = (
        results[seed_frame].center_xy if results[seed_frame].ok else None
    )

    # Chronological last commit in this extend call (not max-Z frontier).
    last_committed_z: int | None = None
    last_committed_res: SeededSliceResult | None = None

    def _commit_extend(z: int, res: SeededSliceResult) -> None:
        nonlocal last_committed_z, last_committed_res
        results[z] = res
        results_opt[z] = res
        last_committed_z = int(z)
        last_committed_res = res
        _emit_track_progress(
            on_progress,
            frame_index=z,
            result=res,
            results=results_opt,
            seed_frame=seed_frame,
            marker="partial",
        )

    gap_count = 0
    z = furthest_ok + direction
    while 0 <= z < n:
        tf = _resolve_target_frame(target_frame, n=n)
        if tf is None:
            break
        # Cross-seed target: stop this frontier (opposite side is a separate extend).
        if direction > 0 and tf < seed_frame:
            break
        if direction < 0 and tf > seed_frame:
            break
        if direction > 0 and z > tf:
            break
        if direction < 0 and z < tf:
            break

        _raise_if_cancelled(
            cancel_check,
            results_opt,
            n=n,
            seed_x=seed_x,
            seed_y=seed_y,
            seed_frame=seed_frame,
        )

        if results[z].ok:
            prop = prop.with_accepted(
                center_xy=results[z].center_xy,
                area_px=results[z].area_px,
                frame_index=z,
                seed_radius=R,
            )
            ref_area = float(prop.area_px)
            recent_centers.append((prop.cx, prop.cy, z))
            if len(recent_centers) > 3:
                recent_centers = recent_centers[-3:]
            gap_count = 0
            z += direction
            continue

        vel = _per_frame_velocity(recent_centers)
        if vel is not None:
            prop = TrackProposalState(
                cx=prop.cx,
                cy=prop.cy,
                radius=prop.radius,
                area_px=prop.area_px,
                vx=float(vel[0]),
                vy=float(vel[1]),
                frame_index=prop.frame_index,
            )

        attempts = proposal_attempt_centers(
            prop,
            gap_count=gap_count,
            seed_xy=(float(seed_x), float(seed_y)),
            seed_result_center=seed_center,
            include_seed_fallback=True,
        )
        predicted = prop.predict_center(steps=max(1, gap_count + 1))

        prev_z = z - direction
        prev = results[prev_z] if 0 <= prev_z < n else None
        association_prev = prev if (prev is not None and prev.ok) else last_valid
        expected_center = predicted if gap_count > 0 else None
        expected_tolerance = (
            _gap_reacquisition_tolerance(vel, gap_count=gap_count, radius=R)
            if gap_count > 0
            else None
        )
        res: SeededSliceResult | None = None
        for use_r in (R, R * 1.35, R * 1.6):
            for tx, ty in attempts:
                _raise_if_cancelled(
                    cancel_check,
                    results_opt,
                    n=n,
                    seed_x=seed_x,
                    seed_y=seed_y,
                    seed_frame=seed_frame,
                )
                cand = segment_slice_seeded(
                    arr[z],
                    seed_x=tx,
                    seed_y=ty,
                    seed_radius=use_r,
                    ref_area=ref_area,
                    competitive_isolation=use_competitive,
                    multiscale_consensus=use_consensus,
                    profile=profile,
                )
                accepted = _candidate_accepted(
                    cand,
                    prev=association_prev,
                    ref_area=ref_area,
                    max_area_ratio=max_area_ratio,
                    jump=(jump if jump is not None else 60.0) * (gap_count + 1),
                    jump_um=(jump_um * (gap_count + 1) if jump_um is not None else None),
                    voxel_x_um=float(voxel_x_um),
                    voxel_y_um=float(voxel_y_um),
                    expected_center=expected_center,
                    expected_center_tolerance=expected_tolerance,
                    search_radius=use_r,
                    nominal_radius=R,
                )
                if accepted and use_consensus:
                    anchor_dist = math.hypot(
                        cand.center_xy[0] - float(seed_x), cand.center_xy[1] - float(seed_y)
                    )
                    anchor_frac = 0.50 if R < 30.0 else 0.30
                    accepted = anchor_dist <= max(6.0, anchor_frac * R)
                _instr_record_association(
                    z=z,
                    accepted=accepted,
                    cand=cand,
                    search_radius=use_r,
                    seed_x=tx,
                    seed_y=ty,
                    gap_count=gap_count,
                )
                if not accepted:
                    continue
                res = cand
                break
            if res is not None:
                break

        if res is None:
            if results[z].method == "circle_seed_unreached":
                gap_res = SeededSliceResult(
                    None, None, (prop.cx, prop.cy), 0.0, 0.0, "circle_seed_gap", False
                )
                _commit_extend(z, gap_res)
                if _instr_on():
                    _instr_record_event("gap", z=int(z), gap_count=int(gap_count) + 1)
            gap_count += 1
            if gap_count > MAX_CONSECUTIVE_TRACK_GAPS:
                break
            z += direction
            continue

        curr_r = np.sqrt(res.area_px / np.pi) if res.area_px > 10.0 else R
        disk_r = max(curr_r * 1.35, curr_r + 15.0)
        full_disk = _disk_mask(arr[z].shape, res.center_xy[0], res.center_xy[1], disk_r)
        intensity_cap = _is_vesicle_cap(arr[z], res.solid_mask, full_disk)
        area_stable = float(res.area_px) >= 0.55 * float(ref_area) if ref_area > 0 else False
        is_cap = bool(intensity_cap) and not (
            str(res.method).startswith(("competitive", "multiscale_consensus")) and area_stable
        )
        if is_cap:
            cap_res = SeededSliceResult(
                res.contour_xy,
                res.solid_mask,
                res.center_xy,
                res.area_px,
                res.perimeter_px,
                "cap_detected",
                False,
                merge_suspect=res.merge_suspect,
                qc=res.qc,
                effective_threshold=res.effective_threshold,
            )
            _commit_extend(z, cap_res)
            if _instr_on():
                _instr_record_event("cap", z=int(z), method="cap_detected")
            break

        _commit_extend(z, res)
        prop = prop.with_accepted(
            center_xy=res.center_xy,
            area_px=res.area_px,
            frame_index=z,
            seed_radius=R,
        )
        last_valid = res
        recent_centers.append((prop.cx, prop.cy, z))
        if len(recent_centers) > 3:
            recent_centers = recent_centers[-3:]
        ref_area = float(prop.area_px)
        gap_count = 0
        z += direction

    if on_progress is not None and last_committed_z is not None and last_committed_res is not None:
        # Terminal complete matches the final preceding partial of this extend.
        _emit_track_progress(
            on_progress,
            frame_index=last_committed_z,
            result=last_committed_res,
            results=results_opt,
            seed_frame=seed_frame,
            marker="complete",
        )
    return results
