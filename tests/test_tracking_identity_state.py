"""Canonical tracking identity, cache key, and job-state contract (packet 01)."""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace

import numpy as np
import pytest

from morphostack.core.pipeline import RectROI, ZRange
from morphostack.core.seeded_vesicle import (
    EXACT_TRACKING_ALGORITHM_VERSION,
    EXACT_TRACKING_MODE,
    SeededSliceResult,
    track_seeded_vesicle_stack,
)
from morphostack.core.stack_cache import (
    TrackingCacheKey,
    TrackingJobState,
    TrackingResultCache,
    make_tracking_cache_key,
    tracking_key_revision,
)


def _base_key_kwargs(**overrides):
    base = dict(
        stack_identity="path:/data/stack.tif|m1|s100",
        seed_x=32.0,
        seed_y=40.0,
        seed_frame=3,
        seed_radius=14.0,
        gray_shape=(20, 128, 128),
    )
    base.update(overrides)
    return base


def test_exact_tracking_constants_are_stable_nonempty():
    assert isinstance(EXACT_TRACKING_ALGORITHM_VERSION, str)
    assert EXACT_TRACKING_ALGORITHM_VERSION.strip()
    assert EXACT_TRACKING_MODE == "seeded_exact"


def test_make_tracking_cache_key_fills_canonical_identity_defaults():
    key = make_tracking_cache_key(**_base_key_kwargs())
    assert key.profile == "vesicle"
    assert key.tracking_mode == EXACT_TRACKING_MODE
    assert key.algorithm_version == EXACT_TRACKING_ALGORITHM_VERSION
    assert isinstance(key, TrackingCacheKey)


def test_tracking_cache_key_equality_and_hash_stability():
    a = make_tracking_cache_key(**_base_key_kwargs())
    b = make_tracking_cache_key(**_base_key_kwargs())
    assert a == b
    assert hash(a) == hash(b)
    assert tracking_key_revision(a) == tracking_key_revision(b)
    assert len(tracking_key_revision(a)) == 16

    # Set membership must treat equal keys as one entry.
    assert len({a, b}) == 1


def test_profile_and_algorithm_version_force_cache_miss():
    cache = TrackingResultCache(maxsize=8)
    base = make_tracking_cache_key(**_base_key_kwargs())
    dummy = [
        SeededSliceResult(None, None, (32.0, 40.0), 1.0, 1.0, "circle_seed", True)
    ]
    cache.put(base, dummy)
    assert cache.get(base) is not None

    by_profile = make_tracking_cache_key(**_base_key_kwargs(profile="rbc"))
    by_version = make_tracking_cache_key(
        **_base_key_kwargs(algorithm_version="not-" + EXACT_TRACKING_ALGORITHM_VERSION)
    )
    by_mode = make_tracking_cache_key(**_base_key_kwargs(tracking_mode="other_mode"))
    assert by_profile != base
    assert by_version != base
    assert by_mode != base
    assert cache.get(by_profile) is None
    assert cache.get(by_version) is None
    assert cache.get(by_mode) is None


def test_stack_revision_seed_roi_z_still_force_miss():
    base = make_tracking_cache_key(**_base_key_kwargs())
    cases = [
        make_tracking_cache_key(**_base_key_kwargs(stack_identity="path:/other.tif|m2|s200")),
        make_tracking_cache_key(**_base_key_kwargs(seed_x=32.5)),
        make_tracking_cache_key(**_base_key_kwargs(seed_y=41.0)),
        make_tracking_cache_key(**_base_key_kwargs(seed_frame=4)),
        make_tracking_cache_key(**_base_key_kwargs(seed_radius=15.0)),
        make_tracking_cache_key(
            **_base_key_kwargs(roi=RectROI(xmin=0, xmax=64, ymin=0, ymax=64))
        ),
        make_tracking_cache_key(**_base_key_kwargs(z_range=ZRange(zmin=0, zmax=10))),
        make_tracking_cache_key(**_base_key_kwargs(gray_shape=(20, 64, 64))),
    ]
    for other in cases:
        assert other != base
        assert tracking_key_revision(other) != tracking_key_revision(base)


