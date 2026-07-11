from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.slice_qc import compute_slice_qc, _fit_circle_ransac, _two_circle_delta_bic
from morphostack.core.seeded_vesicle import segment_slice_seeded, SeededSliceResult
import morphostack.core.seeded_vesicle as sv


def _ring(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float, value: float = 1.0) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = value
    return frame


def _filled_disk(h: int, w: int, cx: float, cy: float, r: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r**2


def test_clean_circular_ring_accepted_and_no_merge_suspect():
    frame = _ring(100, 100, 50, 50, 12, 16)
    res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=16, refine=False)
    assert res.ok
    assert not res.merge_suspect
    assert res.qc is not None
    assert not res.qc.merge_suspect


def test_pear_deformation_not_hard_rejected_for_circularity_alone():
    h = w = 100
    yy, xx = np.ogrid[:h, :w]
    # Pear/ellipse-like single vesicle mask
    solid = ((xx - 50) / 22) ** 2 + ((yy - 50) / 14) ** 2 <= 1.0
    frame = np.zeros((h, w), dtype=np.float64)
    from scipy import ndimage as ndi
    rim = solid ^ ndi.binary_erosion(solid, iterations=2)
    frame[rim] = 1.0

    res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=22, refine=False)
    assert res.ok
    # Legitimate non-circular vesicle must be accepted (ok=True), even if circularity is lower.
    assert res.contour_xy is not None
    assert len(res.contour_xy) > 12


def test_tangent_and_overlapping_neighbors_isolation_or_reject():
    """Overlap/tangent neighbors must either be isolated correctly or explicitly rejected, never silent merge."""
    h = w = 100
    # Seeded vesicle at (40, 50), neighbor at (66, 50) - they overlap/touch
    frame = _ring(h, w, 40, 50, 10, 14) + _ring(h, w, 66, 50, 10, 14)
    frame = np.clip(frame, 0.0, 1.0)

    res = segment_slice_seeded(frame, seed_x=40, seed_y=50, seed_radius=14, refine=False)
    
    if res.ok:
        assert res.solid_mask is not None
        # Verify neighbor center is NOT inside our mask (proper isolation)
        assert not res.solid_mask[50, 66]
        # Bounded area
        assert res.area_px < np.pi * 14**2 * 1.5
    else:
        # Explicit merge reject is also an acceptable outcome
        assert res.method in {"circle_seed_merge_reject", "circle_seed_fail"}


def test_weak_broken_ring_no_neighbour_steal():
    """A weak/broken ring must not swallow or steal a nearby strong neighbor."""
    h = w = 100
    # Broken target ring at (40, 50): remove a quadrant
    target = _ring(h, w, 40, 50, 10, 14)
    yy, xx = np.ogrid[:h, :w]
    target[(xx >= 40) & (yy >= 50)] = 0.0
    
    # Bright neighbor at (70, 50)
    neighbor = _ring(h, w, 70, 50, 10, 14)
    frame = np.clip(target + neighbor, 0.0, 1.0)

    res = segment_slice_seeded(frame, seed_x=40, seed_y=50, seed_radius=14, refine=False)
    
    if res.ok:
        assert res.solid_mask is not None
        # Check that the neighbor's center and body is not stolen
        assert not res.solid_mask[50, 70]
        assert res.area_px < np.pi * 14**2 * 1.5
    else:
        assert res.method in {"circle_seed_merge_reject", "circle_seed_fail"}


def test_post_refinement_partial_neighbour_lobe_rejected():
    """If MorphGAC refinement pulls in a neighbor lobe, post-refinement full QC must reject it."""
    # Create a frame where refinement will cause a leak/merge
    h = w = 100
    # Target ring at (40, 50), neighbor ring very close at (64, 50)
    frame = _ring(h, w, 40, 50, 10, 14) + _ring(h, w, 64, 50, 10, 14)
    frame = np.clip(frame, 0.0, 1.0)

    # If we segment with refine=True, MorphGAC should refine. If it leaks to neighbor,
    # the post-refinement QC should fail_closed and return ok=False with merge_reject.
    res = segment_slice_seeded(frame, seed_x=40, seed_y=50, seed_radius=14, refine=True)
    if res.ok:
        # If it passed, it must have isolated the neighbor center successfully
        assert res.solid_mask is not None
        assert not res.solid_mask[50, 64]
    else:
        assert res.method == "circle_seed_merge_reject"


def test_repeated_20_runs_identical_qc_and_metrics():
    """RANSAC/BIC fitting must be fully reproducible across multiple runs."""
    h = w = 120
    frame = _ring(h, w, 48, 60, 14, 18) + _ring(h, w, 72, 60, 14, 18)
    frame = np.clip(frame, 0.0, 1.0)
    solid = _filled_disk(h, w, 48, 60, 18) | _filled_disk(h, w, 72, 60, 18)

    qcs = []
    for _ in range(20):
        qc = compute_slice_qc(solid, frame, seed_x=48, seed_y=60, seed_radius=18, cheap=False)
        qcs.append(qc)

    first_qc = qcs[0]
    for idx, qc in enumerate(qcs[1:]):
        assert qc.delta_bic == first_qc.delta_bic, f"delta_bic mismatch at run {idx+1}"
        assert qc.eta == first_qc.eta, f"eta mismatch at run {idx+1}"
        assert qc.inlier_frac == first_qc.inlier_frac, f"inlier_frac mismatch at run {idx+1}"
        assert qc.merge_suspect == first_qc.merge_suspect, f"merge_suspect mismatch at run {idx+1}"


def test_cheap_true_bypasses_ransac_and_repair_invocations(monkeypatch):
    """fast_preview=True (cheap=True) must not call _fit_circle_ransac or polar/split repairs."""
    frame = _ring(80, 80, 40, 40, 14, 18)
    
    ransac_called = False
    repair_called = False

    def mock_ransac(*args, **kwargs):
        nonlocal ransac_called
        ransac_called = True
        return (40.0, 40.0, 16.0), np.ones(len(args[0]), dtype=bool), 0.1

    def mock_split(*args, **kwargs):
        nonlocal repair_called
        repair_called = True
        return args[0]

    def mock_polar(*args, **kwargs):
        nonlocal repair_called
        repair_called = True
        return SeededSliceResult(None, None, (40.0, 40.0), 0.0, 0.0, "polar_dp", False)

    import morphostack.core.slice_qc as sqc
    import morphostack.core.object_select as os_sel
    import morphostack.core.polar_dp as pdp

    monkeypatch.setattr(sqc, "_fit_circle_ransac", mock_ransac)
    monkeypatch.setattr(os_sel, "attempt_seeded_split", mock_split)
    monkeypatch.setattr(pdp, "segment_slice_polar_dp", mock_polar)

    # Run fast preview
    res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=18, refine=False, fast_preview=True)
    
    assert res.ok
    assert not ransac_called, "RANSAC was called during fast_preview=True!"
    assert not repair_called, "Repair split/polar DP was called during fast_preview=True!"
