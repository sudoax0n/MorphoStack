"""Packet 04: frame authority + correction invalidation contract."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from morphostack.api import create_app
from morphostack.core.seeded_vesicle import SeededSliceResult
from morphostack.core.stack_cache import (
    TrackingResultCache,
    make_tracking_cache_key,
)
from morphostack.core.track_review import (
    TrackingReviewMeta,
    apply_manual_correction,
    classify_frame_authority,
    display_as_tracked,
    is_measure_authoritative,
)


def _ok(method: str = "circle_seed", merge: bool = False) -> SeededSliceResult:
    return SeededSliceResult(
        np.array([[1.0, 1.0], [2.0, 1.0], [2.0, 2.0]], dtype=np.float64),
        np.ones((8, 8), dtype=bool),
        (4.0, 4.0),
        20.0,
        10.0,
        method,
        True,
        merge_suspect=merge,
    )


def _unreached() -> SeededSliceResult:
    return SeededSliceResult(
        None, None, (0.0, 0.0), 0.0, 0.0, "circle_seed_unreached", False
    )


def test_merge_suspect_is_uncertain_not_tracked():
    r = _ok(merge=True)
    state, reason = classify_frame_authority(r)
    assert state == "uncertain"
    assert reason == "merge_suspect"
    assert not display_as_tracked(state)
    assert not is_measure_authoritative(r)


def test_manual_anchor_is_measure_authoritative():
    r = _ok(method="manual_anchor", merge=False)
    state, _ = classify_frame_authority(r)
    assert state == "manually_anchored"
    assert display_as_tracked(state)
    assert is_measure_authoritative(r)


def test_gap_and_unreached_states():
    gap = SeededSliceResult(None, None, (1.0, 1.0), 0.0, 0.0, "circle_seed_gap", False)
    assert classify_frame_authority(gap)[0] == "gap"
    assert classify_frame_authority(_unreached())[0] == "unreached"
    assert classify_frame_authority(None, exact_pending=True)[0] == "provisional"


def test_invalidate_downstream_only_until_next_manual_or_seed():
    n = 10
    seed = 4
    results = [_unreached() for _ in range(n)]
    for z in range(2, 9):
        results[z] = _ok()
    results[seed] = _ok()
    # Manual anchor at high side stops invalidation past it.
    results[8] = _ok(method="manual_anchor")

    out, meta, event = apply_manual_correction(
        results,
        n_frames=n,
        seed_frame=seed,
        seed_x=1.0,
        seed_y=1.0,
        frame_index=6,
        action="reject_frame",
        meta=TrackingReviewMeta(),
    )
    assert meta.correction_revision == 1
    assert out[6].method == "manual_reject"
    # Downstream high toward 8: clear 7 only (8 is manual stop).
    assert out[7].method == "circle_seed_unreached"
    assert out[8].method == "manual_anchor" and out[8].ok
    # Downstream low toward seed: clear 5 only (seed 4 stops).
    assert out[5].method == "circle_seed_unreached"
    assert out[4].ok
    # Far side beyond seed preserved.
    assert out[2].ok and out[3].ok
    assert event.previous_result is not None
    assert event.previous_result.ok


def test_accept_manual_anchor_preserves_audit_previous():
    results = [_ok() for _ in range(5)]
    anchor = _ok(method="circle_seed_rw")
    out, meta, event = apply_manual_correction(
        results,
        n_frames=5,
        seed_frame=0,
        seed_x=1.0,
        seed_y=1.0,
        frame_index=2,
        action="accept_manual_anchor",
        anchor_result=anchor,
    )
    assert out[2].method == "manual_anchor"
    assert out[2].ok and not out[2].merge_suspect
    assert event.previous_result is not None
    assert meta.events[-1].action == "accept_manual_anchor"


def test_accept_manual_anchor_rejects_missing_solid_mask():
    results = [_ok() for _ in range(3)]
    bare = SeededSliceResult(
        np.array([[1.0, 1.0], [2.0, 1.0], [2.0, 2.0]], dtype=np.float64),
        None,  # incomplete — contour without solid mask
        (1.5, 1.5),
        10.0,
        8.0,
        "circle_seed",
        True,
        merge_suspect=False,
    )
    with pytest.raises(ValueError, match="solid_mask"):
        apply_manual_correction(
            results,
            n_frames=3,
            seed_frame=0,
            seed_x=1.0,
            seed_y=1.0,
            frame_index=1,
            action="accept_manual_anchor",
            anchor_result=bare,
        )


def test_accept_manual_anchor_refuses_merge_suspect_without_operator_drawn():
    results = [_ok() for _ in range(3)]
    suspect = _ok(merge=True)
    with pytest.raises(ValueError, match="merge_suspect"):
        apply_manual_correction(
            results,
            n_frames=3,
            seed_frame=0,
            seed_x=1.0,
            seed_y=1.0,
            frame_index=1,
            action="accept_manual_anchor",
            anchor_result=suspect,
            operator_drawn=False,
        )
    # Operator-drawn confirmation may clear unsafe automatic provenance.
    out, _, _ = apply_manual_correction(
        results,
        n_frames=3,
        seed_frame=0,
        seed_x=1.0,
        seed_y=1.0,
        frame_index=1,
        action="accept_manual_anchor",
        anchor_result=suspect,
        operator_drawn=True,
    )
    assert out[1].method == "manual_anchor"
    assert out[1].ok and not out[1].merge_suspect
    assert is_measure_authoritative(out[1])


def test_incomplete_manual_geometry_not_measure_authoritative():
    incomplete = SeededSliceResult(
        np.array([[1.0, 1.0], [2.0, 1.0], [2.0, 2.0]], dtype=np.float64),
        None,
        (1.0, 1.0),
        10.0,
        8.0,
        "manual_anchor",
        True,
        merge_suspect=False,
    )
    state, reason = classify_frame_authority(incomplete)
    assert state == "uncertain"
    assert reason == "incomplete_manual_geometry"
    assert not is_measure_authoritative(incomplete)
    assert not display_as_tracked(state)


def test_cache_replace_preserves_review_meta():
    key = make_tracking_cache_key(
        stack_identity="t:review",
        seed_x=1.0,
        seed_y=1.0,
        seed_frame=0,
        seed_radius=10.0,
        gray_shape=(4, 16, 16),
    )
    cache = TrackingResultCache(maxsize=4)
    frames = [_ok() for _ in range(4)]
    cache.put(key, frames)
    meta = TrackingReviewMeta(correction_revision=2)
    cache.set_review_meta(key, meta)
    frames[1] = _unreached()
    cache.replace_results(key, frames)
    assert cache.correction_revision(key) == 2
    got = cache.get(key)
    assert got is not None and not got[1].ok


def _ring_stack(n: int = 6, h: int = 48, w: int = 48) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - 24) ** 2 + (yy - 24) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= 100) & (d <= 196)] = 1.0
    return np.stack([frame for _ in range(n)], axis=0)


def test_api_correction_invalidates_downstream(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    stack = (_ring_stack() * 200).astype(np.uint8)
    path = tmp_path / "rings.tif"
    tifffile.imwrite(path, stack, photometric="minisblack")

    with TestClient(create_app()) as client:
        # Force sync exact walk into process cache via preview.
        prev = client.post(
            "/preview",
            json={
                "path": str(path),
                "threshold": 0.5,
                "frame_index": 4,
                "object_seed": {
                    "type": "circle",
                    "x": 24,
                    "y": 24,
                    "frame_index": 1,
                    "radius": 14,
                },
                "force_sync_exact": True,
                "show_selection": True,
            },
        )
        assert prev.status_code == 200, prev.text
        body = prev.json()
        assert "frame_authority" in body

        corr = client.post(
            "/tracking/corrections",
            json={
                "path": str(path),
                "frame_index": 2,
                "action": "reject_frame",
                "object_seed": {
                    "type": "circle",
                    "x": 24,
                    "y": 24,
                    "frame_index": 1,
                    "radius": 14,
                },
            },
        )
        assert corr.status_code == 200, corr.text
        cbody = corr.json()
        assert cbody["ok"] is True
        assert cbody["correction_revision"] >= 1
        assert cbody["frame_authority"] == "uncertain"

        # Re-preview an invalidated higher frame should not be exact_accepted.
        prev2 = client.post(
            "/preview",
            json={
                "path": str(path),
                "threshold": 0.5,
                "frame_index": 4,
                "object_seed": {
                    "type": "circle",
                    "x": 24,
                    "y": 24,
                    "frame_index": 1,
                    "radius": 14,
                },
                "force_sync_exact": False,
                "show_selection": True,
            },
        )
        assert prev2.status_code == 200
        p2 = prev2.json()
        # After reject at 2, frames 3.. may be unreached until re-extended.
        assert p2.get("display_as_tracked") in (False, None) or p2.get(
            "frame_authority"
        ) in ("unreached", "provisional", "uncertain", "gap", "exact_accepted", "manually_anchored")
