"""Packet 11 — request-scoped competitive tracking opt-in."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from morphostack.core.seeded_vesicle import (
    SEEDED_EXACT_MODE_COMPETITIVE,
    SEEDED_EXACT_MODE_LEGACY,
    competitive_from_tracking_mode,
    exact_tracking_mode_token,
    is_competitive_isolation_enabled,
    segment_slice_seeded,
    set_competitive_isolation_enabled,
    track_seeded_vesicle_stack,
)
from morphostack.core.stack_cache import (
    TrackingResultCache,
    make_tracking_cache_key,
    tracking_key_revision,
)
from morphostack.api.tracking_jobs import TrackingJobService


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


def test_mode_tokens_distinct():
    assert exact_tracking_mode_token(False) == SEEDED_EXACT_MODE_LEGACY
    assert exact_tracking_mode_token(True) == SEEDED_EXACT_MODE_COMPETITIVE
    assert competitive_from_tracking_mode(SEEDED_EXACT_MODE_COMPETITIVE) is True
    assert competitive_from_tracking_mode(SEEDED_EXACT_MODE_LEGACY) is False
    assert competitive_from_tracking_mode("seeded_exact") is False


def test_cache_keys_separate_variants():
    shape = (5, 64, 64)
    base = dict(
        stack_identity="path:test",
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        gray_shape=shape,
        profile="vesicle",
    )
    legacy = make_tracking_cache_key(**base, tracking_mode=SEEDED_EXACT_MODE_LEGACY)
    comp = make_tracking_cache_key(**base, tracking_mode=SEEDED_EXACT_MODE_COMPETITIVE)
    assert legacy != comp
    assert tracking_key_revision(legacy) != tracking_key_revision(comp)
    assert legacy.tracking_mode == SEEDED_EXACT_MODE_LEGACY
    assert comp.tracking_mode == SEEDED_EXACT_MODE_COMPETITIVE


def test_request_scoped_arg_ignores_process_global():
    """Explicit competitive_isolation=False must not use process-global True."""
    frame = _ring(80, 80, 40, 40, 14, 18)
    set_competitive_isolation_enabled(True)
    try:
        res = segment_slice_seeded(
            frame,
            seed_x=40,
            seed_y=40,
            seed_radius=18,
            refine=True,
            competitive_isolation=False,
        )
        assert res.ok
        assert res.method != "competitive_polar_rw"
        assert not str(res.method).startswith("competitive")
    finally:
        set_competitive_isolation_enabled(False)


def test_request_scoped_true_without_global():
    frame = _ring(80, 80, 40, 40, 14, 18)
    assert is_competitive_isolation_enabled() is False
    res = segment_slice_seeded(
        frame,
        seed_x=40,
        seed_y=40,
        seed_radius=18,
        refine=True,
        competitive_isolation=True,
    )
    assert res.ok, res.method
    assert res.method == "competitive_polar_rw" or res.method.startswith("competitive")


def test_concurrent_jobs_opposite_variants_isolated():
    """Two jobs same stack/seed different modes: separate keys; each keeps its mode."""
    n, h, w = 4, 48, 48
    stack = np.stack([_ring(h, w, 24, 24, 8, 12) for _ in range(n)], axis=0)
    cache = TrackingResultCache(maxsize=8)
    svc = TrackingJobService(result_cache=cache, max_active_jobs=2)

    key_legacy = make_tracking_cache_key(
        stack_identity="session:t11",
        seed_x=24.0,
        seed_y=24.0,
        seed_frame=0,
        seed_radius=12.0,
        gray_shape=stack.shape,
        profile="vesicle",
        tracking_mode=SEEDED_EXACT_MODE_LEGACY,
    )
    key_comp = make_tracking_cache_key(
        stack_identity="session:t11",
        seed_x=24.0,
        seed_y=24.0,
        seed_frame=0,
        seed_radius=12.0,
        gray_shape=stack.shape,
        profile="vesicle",
        tracking_mode=SEEDED_EXACT_MODE_COMPETITIVE,
    )
    assert key_legacy != key_comp

    snap_l = svc.start(
        key=key_legacy,
        stack=stack,
        seed_x=24.0,
        seed_y=24.0,
        seed_frame=0,
        seed_radius=12.0,
        target_z=3,
    )
    snap_c = svc.start(
        key=key_comp,
        stack=stack,
        seed_x=24.0,
        seed_y=24.0,
        seed_frame=0,
        seed_radius=12.0,
        target_z=3,
    )
    assert snap_l.job_id != snap_c.job_id
    assert snap_l.tracking_key_revision != snap_c.tracking_key_revision

    svc.wait(snap_l.job_id, timeout=60.0)
    svc.wait(snap_c.job_id, timeout=60.0)

    res_l = cache.get(key_legacy)
    res_c = cache.get(key_comp)
    assert res_l is not None and res_c is not None
    # Methods on competitive path should be competitive when accepted.
    methods_c = [r.method for r in res_c if r is not None and r.ok]
    methods_l = [r.method for r in res_l if r is not None and r.ok]
    if methods_c:
        assert any("competitive" in m or m.startswith("circle_seed") for m in methods_c)
    # Legacy must not be competitive_polar_rw (global flag remains off).
    assert all("competitive_polar" not in m for m in methods_l)
    svc.shutdown(timeout=5.0)


def test_cache_hit_does_not_cross_variant():
    n, h, w = 3, 40, 40
    stack = np.stack([_ring(h, w, 20, 20, 7, 11) for _ in range(n)], axis=0)
    cache = TrackingResultCache()
    key_l = make_tracking_cache_key(
        stack_identity="path:cross",
        seed_x=20.0,
        seed_y=20.0,
        seed_frame=0,
        seed_radius=11.0,
        gray_shape=stack.shape,
        tracking_mode=SEEDED_EXACT_MODE_LEGACY,
    )
    key_c = make_tracking_cache_key(
        stack_identity="path:cross",
        seed_x=20.0,
        seed_y=20.0,
        seed_frame=0,
        seed_radius=11.0,
        gray_shape=stack.shape,
        tracking_mode=SEEDED_EXACT_MODE_COMPETITIVE,
    )
    tracked = track_seeded_vesicle_stack(
        stack,
        seed_x=20.0,
        seed_y=20.0,
        seed_frame=0,
        seed_radius=11.0,
        target_frame=2,
        competitive_isolation=False,
    )
    cache.merge(key_l, tracked)
    assert cache.get(key_l) is not None
    assert cache.get(key_c) is None  # competitive must not see legacy
