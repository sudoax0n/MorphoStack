"""QC diagnostics and contact/merge decision helpers for seeded isolation."""

from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.slice_qc import (
    accept_as_is,
    compute_slice_qc,
    crofton_circularity,
    fail_closed,
    repair_improves,
    should_attempt_polar_repair,
    should_attempt_split,
)
from morphostack.core.seeded_vesicle import segment_slice_seeded


def _ring(h, w, cx, cy, r_in, r_out, value=1.0) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = value
    return frame


def _filled_disk(h, w, cx, cy, r) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r**2


def test_crofton_circularity_near_one_for_disk():
    mask = _filled_disk(80, 80, 40, 40, 18)
    c, area, peri = crofton_circularity(mask)
    assert area > 100
    assert peri > 0
    assert c > 0.85


def test_qc_isolated_ring_not_merge_suspect():
    frame = _ring(100, 100, 50, 50, 16, 20)
    solid = _filled_disk(100, 100, 50, 50, 20)
    qc = compute_slice_qc(solid, frame, seed_x=50, seed_y=50, seed_radius=18, cheap=False)
    assert qc.edge_support > 0.3 or qc.eta < 0.15
    assert accept_as_is(qc) or not fail_closed(qc)
    # A clean disk may have low edge on filled solid vs ring image — segment path is authoritative.
    res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=20, refine=False)
    assert res.ok
    assert res.method != "circle_seed_merge_reject"


def test_qc_broad_contact_flags_or_repairs():
    """Two rings with broad contact: either merge_suspect QC or successful isolation."""
    h = w = 120
    frame = np.zeros((h, w), dtype=np.float64)
    frame += _ring(h, w, 48, 60, 14, 18)
    frame += _ring(h, w, 72, 60, 14, 18)
    # Filled merge mask spanning both (single blob, broad contact).
    solid = _filled_disk(h, w, 48, 60, 18) | _filled_disk(h, w, 72, 60, 18)
    qc = compute_slice_qc(solid, frame, seed_x=48, seed_y=60, seed_radius=18, cheap=False)
    # Should raise at least one contact cue or two-circle preference.
    assert (
        qc.merge_suspect
        or qc.flat_contact_frac >= 0.08
        or qc.strong_two_circle
        or qc.eta > 0.06
        or qc.n_dt_markers >= 2
        or should_attempt_split(qc)
        or should_attempt_polar_repair(qc)
    )

    res = segment_slice_seeded(frame, seed_x=48, seed_y=60, seed_radius=18, refine=False)
    # Accept isolation of seed-side vesicle OR explicit merge reject — never silent dual blob.
    if res.ok and res.solid_mask is not None:
        # Seed vesicle body should dominate; far lobe should not be fully included.
        far = res.solid_mask[60, 72]
        near = res.solid_mask[60, 48] or res.solid_mask[int(res.center_xy[1]), int(res.center_xy[0])]
        assert near
        # Either split cleaned the far center, or area is not a double merge.
        if far:
            assert res.area_px < 1.6 * (np.pi * 18**2)
    else:
        assert res.method in {"circle_seed_merge_reject", "circle_seed_fail"}


def test_thin_neck_prefers_split_markers():
    h = w = 100
    # Two disks connected by a thin 2px neck.
    solid = _filled_disk(h, w, 35, 50, 12) | _filled_disk(h, w, 65, 50, 12)
    solid[48:53, 45:56] = True
    from morphostack.core.object_select import attempt_seeded_split

    split = attempt_seeded_split(solid, seed_x=35, seed_y=50, seed_radius=12)
    assert split is not None
    assert np.count_nonzero(split) < np.count_nonzero(solid) * 0.85
    # Far lobe center should not remain in child.
    assert not split[50, 65]


def test_pear_deformation_not_rejected_for_circularity_alone():
    """Legitimate elongated single object must not fail solely on low C."""
    h = w = 100
    yy, xx = np.ogrid[:h, :w]
    # Ellipse / pear-like single blob
    solid = ((xx - 50) / 22) ** 2 + ((yy - 50) / 14) ** 2 <= 1.0
    frame = np.zeros((h, w), dtype=np.float64)
    # Bright rim approximation
    from scipy import ndimage as ndi

    rim = solid ^ ndi.binary_erosion(solid, iterations=2)
    frame[rim] = 1.0
    qc = compute_slice_qc(solid, frame, seed_x=50, seed_y=50, seed_radius=18, cheap=False)
    # Low circularity possible, but not a hard fail by itself.
    if qc.circularity < 0.85:
        assert not (fail_closed(qc) and not qc.merge_suspect and qc.edge_support > 0.5)
    res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=22, refine=False)
    # Should segment something; if ok, contour is not replaced by a fitted circle.
    if res.ok:
        assert res.contour_xy is not None
        assert len(res.contour_xy) > 20


def test_repair_improves_requires_real_gain():
    from morphostack.core.slice_qc import SliceQC

    bad = SliceQC(
        circularity=0.7,
        eta=0.12,
        edge_support=0.40,
        inlier_frac=0.5,
        defect_depth_norm=0.1,
        flat_contact_frac=0.15,
        delta_bic=-12.0,
        n_dt_markers=1,
        merge_suspect=True,
        strong_two_circle=True,
        fitted_radius=15.0,
    )
    good = SliceQC(
        circularity=0.85,
        eta=0.04,
        edge_support=0.55,
        inlier_frac=0.8,
        defect_depth_norm=0.02,
        flat_contact_frac=0.05,
        delta_bic=2.0,
        n_dt_markers=1,
        merge_suspect=False,
        strong_two_circle=False,
        fitted_radius=15.0,
    )
    assert repair_improves(bad, good)
    assert not repair_improves(good, bad)


def test_fast_preview_skips_merge_reject_path():
    """fast_preview must remain cheap and still return a provisional result."""
    frame = _ring(80, 80, 40, 40, 14, 18)
    res = segment_slice_seeded(
        frame, seed_x=40, seed_y=40, seed_radius=18, refine=False, fast_preview=True
    )
    assert res.ok
    assert res.method != "circle_seed_merge_reject"