def test_requested_threshold_is_not_part_of_seeded_exact_key():
    """UI global threshold must not appear on the exact adaptive tracking key."""
    key = make_tracking_cache_key(**_base_key_kwargs())
    field_names = set(key.__dataclass_fields__)
    assert "threshold" not in field_names
    assert "requested_threshold" not in field_names
    # Factory has no threshold parameter — only scientific identity.
    assert "threshold" not in make_tracking_cache_key.__code__.co_varnames


def test_old_unversioned_shape_cannot_hit_versioned_key():
    """Legacy spatial-only identity is not equal to the versioned key object."""
    versioned = make_tracking_cache_key(**_base_key_kwargs())
    # Simulate a pre-version cache entry that only had spatial fields by building
    # a distinct key with empty algorithm version forced via replace.
    legacy_like = replace(versioned, algorithm_version="0-legacy")
    cache = TrackingResultCache(maxsize=4)
    dummy = [
        SeededSliceResult(None, None, (32.0, 40.0), 1.0, 1.0, "circle_seed", True)
    ]
    cache.put(legacy_like, dummy)
    assert cache.get(versioned) is None
    assert cache.get(legacy_like) is not None


def test_tracking_job_state_json_roundtrip_and_no_nonfinite():
    state = TrackingJobState(
        job_id="job-1",
        tracking_key_revision="abc123def4567890",
        state="partial",
        requested_target_z=12,
        reached_low_z=3,
        reached_high_z=10,
        available_exact_frames=(10, 3, 7, 3),
        started_at="2026-07-11T12:00:00Z",
        updated_at="2026-07-11T12:00:01Z",
        error_code=None,
        message=None,
    )
    assert state.available_exact_frames == (3, 7, 10)
    payload = state.to_json_dict()
    raw = json.dumps(payload)
    loaded = json.loads(raw)
    assert math.isfinite(float(loaded["requested_target_z"]))
    restored = TrackingJobState.from_json_dict(loaded)
    assert restored == state
    assert restored.to_json_dict() == payload

    failed = TrackingJobState(
        job_id="job-2",
        tracking_key_revision="abc123def4567890",
        state="failed",
        requested_target_z=None,
        reached_low_z=None,
        reached_high_z=None,
        available_exact_frames=(),
        started_at="2026-07-11T12:00:00Z",
        updated_at="2026-07-11T12:00:02Z",
        error_code="track_error",
        message="example",
    )
    assert failed.to_json_dict()["state"] == "failed"
    assert "NaN" not in json.dumps(failed.to_json_dict())
    assert "Infinity" not in json.dumps(failed.to_json_dict())


def test_tracking_job_state_rejects_invalid_state():
    with pytest.raises(ValueError, match="invalid tracking job state"):
        TrackingJobState(
            job_id="x",
            tracking_key_revision="y",
            state="done",  # type: ignore[arg-type]
            requested_target_z=0,
            reached_low_z=0,
            reached_high_z=0,
            available_exact_frames=(),
            started_at=None,
            updated_at=None,
        )


