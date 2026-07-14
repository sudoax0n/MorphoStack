from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.multiscale_consensus import (
    CONSENSUS_SIGMAS,
    mask_iou,
    propose_multiscale_consensus,
)
from morphostack.core.seeded_vesicle import (
    SEEDED_EXACT_MODE_LEGACY,
    SEEDED_EXACT_MODE_MULTISCALE,
    exact_tracking_mode_token,
    segment_slice_seeded,
)
from morphostack.api.tracking_jobs import TrackingJobService
from morphostack.core.stack_cache import TrackingResultCache, make_tracking_cache_key



def _ellipse(h=96, w=96, cx=48, cy=48, rx=22, ry=16, noise=0.0):
    yy, xx = np.ogrid[:h, :w]
    d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    image = np.zeros((h, w), dtype=float)
    image[(d >= 0.72) & (d <= 1.0)] = 1.0
    if noise:
        image += np.random.default_rng(7).normal(0, noise, image.shape)
    return image


def test_consensus_is_deterministic_and_reports_four_views():
    frame = _ellipse(noise=0.03)
    a = segment_slice_seeded(
        frame, seed_x=48, seed_y=48, seed_radius=24,
        multiscale_consensus=True, profile="vesicle",
    )
    b = segment_slice_seeded(
        frame, seed_x=48, seed_y=48, seed_radius=24,
        multiscale_consensus=True, profile="vesicle",
    )
    assert a.ok and b.ok
    assert a.method.startswith("multiscale_consensus")
    assert a.consensus_sigmas == CONSENSUS_SIGMAS
    assert np.array_equal(a.solid_mask, b.solid_mask)
    assert a.consensus_dominant_cluster_size >= 3


def test_elliptical_rbc_is_not_circle_snapped():
    frame = _ellipse(rx=26, ry=13, noise=0.015)
    result = segment_slice_seeded(
        frame, seed_x=48, seed_y=48, seed_radius=28,
        multiscale_consensus=True, profile="rbc",
    )
    assert result.ok and result.solid_mask is not None
    ys, xs = np.where(result.solid_mask)
    assert (xs.max() - xs.min()) / max(ys.max() - ys.min(), 1) > 1.45
def test_dim_noisy_ring_retains_raw_supported_contour():
    frame = _ellipse(rx=20, ry=16) * 0.18
    frame += np.random.default_rng(4).normal(0, 0.012, frame.shape)
    result = segment_slice_seeded(
        frame,
        seed_x=48,
        seed_y=48,
        seed_radius=23,
        multiscale_consensus=True,
        profile="vesicle",
    )
    assert result.ok
    assert result.consensus_raw_edge_support is not None
    assert result.consensus_raw_edge_support >= 0.05


def test_touching_equal_neighbors_fail_closed_without_geometry():
    left = _ellipse(cx=39, cy=48, rx=18, ry=18)
    right = _ellipse(cx=57, cy=48, rx=18, ry=18)
    result = segment_slice_seeded(
        np.maximum(left, right),
        seed_x=48,
        seed_y=48,
        seed_radius=30,
        multiscale_consensus=True,
        profile="vesicle",
    )
    assert not result.ok
    assert result.solid_mask is None





def test_blank_constant_and_nan_fail_closed():
    for frame in (
        np.zeros((64, 64), dtype=float),
        np.ones((64, 64), dtype=float),
        np.full((64, 64), np.nan),
    ):
        result = segment_slice_seeded(
            frame, seed_x=32, seed_y=32, seed_radius=18,
            multiscale_consensus=True, profile="vesicle",
        )
        assert not result.ok
        assert result.consensus_reject_reason is not None


def test_iou_math():
    a = np.zeros((8, 8), bool)
    b = np.zeros((8, 8), bool)
    a[1:5, 1:5] = True
    b[1:5, 1:5] = True
    assert mask_iou(a, b) == 1.0



def test_multiscale_mode_has_separate_cache_identity_and_rejects_conflict():
    assert exact_tracking_mode_token(False, False) == SEEDED_EXACT_MODE_LEGACY
    assert exact_tracking_mode_token(False, True) == SEEDED_EXACT_MODE_MULTISCALE
    with pytest.raises(ValueError, match="mutually exclusive"):
        exact_tracking_mode_token(True, True)

    base = dict(
        stack_identity="fixture:multiscale",
        seed_x=48.0,
        seed_y=48.0,
        seed_frame=0,
        seed_radius=24.0,
        gray_shape=(3, 96, 96),
        profile="vesicle",
    )
    legacy = make_tracking_cache_key(
        **base, tracking_mode=SEEDED_EXACT_MODE_LEGACY
    )
    multiscale = make_tracking_cache_key(
        **base, tracking_mode=SEEDED_EXACT_MODE_MULTISCALE
    )
    assert legacy != multiscale
    assert legacy.tracking_mode != multiscale.tracking_mode


def test_concurrent_legacy_and_multiscale_jobs_remain_isolated():
    stack = np.stack([_ellipse(noise=0.01) for _ in range(3)], axis=0)
    cache = TrackingResultCache(maxsize=8)
    service = TrackingJobService(result_cache=cache, max_active_jobs=2)
    base = dict(
        stack_identity="fixture:multiscale-concurrent",
        seed_x=48.0,
        seed_y=48.0,
        seed_frame=0,
        seed_radius=24.0,
        gray_shape=stack.shape,
        profile="vesicle",
    )
    legacy_key = make_tracking_cache_key(
        **base, tracking_mode=SEEDED_EXACT_MODE_LEGACY
    )
    multiscale_key = make_tracking_cache_key(
        **base, tracking_mode=SEEDED_EXACT_MODE_MULTISCALE
    )
    legacy = service.start(
        key=legacy_key,
        stack=stack,
        seed_x=48.0,
        seed_y=48.0,
        seed_frame=0,
        seed_radius=24.0,
        target_z=2,
    )
    multiscale = service.start(
        key=multiscale_key,
        stack=stack,
        seed_x=48.0,
        seed_y=48.0,
        seed_frame=0,
        seed_radius=24.0,
        target_z=2,
    )
    service.wait(legacy.job_id, timeout=60.0)
    service.wait(multiscale.job_id, timeout=60.0)
    legacy_results = cache.get(legacy_key)
    multiscale_results = cache.get(multiscale_key)
    service.shutdown(timeout=5.0)

    assert legacy_results is not None
    assert multiscale_results is not None
    assert all(
        not result.method.startswith("multiscale_consensus")
        for result in legacy_results
        if result.ok
    )
    assert any(
        result.method.startswith("multiscale_consensus")
        for result in multiscale_results
        if result.ok
    )
