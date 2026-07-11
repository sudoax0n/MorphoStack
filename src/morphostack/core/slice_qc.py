"""Post-segmentation QC for seeded vesicle isolation (rings / GUVs).

Diagnostics support a fail-closed decision tree:
  - Crofton circularity (soft cue only — never a solo hard reject)
  - robust circle-fit residual η = median|r_i| / R̂
  - edge-support fraction along the contour
  - concavity / flat-contact cues
  - constrained one- vs two-circle model comparison (full mode)

Circle / two-circle fits are **QC detectors only** — they are never emitted as
the scientific contour. Contour smoothing is used only for curvature diagnostics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# RANSAC is a QC detector, not a scientific contour generator.  A fixed seed
# makes its diagnostic output reproducible across repeated runs and supported
# scikit-image releases.
_RANSAC_SEED = 0


@dataclass(frozen=True)
class SliceQC:
    """QC bundle for one candidate mask inside the seed disk."""

    circularity: float
    eta: float  # median radial residual / fitted radius
    edge_support: float  # fraction of contour samples on strong edge
    inlier_frac: float  # RANSAC inlier fraction for one-circle fit
    defect_depth_norm: float  # max convexity-defect depth / R̂
    flat_contact_frac: float  # longest low-curvature run / circumference
    delta_bic: float  # BIC_2 - BIC_1; negative prefers two-circle
    n_dt_markers: int
    merge_suspect: bool
    strong_two_circle: bool
    fitted_radius: float
    # ``cheap`` marks display-only diagnostics whose circle/contact fields were
    # intentionally not fitted.  Such a bundle must never drive an exact gate.
    cheap: bool = False

    @property
    def quality_score(self) -> float:
        """Scalar in ~[0, 1] for soft tracking tie-breaks (higher = better)."""
        circ = float(np.clip(self.circularity, 0.0, 1.0))
        eta_term = float(np.clip(1.0 - self.eta / 0.12, 0.0, 1.0))
        edge = float(np.clip(self.edge_support, 0.0, 1.0))
        merge_pen = 0.0 if not self.merge_suspect else 0.35
        raw = 0.35 * circ + 0.35 * eta_term + 0.30 * edge - merge_pen
        return float(np.clip(raw, 0.0, 1.0))


@dataclass(frozen=True)
class SliceQCRef:
    """Seed-frame reference ranges for adaptive thresholds."""

    circularity: float
    eta: float
    edge_support: float
    fitted_radius: float

    @classmethod
    def from_qc(cls, qc: SliceQC) -> SliceQCRef:
        return cls(
            circularity=float(np.clip(qc.circularity, 0.70, 0.98)),
            eta=float(np.clip(qc.eta, 0.01, 0.06)),
            edge_support=float(np.clip(qc.edge_support, 0.55, 0.95)),
            fitted_radius=max(float(qc.fitted_radius), 1.0),
        )


def _contour_xy_from_mask(mask: np.ndarray) -> np.ndarray | None:
    """Return exterior contour as (N, 2) float x,y or None."""
    binary = np.asarray(mask, dtype=bool)
    if not np.any(binary):
        return None
    try:
        import cv2

        cnts, _ = cv2.findContours(
            (binary.astype(np.uint8) * 255),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_NONE,
        )
        if not cnts:
            return None
        best = max(cnts, key=cv2.contourArea)
        if len(best) < 8:
            return None
        pts = best.reshape(-1, 2).astype(np.float64)
        return pts
    except Exception:
        pass
    try:
        from skimage.measure import find_contours

        raw = find_contours(binary.astype(np.float64), 0.5)
        if not raw:
            return None
        best = max(raw, key=len)
        if len(best) < 8:
            return None
        # skimage: (row, col) = (y, x)
        return np.column_stack([best[:, 1], best[:, 0]]).astype(np.float64)
    except Exception:
        return None


def crofton_circularity(mask: np.ndarray) -> tuple[float, float, float]:
    """Return (circularity, area, crofton_perimeter)."""
    binary = np.asarray(mask, dtype=bool)
    if not np.any(binary):
        return 0.0, 0.0, 0.0
    area = float(np.count_nonzero(binary))
    peri = 0.0
    try:
        from skimage.measure import label, regionprops

        lab = label(binary.astype(np.uint8), connectivity=1)
        props = regionprops(lab)
        if props:
            # Largest region (seeded isolation should be one object).
            prop = max(props, key=lambda p: p.area)
            area = float(prop.area)
            if hasattr(prop, "perimeter_crofton"):
                peri = float(prop.perimeter_crofton)
            else:
                peri = float(prop.perimeter)
    except Exception:
        peri = 0.0
    if peri <= 1e-9:
        try:
            from skimage.measure import perimeter

            peri = float(perimeter(binary, neighbourhood=4))
        except Exception:
            peri = float(np.count_nonzero(binary) ** 0.5 * 4.0)
    if peri <= 1e-9:
        return 0.0, area, 0.0
    circ = float((4.0 * math.pi * area) / (peri * peri))
    # Pixelation can push slightly above 1; clamp for downstream soft scores.
    circ = float(np.clip(circ, 0.0, 1.05))
    return circ, area, peri


def _fit_circle_ransac(
    pts: np.ndarray,
    *,
    residual_threshold: float = 2.0,
    max_trials: int = 80,
) -> tuple[tuple[float, float, float] | None, np.ndarray | None, float]:
    """Fit circle; return ((cx,cy,r), inlier_mask, median_abs_residual)."""
    if pts is None or len(pts) < 12:
        return None, None, float("inf")
    xy = np.asarray(pts, dtype=np.float64)

    def algebraic_fallback():
        try:
            x = xy[:, 0]
            y = xy[:, 1]
            A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
            b = x * x + y * y
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            cx, cy = float(sol[0]), float(sol[1])
            r = math.sqrt(max(sol[2] + cx * cx + cy * cy, 1e-6))
            residuals = np.abs(np.hypot(x - cx, y - cy) - r)
            return (cx, cy, r), residuals <= residual_threshold, float(np.median(residuals))
        except Exception:
            return None, None, float("inf")
    try:
        from skimage.measure import CircleModel, ransac
        import inspect

        common = dict(
            data=xy,
            model_class=CircleModel,
            min_samples=3,
            residual_threshold=float(residual_threshold),
            max_trials=int(max_trials),
        )
        try:
            sig = inspect.signature(ransac)
            params = sig.parameters
        except Exception:
            params = {}

        if "rng" in params:
            # skimage >= 0.21 uses rng
            model, inliers = ransac(**common, rng=np.random.default_rng(_RANSAC_SEED))
        elif "random_state" in params:
            # skimage < 0.21 uses random_state
            model, inliers = ransac(**common, random_state=np.random.RandomState(_RANSAC_SEED))
        else:
            # fallback attempt
            try:
                model, inliers = ransac(**common, rng=np.random.default_rng(_RANSAC_SEED))
            except TypeError:
                try:
                    model, inliers = ransac(**common, random_state=np.random.RandomState(_RANSAC_SEED))
                except TypeError:
                    return algebraic_fallback()
        if model is None:
            return None, None, float("inf")
        # skimage≥0.26: center/radius attrs; older: params
        if hasattr(model, "center") and hasattr(model, "radius"):
            cx, cy = float(model.center[0]), float(model.center[1])
            r = float(model.radius)
        elif getattr(model, "params", None) is not None:
            cx, cy, r = (float(model.params[0]), float(model.params[1]), float(model.params[2]))
        else:
            return None, None, float("inf")
        if not np.isfinite(r) or r < 1.0:
            return None, None, float("inf")
        residuals = np.abs(model.residuals(xy))
        med = float(np.median(residuals))
        if inliers is None:
            inliers = residuals <= residual_threshold
        return (cx, cy, r), np.asarray(inliers, dtype=bool), med
    except Exception:
        return algebraic_fallback()


def _edge_support(
    image: np.ndarray,
    pts: np.ndarray,
    *,
    tau_frac: float = 0.55,
) -> float:
    """Fraction of contour samples sitting on a strong gradient ridge."""
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2 or pts is None or len(pts) < 4:
        return 0.0
    try:
        from skimage.filters import sobel

        grad = sobel(arr)
    except Exception:
        gy, gx = np.gradient(arr)
        grad = np.hypot(gx, gy)
    h, w = arr.shape
    xs = np.clip(np.round(pts[:, 0]).astype(int), 0, w - 1)
    ys = np.clip(np.round(pts[:, 1]).astype(int), 0, h - 1)
    samples = grad[ys, xs]
    if samples.size == 0:
        return 0.0
    # Adaptive threshold from contour neighborhood strength.
    tau = float(np.percentile(samples, 40.0)) * float(tau_frac) / 0.55
    # Also require vs global mid-gradient so empty frames fail.
    g_med = float(np.median(grad)) if grad.size else 0.0
    tau = max(tau, g_med * 1.05, 1e-6)
    return float(np.mean(samples >= tau))


def _convexity_defect_depth_norm(pts: np.ndarray, radius: float) -> float:
    """Max significant convexity-defect depth / radius after light simplification."""
    if pts is None or len(pts) < 12 or radius <= 1e-6:
        return 0.0
    try:
        import cv2

        approx = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2), epsilon=1.5, closed=True)
        if approx is None or len(approx) < 4:
            return 0.0
        hull = cv2.convexHull(approx, returnPoints=False)
        if hull is None or len(hull) < 3:
            return 0.0
        defects = cv2.convexityDefects(approx, hull)
        if defects is None:
            return 0.0
        # depth is in fixed-point 1/256 px
        depths = defects[:, 0, 3].astype(np.float64) / 256.0
        if depths.size == 0:
            return 0.0
        return float(np.max(depths) / max(radius, 1.0))
    except Exception:
        return 0.0


def _flat_contact_fraction(pts: np.ndarray, radius: float) -> float:
    """Longest low-curvature run length / circumference (diagnostic only)."""
    if pts is None or len(pts) < 24 or radius <= 1e-6:
        return 0.0
    xy = np.asarray(pts, dtype=np.float64)
    # Light smoothing for curvature only (not for morphometry output).
    try:
        from scipy.ndimage import uniform_filter1d

        xs = uniform_filter1d(xy[:, 0], size=5, mode="wrap")
        ys = uniform_filter1d(xy[:, 1], size=5, mode="wrap")
    except Exception:
        xs, ys = xy[:, 0], xy[:, 1]
    # Finite-difference curvature κ ≈ |x'y'' - y'x''| / (x'^2+y'^2)^{3/2}
    dx = np.gradient(xs)
    dy = np.gradient(ys)
    ddx = np.gradient(dx)
    ddy = np.gradient(dy)
    denom = np.power(dx * dx + dy * dy, 1.5) + 1e-9
    kappa = np.abs(dx * ddy - dy * ddx) / denom
    # Nominal circle curvature is 1/R; flat contact << that.
    thr = 0.35 / max(radius, 1.0)
    low = kappa < thr
    # Longest circular run
    n = len(low)
    if n == 0:
        return 0.0
    extended = np.concatenate([low, low])
    best = cur = 0
    for v in extended:
        if v:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    best = min(best, n)
    # Chord/arc sanity: for a flat run, endpoint chord ≈ arc length
    if best < 6:
        return 0.0
    # Approximate arc length from consecutive points
    step = float(np.mean(np.hypot(np.diff(xs), np.diff(ys))))
    arc = best * max(step, 1e-6)
    circ = 2.0 * math.pi * radius
    return float(np.clip(arc / max(circ, 1e-6), 0.0, 1.0))


def _rss_circle(pts: np.ndarray, cx: float, cy: float, r: float) -> float:
    d = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    return float(np.sum((d - r) ** 2))


def _two_circle_delta_bic(
    pts: np.ndarray,
    one_params: tuple[float, float, float],
    *,
    seed_radius: float,
) -> float:
    """BIC_2 - BIC_1. Strongly negative favors a two-circle merge model.

    Detector only — does not emit fitted circles as contours.
    """
    xy = np.asarray(pts, dtype=np.float64)
    n = len(xy)
    if n < 24:
        return 0.0
    cx1, cy1, r1 = one_params
    rss1 = _rss_circle(xy, cx1, cy1, r1)
    # Partition by angle around one-circle center (two half-arcs).
    ang = np.arctan2(xy[:, 1] - cy1, xy[:, 0] - cx1)
    # Try a few split angles; pick best constrained two-circle RSS.
    best_rss2 = float("inf")
    R = max(float(seed_radius), 1.0)
    for offset in (0.0, math.pi / 3.0, 2.0 * math.pi / 3.0):
        a = (ang + offset + math.pi) % (2.0 * math.pi)
        mask_a = a < math.pi
        if int(np.count_nonzero(mask_a)) < 10 or int(np.count_nonzero(~mask_a)) < 10:
            continue
        fit_a, _, _ = _fit_circle_ransac(xy[mask_a], residual_threshold=2.5, max_trials=40)
        fit_b, _, _ = _fit_circle_ransac(xy[~mask_a], residual_threshold=2.5, max_trials=40)
        if fit_a is None or fit_b is None:
            continue
        cxa, cya, ra = fit_a
        cxb, cyb, rb = fit_b
        # Plausibility constraints from research brief.
        if not (0.6 * R <= ra <= 1.4 * R and 0.6 * R <= rb <= 1.4 * R):
            continue
        d12 = math.hypot(cxa - cxb, cya - cyb)
        if not (0.6 * R <= d12 <= 1.8 * R):
            continue
        rss = _rss_circle(xy[mask_a], cxa, cya, ra) + _rss_circle(xy[~mask_a], cxb, cyb, rb)
        if rss < best_rss2:
            best_rss2 = rss
    if not np.isfinite(best_rss2) or best_rss2 >= float("inf"):
        return 0.0
    # Gaussian BIC ≈ n ln(RSS/n) + k ln n
    rss1 = max(rss1, 1e-9)
    best_rss2 = max(best_rss2, 1e-9)
    bic1 = n * math.log(rss1 / n) + 3.0 * math.log(n)
    bic2 = n * math.log(best_rss2 / n) + 6.0 * math.log(n)
    return float(bic2 - bic1)


def count_dt_markers(mask: np.ndarray, seed_radius: float) -> int:
    """Count reliable distance-transform peaks (h-maxima style)."""
    binary = np.asarray(mask, dtype=bool)
    if not np.any(binary):
        return 0
    try:
        from scipy import ndimage as ndi
        from skimage.feature import peak_local_max
        from skimage.morphology import h_maxima
    except Exception:
        return 0
    try:
        filled = ndi.binary_fill_holes(binary)
    except Exception:
        filled = binary
    distance = ndi.distance_transform_edt(filled)
    if float(np.max(distance)) <= 1.0:
        return 0
    # Suppress shallow noise peaks.
    h = max(1.0, 0.25 * float(np.max(distance)))
    try:
        peaks_img = h_maxima(distance, h)
        n_h = int(np.count_nonzero(peaks_img))
        if n_h >= 1:
            # Still require geometric separation.
            coords = peak_local_max(
                distance,
                min_distance=max(3, int(round(float(seed_radius) * 0.55))),
                labels=filled.astype(np.int32),
                exclude_border=False,
            )
            return int(len(coords)) if coords is not None else n_h
    except Exception:
        pass
    try:
        coords = peak_local_max(
            distance,
            min_distance=max(3, int(round(float(seed_radius) * 0.7))),
            labels=filled.astype(np.int32),
            exclude_border=False,
        )
        return int(len(coords)) if coords is not None else 0
    except Exception:
        return 0


def compute_slice_qc(
    mask: np.ndarray,
    image: np.ndarray | None,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    cheap: bool = False,
) -> SliceQC:
    """Compute QC diagnostics for a candidate solid mask.

    ``cheap=True`` is display-only: it computes circularity and edge support,
    but skips RANSAC, BIC/two-circle fitting, convexity/contact diagnostics,
    and distance-transform markers.
    """
    del seed_x, seed_y  # reserved for future seed-relative residual weighting
    binary = np.asarray(mask, dtype=bool)
    R = max(float(seed_radius), 1.0)
    circ, _area, _peri = crofton_circularity(binary)
    pts = _contour_xy_from_mask(binary)
    eta = 0.25
    inlier_frac = 0.0
    fitted_r = R
    edge = 0.0
    defect = 0.0
    flat = 0.0
    delta_bic = 0.0
    n_markers = count_dt_markers(binary, R) if not cheap else 0

    if pts is not None and len(pts) >= 12:
        if image is not None:
            edge = _edge_support(image, pts)
        if not cheap:
            fit, inliers, med = _fit_circle_ransac(
                pts,
                residual_threshold=max(1.5, 0.08 * R),
                max_trials=80,
            )
            if fit is not None:
                fitted_r = max(float(fit[2]), 1.0)
                eta = float(med / fitted_r)
                if inliers is not None and inliers.size:
                    inlier_frac = float(np.mean(inliers))
            defect = _convexity_defect_depth_norm(pts, fitted_r)
            flat = _flat_contact_fraction(pts, fitted_r)
            if fit is not None:
                delta_bic = _two_circle_delta_bic(pts, fit, seed_radius=R)

    strong_two = bool(not cheap and delta_bic <= -10.0)
    if strong_two and defect <= 0.06 and n_markers <= 1:
        strong_two = False

    if cheap:
        merge_suspect = False
    else:
        merge_suspect = bool(
            strong_two
            or flat >= 0.12
            or defect > 0.07
            or (eta > 0.10 and edge < 0.55)
            or (n_markers >= 2 and (eta > 0.06 or circ < 0.82))
        )

    return SliceQC(
        circularity=circ,
        eta=eta,
        edge_support=edge,
        inlier_frac=inlier_frac,
        defect_depth_norm=defect,
        flat_contact_frac=flat,
        delta_bic=delta_bic,
        n_dt_markers=n_markers,
        merge_suspect=merge_suspect,
        strong_two_circle=strong_two,
        fitted_radius=fitted_r,
        cheap=bool(cheap),
    )


def accept_as_is(
    qc: SliceQC,
    *,
    ref: SliceQCRef | None = None,
) -> bool:
    """Research accept-as-is rule (soft circularity only)."""
    e_min = 0.55
    eta_max = 0.08
    if ref is not None:
        e_min = max(0.55, ref.edge_support - 0.20)
        eta_max = max(0.08, 1.8 * ref.eta)
    if qc.edge_support < e_min:
        return False
    if qc.eta > eta_max:
        return False
    if qc.defect_depth_norm > 0.07:
        return False
    if qc.flat_contact_frac >= 0.12:
        return False
    if qc.delta_bic <= -6.0:
        return False
    return True


def should_attempt_split(qc: SliceQC) -> bool:
    """Thin-neck / multi-marker / strong two-circle → try watershed split."""
    if qc.cheap:
        return False
    if qc.n_dt_markers >= 2:
        return True
    if qc.defect_depth_norm > 0.07:
        return True
    if qc.strong_two_circle:
        return True
    return False


def should_attempt_polar_repair(qc: SliceQC, *, ref: SliceQCRef | None = None) -> bool:
    """Broad-contact / unimodal merge suspicion → polar DP repair."""
    if qc.cheap:
        return False
    if qc.flat_contact_frac >= 0.12:
        return True
    c_floor = 0.72
    if ref is not None:
        c_floor = max(0.72, ref.circularity - 0.12)
    if qc.circularity < c_floor and qc.eta > 0.06:
        return True
    if qc.merge_suspect and qc.n_dt_markers <= 1:
        return True
    if qc.eta > 0.10 and qc.edge_support >= 0.35:
        return True
    return False


def repair_improves(before: SliceQC, after: SliceQC) -> bool:
    """Accept polar/split repair only if QC improves (research thresholds)."""
    if before.cheap or after.cheap:
        return False
    edge_gain = after.edge_support - before.edge_support
    eta_drop = (before.eta - after.eta) / max(before.eta, 1e-6)
    if edge_gain >= 0.08:
        return True
    if eta_drop >= 0.20 and after.edge_support >= max(0.35, before.edge_support - 0.05):
        return True
    if before.merge_suspect and not after.merge_suspect and after.edge_support >= 0.45:
        return True
    return False


def multi_object_cue_count(qc: SliceQC) -> int:
    """Count independent multi-object / contact cues (not circularity, not edge).

    Used for composite fail-closed decisions. A single raw cue (one weak DT
    peak pair, mild flatness, etc.) is insufficient alone.
    """
    n = 0
    if qc.strong_two_circle:
        n += 1
    if qc.n_dt_markers >= 2:
        n += 1
    if qc.delta_bic <= -5.0:
        n += 1
    if qc.flat_contact_frac >= 0.12:
        n += 1
    if qc.defect_depth_norm > 0.07:
        n += 1
    # Radial inconsistency vs single-circle model (not circularity itself).
    if qc.eta > 0.10:
        n += 1
    return n


def fail_closed(qc: SliceQC) -> bool:
    """Unresolved multi-object mixture or collapsed membrane → reject slice.

    Callers run this **after** split/polar repair attempts. Edge support is
    membrane evidence only — high edge must not salvage a genuinely mixed
    exterior (the prior acceptance hole). Circularity alone never fails closed.

    Rejection requires **composite** multi-object evidence: residual
    ``merge_suspect`` plus at least two independent cues, or an explicit
    strong two-body + contact combination. A lone flat/concave/deformed
    single-object cue must not hard-reject.
    """
    if qc.cheap:
        return False
    if qc.edge_support < 0.25:
        return True

    cues = multi_object_cue_count(qc)
    contact_geo = qc.flat_contact_frac >= 0.10 or qc.defect_depth_norm > 0.06

    # Strong two-circle model plus contact geometry (or multi markers).
    if qc.strong_two_circle and (contact_geo or qc.n_dt_markers >= 2 or qc.eta > 0.08):
        return True
    # Multiple DT peaks only with another multi-object cue.
    if qc.n_dt_markers >= 2 and (
        contact_geo or qc.strong_two_circle or qc.delta_bic <= -5.0 or qc.eta > 0.08
    ):
        return True
    # Unresolved merge_suspect after repair: need ≥2 independent cues so a
    # legitimate pear/flat single object is not rejected for one raw flag.
    if qc.merge_suspect and cues >= 2:
        return True
    return False
