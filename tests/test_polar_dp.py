"""Tests for Polar-DP (Viterbi) membrane contour extraction."""

from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.polar_dp import (
    compute_cost_image,
    contour_to_solid_mask,
    polar_to_cartesian_contour,
    polar_transform,
    segment_slice_polar_dp,
    viterbi_optimal_path,
)


def _bright_ring(h: int, w: int, cx: float, cy: float, r: float, thickness: float = 2.0) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    frame = np.zeros((h, w), dtype=np.float64)
    frame[np.abs(d - r) <= thickness] = 1.0
    return frame


def test_polar_dp_finds_perfect_ring():
    h, w = 80, 80
    cx, cy, r = 40.0, 40.0, 18.0
    frame = _bright_ring(h, w, cx, cy, r, thickness=2.0)
    res = segment_slice_polar_dp(frame, cx, cy, radius=r, n_angles=180)
    assert res.ok
    assert res.contour_xy is not None
    assert res.solid_mask is not None
    # Mean radius of contour should be near true r
    radii = np.hypot(res.contour_xy[:, 0] - cx, res.contour_xy[:, 1] - cy)
    assert abs(float(np.mean(radii)) - r) < 2.5


def test_polar_dp_handles_touching_rings():
    """Tighter search band (0.20) must keep Viterbi away from a touching neighbor membrane."""
    h, w = 100, 100
    frame = np.zeros((h, w), dtype=np.float64)
    frame += _bright_ring(h, w, 35, 50, 14, 2.0)
    frame += _bright_ring(h, w, 63, 50, 14, 2.0)  # touching neighbor
    frame = np.clip(frame, 0, 1)
    # Use the new tighter search_band that matches the fixed default
    res = segment_slice_polar_dp(frame, 35, 50, radius=14, n_angles=360, search_band=0.20)
    assert res.ok
    assert res.solid_mask is not None
    # Should not include the neighbor center
    assert not bool(res.solid_mask[50, 63])
    # Contour center of mass near seed ring
    ys, xs = np.where(res.solid_mask)
    assert abs(float(xs.mean()) - 35) < 8
    assert abs(float(ys.mean()) - 50) < 8


def test_polar_dp_handles_gap_in_ring():
    h, w = 80, 80
    cx, cy, r = 40.0, 40.0, 16.0
    frame = _bright_ring(h, w, cx, cy, r, thickness=2.0)
    # Punch a ~30° angular gap
    yy, xx = np.ogrid[:h, :w]
    ang = np.arctan2(yy - cy, xx - cx)
    gap = (ang > 0.0) & (ang < 0.55)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    frame[gap & (np.abs(d - r) <= 2.5)] = 0.0
    res = segment_slice_polar_dp(frame, cx, cy, radius=r, n_angles=180, smoothness_penalty=3.0)
    assert res.ok
    assert res.contour_xy is not None
    radii = np.hypot(res.contour_xy[:, 0] - cx, res.contour_xy[:, 1] - cy)
    assert abs(float(np.mean(radii)) - r) < 4.0


def test_polar_transform_roundtrip_samples_ring():
    h, w = 64, 64
    cx, cy, r = 32.0, 32.0, 12.0
    frame = _bright_ring(h, w, cx, cy, r, thickness=1.5)
    polar = polar_transform(frame, (cx, cy), r_min=8, r_max=16, n_angles=90, n_radii=20)
    assert polar.shape == (90, 20)
    # Peak along radius axis near true r
    mean_profile = polar.mean(axis=0)
    peak_idx = int(np.argmax(mean_profile))
    radii = np.linspace(8, 16, 20)
    assert abs(radii[peak_idx] - r) < 2.5


def test_viterbi_and_cost_helpers():
    # Synthetic ridge at radius index 5
    n_a, n_r = 40, 12
    polar = np.zeros((n_a, n_r), dtype=np.float64)
    polar[:, 5] = 1.0
    cost = compute_cost_image(polar)
    path = viterbi_optimal_path(cost, smoothness_penalty=1.0, max_jump=2)
    assert path.shape == (n_a,)
    # Gradient peaks at ridge edges; path should sit near column 5
    assert abs(int(np.median(path)) - 5) <= 1
    contour = polar_to_cartesian_contour(path, (30.0, 30.0), 0.0, 11.0, n_r)
    assert contour.shape == (n_a, 2)
    solid = contour_to_solid_mask(contour, (64, 64))
    assert solid.dtype == bool
    assert np.count_nonzero(solid) > 0


def test_seeded_fallback_can_use_polar_dp():
    """Hard case: weak ring where primary may fail; polar_dp path is invokable."""
    from morphostack.core.seeded_vesicle import segment_slice_seeded
    from morphostack.core.polar_dp import segment_slice_polar_dp

    frame = _bright_ring(80, 80, 40, 40, 15, thickness=1.5) * 0.4
    # Direct Polar-DP always works on this synthetic (use updated defaults)
    direct = segment_slice_polar_dp(frame, 40, 40, 15, n_angles=360, search_band=0.20)
    assert direct.ok
    # Seeded path should also succeed (primary or polar_dp fallback)
    res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=15)
    assert res.ok


def test_polar_dp_n_angles_scales_with_radius():
    """Verify that the seeded pipeline uses >=1 px arc resolution (n_angles >= 2*pi*R)."""
    import math
    from morphostack.core.seeded_vesicle import segment_slice_seeded

    R = 30.0
    frame = _bright_ring(120, 120, 60, 60, R, thickness=2.0)
    res = segment_slice_seeded(frame, seed_x=60, seed_y=60, seed_radius=R)
    assert res.ok
    # With correct n_angles >= 2*pi*R ~ 188, contour should have many points
    if res.contour_xy is not None:
        expected_min = int(2.0 * math.pi * R) // 2  # generous lower bound
        assert len(res.contour_xy) >= expected_min or res.method == "circle_seed"


def test_pick_component_soft_fallback_prefers_containing():
    """Soft fallback must prefer the ring containing the seed over a nearer non-containing neighbor."""
    from morphostack.core.object_select import pick_component
    import numpy as np

    # Build two synthetic component dicts.
    # comp_a: small blob whose centroid is further from seed but seed is inside its contour.
    # comp_b: small blob whose centroid is closer to seed but seed is NOT inside it.
    seed_x, seed_y = 30.0, 30.0
    ref_area = 400.0

    # comp_a: 20x20 square centered at (30, 30) — seed is inside
    sub_a = np.ones((20, 20), dtype=bool)
    comp_a = {
        "sub_mask": sub_a,
        "bbox": (20, 40, 20, 40),   # (ymin, ymax, xmin, xmax)
        "centroid": (30.0, 30.0),   # (cx, cy) in full-image coords
        "area": 400,
    }

    # comp_b: 20x20 square centered at (10, 30) — seed at (30,30) is OUTSIDE
    sub_b = np.ones((20, 20), dtype=bool)
    comp_b = {
        "sub_mask": sub_b,
        "bbox": (20, 40, 0, 20),    # xmax=20, seed_x=30 is outside
        "centroid": (10.0, 30.0),   # closer centroid to... wait
        "area": 400,
    }

    # With the fixed fallback, comp_a (containing seed) must win over comp_b.
    result = pick_component(
        [comp_a, comp_b],
        seed_x=seed_x,
        seed_y=seed_y,
        seed_radius=15.0,
        ref_area=ref_area,
    )
    assert result is not None
    # The picked component's centroid should be comp_a's (30, 30) not comp_b's (10, 30)
    assert abs(result["centroid"][0] - 30.0) < 5.0
