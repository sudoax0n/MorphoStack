"""Packet 01 — tracking instrumentation is neutral and off by default."""

from __future__ import annotations

import time

import numpy as np  # median used in overhead hard-gate test

from morphostack.api.tracking_jobs import TrackingJobService
from morphostack.core.seeded_vesicle import (
    enable_tracking_instrumentation,
    get_tracking_instrumentation,
    is_tracking_instrumentation_enabled,
    reset_tracking_instrumentation,
    scientific_result_fingerprint,
    segment_slice_seeded,
    track_seeded_vesicle_stack,
)
from morphostack.core.stack_cache import (
    TrackingResultCache,
    make_tracking_cache_key,
)


def _ring_frame(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = 1.0
    return frame


def _ring_stack(n: int = 5) -> np.ndarray:
    frames = []
    for z in range(n):
        frames.append(_ring_frame(64, 64, 28 + z, 32, 10, 14))
    return np.stack(frames, axis=0)


def setup_function() -> None:
    enable_tracking_instrumentation(False)
    reset_tracking_instrumentation()


def teardown_function() -> None:
    enable_tracking_instrumentation(False)
    reset_tracking_instrumentation()


def test_instrumentation_off_by_default():
    assert is_tracking_instrumentation_enabled() is False
    snap = get_tracking_instrumentation()
    assert snap["enabled"] is False
    assert snap["segment_calls"] == 0


def test_instrumentation_off_matches_on_scientific_outputs():
    """Masks/methods/statuses identical whether instrumentation is on or off."""
    stack = _ring_stack(4)

    enable_tracking_instrumentation(False)
    off = track_seeded_vesicle_stack(
        stack, seed_x=28, seed_y=32, seed_frame=0, seed_radius=14, target_frame=3
    )
    off_fps = [scientific_result_fingerprint(r) for r in off]

    enable_tracking_instrumentation(True)
    reset_tracking_instrumentation()
    on = track_seeded_vesicle_stack(
        stack, seed_x=28, seed_y=32, seed_frame=0, seed_radius=14, target_frame=3
    )
    on_fps = [scientific_result_fingerprint(r) for r in on]
    instr = get_tracking_instrumentation()

    assert off_fps == on_fps
    assert instr["enabled"] is True
    assert instr["segment_calls"] >= 1
    assert instr["frame_count"] >= 1
    # Decisions only for non-seed association attempts; seed still commits frames.
    assert "segment_total" in instr["stage_summary"] or instr["event_count"] > 0


def test_instrumentation_records_stages_and_decisions():
    frame = _ring_frame(64, 64, 32, 32, 10, 14)
    enable_tracking_instrumentation(True)
    reset_tracking_instrumentation()
    res = segment_slice_seeded(frame, seed_x=32, seed_y=32, seed_radius=14, refine=True)
    assert res.ok
    snap = get_tracking_instrumentation()
    assert snap["segment_calls"] == 1
    stages = snap["stage_summary"]
    assert "segment_total" in stages
    # Exact path uses bilateral + full QC + MorphGAC on reference gates.
    assert "bilateral" in stages
    assert "qc_full" in stages or "qc_cheap" in stages


def test_cache_and_job_observe_events():
    stack = _ring_stack(3)
    cache = TrackingResultCache()
    service = TrackingJobService(result_cache=cache, max_active_jobs=1)
    key = make_tracking_cache_key(
        stack_identity="test:instrumentation",
        seed_x=28.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        gray_shape=tuple(int(v) for v in stack.shape),
        roi=None,
        z_range=None,
        profile="vesicle",
    )
    enable_tracking_instrumentation(True)
    reset_tracking_instrumentation()
    snap = service.start(
        key=key,
        stack=stack,
        seed_x=28.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        target_z=2,
    )
    final = service.wait(snap.job_id, timeout=60.0)
    assert final.state == "complete"
    instr = get_tracking_instrumentation()
    kinds = {e.get("kind") for e in instr["events"]}
    assert "job_start" in kinds
    assert "job_complete" in kinds
    assert "cache_put" in kinds or "cache_merge" in kinds
    service.shutdown(timeout=5.0)


def test_instrumentation_overhead_warm_track_under_5_percent():
    """Warm whole-track instrumentation overhead must stay within hard 5% budget."""
    # Whole-track sample (not a 2-frame microbench): amortizes fixed record cost.
    stack = _ring_stack(12)
    for _ in range(2):
        track_seeded_vesicle_stack(
            stack, seed_x=28, seed_y=32, seed_frame=0, seed_radius=14, target_frame=11
        )

    n = 8
    offs: list[float] = []
    ons: list[float] = []
    for _ in range(n):
        enable_tracking_instrumentation(False)
        t0 = time.perf_counter()
        track_seeded_vesicle_stack(
            stack, seed_x=28, seed_y=32, seed_frame=0, seed_radius=14, target_frame=11
        )
        offs.append((time.perf_counter() - t0) * 1000.0)

        enable_tracking_instrumentation(True)
        reset_tracking_instrumentation()
        t0 = time.perf_counter()
        track_seeded_vesicle_stack(
            stack, seed_x=28, seed_y=32, seed_frame=0, seed_radius=14, target_frame=11
        )
        ons.append((time.perf_counter() - t0) * 1000.0)

    off_ms = float(np.median(offs))
    on_ms = float(np.median(ons))
    overhead = (on_ms - off_ms) / max(off_ms, 1e-6)
    assert overhead <= 0.05, (
        f"instrumentation overhead {overhead:.1%} exceeds hard 5% "
        f"(off_med={off_ms:.1f}ms on_med={on_ms:.1f}ms)"
    )