def test_key_construction_microbenchmark_under_1ms_median():
    kwargs = _base_key_kwargs(
        profile="vesicle",
        roi=RectROI(xmin=0, xmax=80, ymin=0, ymax=80),
        z_range=ZRange(zmin=0, zmax=15),
    )
    # Warm
    for _ in range(50):
        make_tracking_cache_key(**kwargs)
        tracking_key_revision(make_tracking_cache_key(**kwargs))

    times = []
    for _ in range(500):
        t0 = time.perf_counter()
        key = make_tracking_cache_key(**kwargs)
        tracking_key_revision(key)
        times.append(time.perf_counter() - t0)
    times.sort()
    median_ms = times[len(times) // 2] * 1000.0
    assert median_ms < 1.0, f"key construction median {median_ms:.4f} ms exceeds 1 ms"


def test_warm_result_lookup_overhead_under_budget():
    cache = TrackingResultCache(maxsize=8)
    key = make_tracking_cache_key(**_base_key_kwargs())
    dummy = [
        SeededSliceResult(None, None, (32.0, 40.0), 1.0, 1.0, "circle_seed", True)
    ]
    cache.put(key, dummy)
    for _ in range(100):
        cache.get(key)

    times = []
    for _ in range(2000):
        t0 = time.perf_counter()
        hit = cache.get(key)
        times.append(time.perf_counter() - t0)
        assert hit is not None
    times.sort()
    median_ms = times[len(times) // 2] * 1000.0
    # Report-07 warm hit was microsecond-class; allow generous engineering headroom.
    assert median_ms < 0.5, f"warm lookup median {median_ms:.4f} ms too slow"


def _ring_stack(n: int = 8, h: int = 64, w: int = 64) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    stack = np.zeros((n, h, w), dtype=np.float64)
    for z in range(n):
        cx = 32.0 + 0.3 * z
        cy = 32.0
        r_out, r_in = 12.0, 8.0
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        ring = (dist <= r_out) & (dist >= r_in)
        stack[z][ring] = 180.0
        stack[z] += 5.0
    return stack


def test_scientific_parity_track_outputs_unchanged_by_identity_layer():
    """Identity/state layer does not rewrite exact results (cache fidelity).

    Packet 01 does not modify segment/association/QC code paths. Gate is that
    committed exact results survive put/get under the versioned key without
    geometry mutation. (Independent dual runs may already differ slightly due
    to pre-existing MorphGAC/RANSAC noise; that is out of scope here.)
    """
    stack = _ring_stack()
    tracked = track_seeded_vesicle_stack(
        stack,
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        target_frame=5,
    )
    assert any(r.ok for r in tracked)

    key = make_tracking_cache_key(
        stack_identity="session:parity",
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        gray_shape=stack.shape,
        profile="vesicle",
    )
    assert key.algorithm_version == EXACT_TRACKING_ALGORITHM_VERSION
    assert key.tracking_mode == EXACT_TRACKING_MODE

    cache = TrackingResultCache(maxsize=4)
    cache.put(key, tracked)
    cached = cache.get(key)
    assert cached is not None
    for ra, rc in zip(tracked, cached):
        assert ra.ok == rc.ok
        assert ra.method == rc.method
        assert ra.center_xy == rc.center_xy
        assert ra.area_px == rc.area_px
        assert ra.perimeter_px == rc.perimeter_px
        assert ra.effective_threshold == rc.effective_threshold
        if ra.contour_xy is None:
            assert rc.contour_xy is None
        else:
            np.testing.assert_array_equal(ra.contour_xy, rc.contour_xy)
        if ra.solid_mask is None:
            assert rc.solid_mask is None
        else:
            np.testing.assert_array_equal(ra.solid_mask, rc.solid_mask)

    # Neighbor ring: same store fidelity under a distinct key.
    touch = stack.copy()
    yy, xx = np.mgrid[0 : touch.shape[1], 0 : touch.shape[2]]
    for z in range(touch.shape[0]):
        dist2 = np.sqrt((xx - 50.0) ** 2 + (yy - 32.0) ** 2)
        touch[z][(dist2 <= 10.0) & (dist2 >= 7.0)] = 180.0
    touch_tracked = track_seeded_vesicle_stack(
        touch,
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        target_frame=5,
    )
    touch_key = make_tracking_cache_key(
        stack_identity="session:touch",
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        gray_shape=touch.shape,
        profile="vesicle",
    )
    cache.put(touch_key, touch_tracked)
    assert cache.get(key) is not None  # isolated entry still present
    touch_cached = cache.get(touch_key)
    assert touch_cached is not None
    for ra, rc in zip(touch_tracked, touch_cached):
        assert ra.ok == rc.ok
        assert ra.method == rc.method
        assert ra.center_xy == rc.center_xy
