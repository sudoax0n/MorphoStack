"""Directional tracking cache merge — never clobber accepted / committed frames."""

from __future__ import annotations

from morphostack.core.seeded_vesicle import SeededSliceResult
from morphostack.core.stack_cache import (
    TrackingResultCache,
    make_tracking_cache_key,
    merge_tracking_frame,
)


def _ok(z_tag: float = 1.0) -> SeededSliceResult:
    return SeededSliceResult(
        None, None, (z_tag, z_tag), 10.0, 5.0, "circle_seed", True
    )


def _unreached() -> SeededSliceResult:
    return SeededSliceResult(
        None, None, (0.0, 0.0), 0.0, 0.0, "circle_seed_unreached", False
    )


def _gap() -> SeededSliceResult:
    return SeededSliceResult(
        None, None, (1.0, 1.0), 0.0, 0.0, "circle_seed_gap", False
    )


def test_merge_tracking_frame_unreached_never_clobbers_accepted():
    old = _ok(57.0)
    new = _unreached()
    kept = merge_tracking_frame(old, new)
    assert kept is old
    assert kept.ok
    assert kept.center_xy == (57.0, 57.0)


def test_merge_tracking_frame_unreached_never_clobbers_gap():
    old = _gap()
    new = _unreached()
    assert merge_tracking_frame(old, new) is old


def test_merge_tracking_frame_accepted_stable_when_both_ok():
    old = _ok(1.0)
    new = _ok(99.0)
    assert merge_tracking_frame(old, new) is old


def test_merge_tracking_frame_new_accepted_replaces_gap():
    old = _gap()
    new = _ok(2.0)
    assert merge_tracking_frame(old, new) is new


def test_cache_merge_preserves_opposite_side_after_unidirectional_put_materialization():
    """Scout 01 defect: reverse walk materializes high-Z as unreached; merge must retain."""
    key = make_tracking_cache_key(
        stack_identity="test:merge",
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=5,
        seed_radius=14.0,
        gray_shape=(10, 64, 64),
    )
    cache = TrackingResultCache(maxsize=4)
    # After high-side walk: seed..high accepted.
    high = [_unreached() for _ in range(10)]
    for z in (5, 6, 7):
        high[z] = _ok(float(z))
    cache.merge(key, high)

    # Reverse walk materializes only low side; high is unreached in the new list.
    low = [_unreached() for _ in range(10)]
    for z in (3, 4, 5):
        low[z] = _ok(float(z) + 0.1)
    cache.merge(key, low)

    got = cache.get(key)
    assert got is not None
    assert got[7].ok and got[7].center_xy == (7.0, 7.0)
    assert got[6].ok and got[6].center_xy == (6.0, 6.0)
    # Seed was re-accepted in reverse materialization but both ok → keep first.
    assert got[5].ok and got[5].center_xy == (5.0, 5.0)
    assert got[3].ok
    assert got[4].ok
