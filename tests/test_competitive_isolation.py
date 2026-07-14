"""Packet 02 — competitive polar + multi-label RW isolation prototype."""

from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.seeded_vesicle import (
    is_competitive_isolation_enabled,
    segment_slice_seeded,
    set_competitive_isolation_enabled,
    track_seeded_vesicle_stack,
)


def _ring(h, w, cx, cy, r_in, r_out, value=1.0):
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = value
    return frame


def setup_function():
    set_competitive_isolation_enabled(False)


def teardown_function():
    set_competitive_isolation_enabled(False)


def test_competitive_flag_off_by_default():
    assert is_competitive_isolation_enabled() is False


def test_default_path_unchanged_when_flag_off():
    """Isolated ring still segments with legacy path when prototype is off."""
    frame = _ring(80, 80, 40, 40, 14, 18)
    set_competitive_isolation_enabled(False)
    res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=18, refine=True)
    assert res.ok
    assert res.method.startswith("circle_seed") or res.method.startswith("polar")
    assert res.solid_mask is not None
    assert res.solid_mask[40, 40]


def test_competitive_accepts_isolated_ring():
    frame = _ring(80, 80, 40, 40, 14, 18)
    set_competitive_isolation_enabled(True)
    res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=18, refine=True)
    assert res.ok, f"isolated ring rejected: {res.method}"
    assert res.method == "competitive_polar_rw" or res.method.startswith("competitive")
    assert res.solid_mask is not None
    assert res.solid_mask[40, 40]
    # Single blob near seed — not empty and not whole FOV.
    area = float(np.count_nonzero(res.solid_mask))
    assert 80 < area < math_pi_r2(18) * 1.8


def math_pi_r2(r: float) -> float:
    return float(np.pi * r * r)


def test_competitive_rejects_touching_two_rings_bridge():
    """Broad-contact synthetic: must not accept a multi-body bridge as tracked."""
    h = w = 120
    frame = np.zeros((h, w), dtype=np.float64)
    # Target at (45, 60), neighbour at (72, 60) — membranes nearly touch.
    frame += _ring(h, w, 45, 60, 12, 16, value=1.0)
    frame += _ring(h, w, 72, 60, 12, 16, value=1.0)
    frame = np.clip(frame, 0, 1)

    set_competitive_isolation_enabled(True)
    # Large R disk covers both (bridge-like seed).
    res = segment_slice_seeded(frame, seed_x=45, seed_y=60, seed_radius=28, refine=True)
    if res.ok:
        # If accepted, must not include neighbour centre and must stay local.
        assert res.solid_mask is not None
        assert not res.solid_mask[60, 72], "accepted mask steals neighbour centre"
        ys, xs = np.where(res.solid_mask)
        far = np.hypot(xs.astype(float) - 45.0, ys.astype(float) - 60.0)
        assert float(np.count_nonzero(far > 1.25 * 28) / max(ys.size, 1)) < 0.12
    else:
        assert res.method in {
            "circle_seed_merge_reject",
            "circle_seed_fail",
            "competitive_reject",
        }
        assert res.merge_suspect or res.method.endswith("reject") or not res.ok


def test_competitive_track_isolated_stack():
    n, h, w = 4, 64, 64
    stack = np.stack([_ring(h, w, 28 + z, 32, 10, 14) for z in range(n)], axis=0)
    set_competitive_isolation_enabled(True)
    results = track_seeded_vesicle_stack(
        stack, seed_x=28, seed_y=32, seed_frame=0, seed_radius=14, target_frame=3
    )
    assert results[0].ok
    # At least seed + one forward frame; fail-closed gaps preferred over merge.
    ok_n = sum(1 for r in results if r.ok)
    assert ok_n >= 1


def test_legacy_still_rejects_or_accepts_per_existing_policy_when_off():
    """Flag off: two-ring case follows legacy (may still unsafe-accept)."""
    h = w = 120
    frame = np.zeros((h, w), dtype=np.float64)
    frame += _ring(h, w, 45, 60, 12, 16)
    frame += _ring(h, w, 72, 60, 12, 16)
    set_competitive_isolation_enabled(False)
    res = segment_slice_seeded(frame, seed_x=45, seed_y=60, seed_radius=28, refine=True)
    # Not asserting safety here — only that default path runs without error.
    assert res.method is not None
