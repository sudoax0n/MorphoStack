"""Labelled synthetic safety gates for Point 3 contact QC.

These fixtures are regression evidence only: they prove identity/isolation
decision boundaries on deterministic rings, not biological validity on real
microscopy. Real CZI/LSM sign-off is documented separately.

Safe outcome rule for every labelled case:
  - accept: target IoU and centroid error within bounds AND neighbour
    contamination strictly low; OR
  - explicit reject/lost (circle_seed_merge_reject / circle_seed_fail), never
    a silently accepted mixed contour.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from morphostack.core.seeded_vesicle import SeededSliceResult, segment_slice_seeded
from morphostack.core.slice_qc import compute_slice_qc


# ---------------------------------------------------------------------------
# Geometry helpers (small deterministic fixtures; no large assets)
# ---------------------------------------------------------------------------


def _ring(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float, value: float = 1.0) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = value
    return frame


def _filled_disk(h: int, w: int, cx: float, cy: float, r: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r**2


def _filled_ellipse(h: int, w: int, cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0


def _rim_from_solid(solid: np.ndarray, iterations: int = 2) -> np.ndarray:
    from scipy import ndimage as ndi

    eroded = ndi.binary_erosion(solid, iterations=iterations)
    rim = solid ^ eroded
    frame = np.zeros(solid.shape, dtype=np.float64)
    frame[rim] = 1.0
    return frame


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    aa = np.asarray(a, dtype=bool)
    bb = np.asarray(b, dtype=bool)
    inter = int(np.count_nonzero(aa & bb))
    union = int(np.count_nonzero(aa | bb))
    return float(inter / union) if union else 0.0


def _centroid_xy(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.where(np.asarray(mask, dtype=bool))
    if ys.size == 0:
        return float("nan"), float("nan")
    return float(xs.mean()), float(ys.mean())


def _neighbor_contamination(
    pred: np.ndarray,
    neighbor: np.ndarray | None,
    target: np.ndarray | None = None,
) -> float:
    """Fraction of predicted pixels in the *exclusive* neighbour body.

    Contacting solid disks share a geometric lens. Counting ``pred ∩ neighbor``
    would flag a pure target mask as contaminated. Safety cares about the
    neighbour-only region: ``neighbor & ~target``.
    """
    if neighbor is None:
        return 0.0
    p = np.asarray(pred, dtype=bool)
    n = np.asarray(neighbor, dtype=bool)
    if target is not None:
        n = n & ~np.asarray(target, dtype=bool)
    pred_n = int(np.count_nonzero(p))
    if pred_n == 0:
        return 0.0
    return float(np.count_nonzero(p & n) / pred_n)


SAFE_REJECT_METHODS = frozenset(
    {
        "circle_seed_merge_reject",
        "circle_seed_fail",
        "circle_seed_gap",
    }
)


@dataclass(frozen=True)
class LabelledFixture:
    """Known target / neighbour solid masks plus a membrane image."""

    name: str
    frame: np.ndarray
    target_mask: np.ndarray
    neighbor_mask: np.ndarray | None
    seed_x: float
    seed_y: float
    seed_radius: float
    # Clean / deformed singles should accept; contact cases may reject.
    must_accept: bool = False
    refine: bool = False
    # IoU floor when accepted (filled GT vs filled prediction).
    min_target_iou: float = 0.40
    max_centroid_err_px: float = 6.0
    # Exclusive neighbour-body fraction of the prediction (see helper).
    max_neighbor_contamination: float = 0.08


def assert_safe_outcome(res: SeededSliceResult, fx: LabelledFixture) -> None:
    """Accept with isolation bounds, or explicit safe rejection — never silent mix."""
    if res.ok:
        assert res.solid_mask is not None, f"{fx.name}: ok without solid_mask"
        assert res.contour_xy is not None and len(res.contour_xy) > 8
        assert res.method not in SAFE_REJECT_METHODS

        iou = _mask_iou(res.solid_mask, fx.target_mask)
        tcx, tcy = _centroid_xy(fx.target_mask)
        pcx, pcy = float(res.center_xy[0]), float(res.center_xy[1])
        cent_err = float(np.hypot(pcx - tcx, pcy - tcy))
        contam = _neighbor_contamination(res.solid_mask, fx.neighbor_mask, fx.target_mask)

        assert iou >= fx.min_target_iou, (
            f"{fx.name}: accepted but target IoU={iou:.3f} < {fx.min_target_iou}"
        )
        assert cent_err <= fx.max_centroid_err_px, (
            f"{fx.name}: centroid error {cent_err:.2f}px > {fx.max_centroid_err_px}"
        )
        assert contam <= fx.max_neighbor_contamination, (
            f"{fx.name}: exclusive neighbour contamination {contam:.3f} > "
            f"{fx.max_neighbor_contamination}"
        )
        if fx.neighbor_mask is not None:
            # Neighbour body center must not be claimed by an accepted mask.
            ncx, ncy = _centroid_xy(fx.neighbor_mask)
            if np.isfinite(ncx):
                assert not res.solid_mask[int(round(ncy)), int(round(ncx))], (
                    f"{fx.name}: accepted mask includes neighbour center"
                )
    else:
        assert res.method in SAFE_REJECT_METHODS, (
            f"{fx.name}: unexpected fail method {res.method!r}"
        )
        if res.method == "circle_seed_merge_reject":
            assert res.merge_suspect is True
        # Must not claim a mixed contour on reject.
        assert res.solid_mask is None
        assert res.contour_xy is None
        if fx.must_accept:
            pytest.fail(
                f"{fx.name}: required accept but got safe reject ({res.method}); "
                "do not reject legitimate single-object shape alone"
            )


# ---------------------------------------------------------------------------
# Labelled fixtures
# ---------------------------------------------------------------------------


def fixture_clean_isolated_ring() -> LabelledFixture:
    h = w = 100
    cx, cy, r = 50.0, 50.0, 16.0
    frame = _ring(h, w, cx, cy, r - 4, r)
    target = _filled_disk(h, w, cx, cy, r)
    return LabelledFixture(
        name="clean_isolated_circular_ring",
        frame=frame,
        target_mask=target,
        neighbor_mask=None,
        seed_x=cx,
        seed_y=cy,
        seed_radius=r,
        must_accept=True,
        min_target_iou=0.55,
        max_centroid_err_px=4.0,
    )


def fixture_flattened_ellipse_single() -> LabelledFixture:
    """Legitimate deformed single vesicle — must not be rejected solely for shape."""
    h = w = 100
    cx, cy = 50.0, 50.0
    rx, ry = 22.0, 14.0
    solid = _filled_ellipse(h, w, cx, cy, rx, ry)
    frame = _rim_from_solid(solid, iterations=2)
    # Seed radius large enough to cover major axis.
    return LabelledFixture(
        name="flattened_elliptical_single",
        frame=frame,
        target_mask=solid,
        neighbor_mask=None,
        seed_x=cx,
        seed_y=cy,
        seed_radius=22.0,
        must_accept=True,
        min_target_iou=0.45,
        max_centroid_err_px=5.0,
    )


def fixture_tangent_neighbour() -> LabelledFixture:
    h = w = 100
    # Centers ~ 2R apart → external tangent contact of solid disks.
    tcx, tcy, tr = 38.0, 50.0, 14.0
    ncx, ncy, nr = 66.0, 50.0, 14.0
    frame = np.clip(
        _ring(h, w, tcx, tcy, tr - 4, tr) + _ring(h, w, ncx, ncy, nr - 4, nr),
        0.0,
        1.0,
    )
    return LabelledFixture(
        name="tangent_neighbour",
        frame=frame,
        target_mask=_filled_disk(h, w, tcx, tcy, tr),
        neighbor_mask=_filled_disk(h, w, ncx, ncy, nr),
        seed_x=tcx,
        seed_y=tcy,
        seed_radius=tr,
        must_accept=False,
        min_target_iou=0.40,
        max_centroid_err_px=5.0,
        max_neighbor_contamination=0.10,
    )


def fixture_overlapping_neck() -> LabelledFixture:
    h = w = 100
    tcx, tcy, tr = 36.0, 50.0, 14.0
    ncx, ncy, nr = 58.0, 50.0, 14.0  # center distance 22 < 28 → overlap
    frame = np.clip(
        _ring(h, w, tcx, tcy, tr - 4, tr) + _ring(h, w, ncx, ncy, nr - 4, nr),
        0.0,
        1.0,
    )
    # Thin painted neck in intensity to encourage merge candidates.
    frame[48:53, 44:52] = np.maximum(frame[48:53, 44:52], 0.85)
    return LabelledFixture(
        name="overlapping_neck_contact",
        frame=frame,
        target_mask=_filled_disk(h, w, tcx, tcy, tr),
        neighbor_mask=_filled_disk(h, w, ncx, ncy, nr),
        seed_x=tcx,
        seed_y=tcy,
        seed_radius=tr,
        must_accept=False,
        min_target_iou=0.38,
        max_centroid_err_px=6.0,
        max_neighbor_contamination=0.10,
    )


def fixture_broad_flat_contact() -> LabelledFixture:
    h = w = 120
    tcx, tcy, tr = 48.0, 60.0, 18.0
    ncx, ncy, nr = 72.0, 60.0, 18.0  # distance 24, sum radii 36 → broad overlap
    frame = np.clip(
        _ring(h, w, tcx, tcy, tr - 4, tr) + _ring(h, w, ncx, ncy, nr - 4, nr),
        0.0,
        1.0,
    )
    return LabelledFixture(
        name="broad_flat_contact",
        frame=frame,
        target_mask=_filled_disk(h, w, tcx, tcy, tr),
        neighbor_mask=_filled_disk(h, w, ncx, ncy, nr),
        seed_x=tcx,
        seed_y=tcy,
        seed_radius=tr,
        must_accept=False,
        min_target_iou=0.38,
        max_centroid_err_px=6.0,
        max_neighbor_contamination=0.10,
    )


def fixture_partial_neighbour_lobe() -> LabelledFixture:
    """Close rings where MorphGAC refinement can pull a partial neighbour lobe."""
    h = w = 100
    tcx, tcy, tr = 40.0, 50.0, 14.0
    ncx, ncy, nr = 64.0, 50.0, 14.0
    frame = np.clip(
        _ring(h, w, tcx, tcy, tr - 4, tr) + _ring(h, w, ncx, ncy, nr - 4, nr),
        0.0,
        1.0,
    )
    return LabelledFixture(
        name="partial_neighbour_lobe_after_refine",
        frame=frame,
        target_mask=_filled_disk(h, w, tcx, tcy, tr),
        neighbor_mask=_filled_disk(h, w, ncx, ncy, nr),
        seed_x=tcx,
        seed_y=tcy,
        seed_radius=tr,
        must_accept=False,
        refine=True,
        min_target_iou=0.38,
        max_centroid_err_px=6.0,
        max_neighbor_contamination=0.10,
    )


def fixture_weak_broken_membrane() -> LabelledFixture:
    """Weak (dim) target membrane with a bright neighbour distractor.

    A fully open polar arc often yields only a tiny unfilled membrane
    fragment; that regime prefers conservative reject over a bogus contour
    (see report). Here the target remains a continuous but dim ring so the
    safety gate is well-posed: recover within IoU bounds without claiming
    the brighter neighbour, or fail closed.
    """
    h = w = 100
    tcx, tcy, tr = 40.0, 50.0, 16.0
    ncx, ncy, nr = 72.0, 50.0, 14.0
    # Dim continuous target ring (weak SNR) vs bright distractor.
    target = _ring(h, w, tcx, tcy, tr - 5, tr, value=0.40)
    neighbor = _ring(h, w, ncx, ncy, nr - 4, nr, value=1.0)
    frame = np.clip(target + neighbor, 0.0, 1.0)
    return LabelledFixture(
        name="weak_broken_target_near_distractor",
        frame=frame,
        target_mask=_filled_disk(h, w, tcx, tcy, tr),
        neighbor_mask=_filled_disk(h, w, ncx, ncy, nr),
        seed_x=tcx,
        seed_y=tcy,
        seed_radius=tr,
        must_accept=False,
        min_target_iou=0.45,
        max_centroid_err_px=5.0,
        max_neighbor_contamination=0.08,
    )


ALL_LABELLED = [
    fixture_clean_isolated_ring,
    fixture_flattened_ellipse_single,
    fixture_tangent_neighbour,
    fixture_overlapping_neck,
    fixture_broad_flat_contact,
    fixture_partial_neighbour_lobe,
    fixture_weak_broken_membrane,
]


# ---------------------------------------------------------------------------
# Safety outcome tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ALL_LABELLED, ids=lambda f: f().name)
def test_labelled_safe_isolation_or_explicit_reject(factory):
    fx = factory()
    res = segment_slice_seeded(
        fx.frame,
        seed_x=fx.seed_x,
        seed_y=fx.seed_y,
        seed_radius=fx.seed_radius,
        refine=fx.refine,
    )
    assert_safe_outcome(res, fx)


def test_clean_isolated_must_accept_with_bounds():
    fx = fixture_clean_isolated_ring()
    res = segment_slice_seeded(
        fx.frame,
        seed_x=fx.seed_x,
        seed_y=fx.seed_y,
        seed_radius=fx.seed_radius,
        refine=False,
    )
    assert res.ok
    assert not res.merge_suspect
    assert_safe_outcome(res, fx)


def test_flattened_ellipse_not_rejected_for_shape_alone():
    fx = fixture_flattened_ellipse_single()
    res = segment_slice_seeded(
        fx.frame,
        seed_x=fx.seed_x,
        seed_y=fx.seed_y,
        seed_radius=fx.seed_radius,
        refine=False,
    )
    # Shape alone must not force merge_reject; accept is required for this single object.
    assert res.ok, f"ellipse rejected as {res.method} (shape-only reject is unsafe)"
    assert res.method != "circle_seed_merge_reject"
    assert_safe_outcome(res, fx)


def test_partial_neighbour_lobe_candidate_never_silent_mix():
    """Refinement-like close-contact: isolation bounds or explicit merge reject."""
    fx = fixture_partial_neighbour_lobe()
    res = segment_slice_seeded(
        fx.frame,
        seed_x=fx.seed_x,
        seed_y=fx.seed_y,
        seed_radius=fx.seed_radius,
        refine=True,
    )
    assert_safe_outcome(res, fx)
    if not res.ok:
        assert res.method == "circle_seed_merge_reject"


def test_injected_mixed_mask_fails_qc_or_bounds():
    """A deliberately mixed solid candidate must not pass isolation bounds."""
    fx = fixture_overlapping_neck()
    mixed = fx.target_mask | fx.neighbor_mask
    contam = _neighbor_contamination(mixed, fx.neighbor_mask, fx.target_mask)
    assert contam > fx.max_neighbor_contamination
    # Exclusive neighbour body is largely claimed by the dual-blob mask.
    exclusive = fx.neighbor_mask & ~fx.target_mask
    claimed = float(np.count_nonzero(mixed & exclusive) / max(1, np.count_nonzero(exclusive)))
    assert claimed > 0.5
    qc = compute_slice_qc(
        mixed,
        fx.frame,
        seed_x=fx.seed_x,
        seed_y=fx.seed_y,
        seed_radius=fx.seed_radius,
        cheap=False,
    )
    # Full QC should flag contact or two-circle structure on a dual blob.
    assert (
        qc.merge_suspect
        or qc.flat_contact_frac >= 0.08
        or qc.strong_two_circle
        or qc.n_dt_markers >= 2
        or qc.eta > 0.06
    )


# ---------------------------------------------------------------------------
# Repeatability of full decision path
# ---------------------------------------------------------------------------


def test_repeated_decision_identical_over_12_runs():
    """Full segment path + QC must be bit-stable across ≥12 calls on a fixed fixture."""
    fx = fixture_broad_flat_contact()
    results: list[SeededSliceResult] = []
    for _ in range(12):
        results.append(
            segment_slice_seeded(
                fx.frame,
                seed_x=fx.seed_x,
                seed_y=fx.seed_y,
                seed_radius=fx.seed_radius,
                refine=False,
            )
        )

    first = results[0]
    for i, res in enumerate(results[1:], start=2):
        assert res.ok == first.ok, f"ok mismatch at run {i}"
        assert res.method == first.method, f"method mismatch at run {i}: {res.method} vs {first.method}"
        assert res.merge_suspect == first.merge_suspect, f"merge_suspect mismatch at run {i}"
        assert res.area_px == first.area_px, f"area_px mismatch at run {i}"
        assert res.center_xy == first.center_xy, f"center_xy mismatch at run {i}"
        if first.qc is not None and res.qc is not None:
            assert res.qc.merge_suspect == first.qc.merge_suspect
            assert res.qc.delta_bic == first.qc.delta_bic
            assert res.qc.eta == first.qc.eta
            assert res.qc.inlier_frac == first.qc.inlier_frac
            assert res.qc.flat_contact_frac == first.qc.flat_contact_frac
            assert res.qc.circularity == first.qc.circularity
        assert_safe_outcome(res, fx)


def test_qc_numeric_repeatability_20_runs():
    """Direct compute_slice_qc determinism (RANSAC seed fixed in implementation)."""
    fx = fixture_broad_flat_contact()
    solid = fx.target_mask | fx.neighbor_mask
    first = compute_slice_qc(
        solid, fx.frame, seed_x=fx.seed_x, seed_y=fx.seed_y, seed_radius=fx.seed_radius, cheap=False
    )
    for i in range(19):
        qc = compute_slice_qc(
            solid, fx.frame, seed_x=fx.seed_x, seed_y=fx.seed_y, seed_radius=fx.seed_radius, cheap=False
        )
        assert qc.delta_bic == first.delta_bic, f"delta_bic at {i+2}"
        assert qc.eta == first.eta
        assert qc.inlier_frac == first.inlier_frac
        assert qc.merge_suspect == first.merge_suspect
        assert qc.flat_contact_frac == first.flat_contact_frac


# ---------------------------------------------------------------------------
# cheap / fast_preview isolation
# ---------------------------------------------------------------------------


def test_cheap_true_skips_ransac_bic_split_polar_repair_morphgac(monkeypatch):
    """fast_preview=True must not invoke heavy QC/repair/MorphGAC paths."""
    fx = fixture_clean_isolated_ring()

    hits: dict[str, int] = {
        "ransac": 0,
        "bic": 0,
        "split": 0,
        "polar": 0,
        "morphgac": 0,
    }

    import morphostack.core.slice_qc as sqc
    import morphostack.core.object_select as os_sel
    import morphostack.core.polar_dp as pdp
    import morphostack.core.seeded_vesicle as sv

    real_ransac = sqc._fit_circle_ransac
    real_bic = sqc._two_circle_delta_bic

    def mock_ransac(*args, **kwargs):
        hits["ransac"] += 1
        return real_ransac(*args, **kwargs)

    def mock_bic(*args, **kwargs):
        hits["bic"] += 1
        return real_bic(*args, **kwargs)

    def mock_split(*args, **kwargs):
        hits["split"] += 1
        return None

    def mock_polar(*args, **kwargs):
        hits["polar"] += 1
        return SeededSliceResult(None, None, (fx.seed_x, fx.seed_y), 0.0, 0.0, "polar_dp", False)

    def mock_morphgac(*args, **kwargs):
        hits["morphgac"] += 1
        return args[1] if len(args) > 1 else None

    monkeypatch.setattr(sqc, "_fit_circle_ransac", mock_ransac)
    monkeypatch.setattr(sqc, "_two_circle_delta_bic", mock_bic)
    monkeypatch.setattr(os_sel, "attempt_seeded_split", mock_split)
    monkeypatch.setattr(pdp, "segment_slice_polar_dp", mock_polar)
    monkeypatch.setattr(sv, "_refine_contour_morphgac", mock_morphgac)

    res = segment_slice_seeded(
        fx.frame,
        seed_x=fx.seed_x,
        seed_y=fx.seed_y,
        seed_radius=fx.seed_radius,
        refine=True,  # would normally allow MorphGAC; fast_preview must still skip
        fast_preview=True,
    )
    assert res.ok
    assert hits["ransac"] == 0, "RANSAC invoked under cheap/fast_preview"
    assert hits["bic"] == 0, "BIC/two-circle fitting invoked under cheap/fast_preview"
    assert hits["split"] == 0, "seeded split invoked under cheap/fast_preview"
    assert hits["polar"] == 0, "polar path invoked under cheap/fast_preview on successful threshold"
    assert hits["morphgac"] == 0, "MorphGAC invoked under cheap/fast_preview"

    # Direct cheap QC also must not call RANSAC/BIC.
    hits["ransac"] = hits["bic"] = 0
    solid = fx.target_mask
    qc = compute_slice_qc(
        solid, fx.frame, seed_x=fx.seed_x, seed_y=fx.seed_y, seed_radius=fx.seed_radius, cheap=True
    )
    assert qc.cheap is True
    assert qc.merge_suspect is False
    assert hits["ransac"] == 0
    assert hits["bic"] == 0


# ---------------------------------------------------------------------------
# Retain no-reacquisition-after-blank-gap (import existing coverage)
# ---------------------------------------------------------------------------


def test_no_reacquisition_after_blank_gap_still_enforced():
    """Retain fail-closed gap identity: do not claim neighbour at old seed after blank."""
    from morphostack.core.seeded_vesicle import track_seeded_vesicle_stack

    h, w, n = 100, 100, 7
    stack = np.zeros((n, h, w), dtype=np.float64)
    for z, cx in enumerate((30.0, 32.0, 34.0)):
        stack[z] = _ring(h, w, cx, 50, 10, 14)
    for z in range(4, n):
        stack[z] = _ring(h, w, 30.0, 50, 10, 14)

    results = track_seeded_vesicle_stack(
        stack, seed_x=30, seed_y=50, seed_frame=0, seed_radius=14
    )
    assert results[0].ok and results[2].ok
    assert not results[3].ok
    assert all(
        not result.ok or abs(result.center_xy[0] - 30.0) > 5.0 for result in results[4:]
    ), "tracker reacquired the neighbor after the target gap"
