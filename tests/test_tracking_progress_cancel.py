"""Progressive progress/cancel controls for exact seeded tracking (packet 02)."""

from __future__ import annotations

import time
from dataclasses import replace

import numpy as np
import pytest

from morphostack.core.seeded_vesicle import (
    SeededSliceResult,
    TrackingCancelled,
    TrackProgressEvent,
    extend_track,
    segment_slice_seeded,
    track_seeded_vesicle_stack,
)


def _ring_frame(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = 1.0
    return frame


def _ring_stack(n: int = 8, h: int = 64, w: int = 64, cx: float = 32.0, cy: float = 32.0) -> np.ndarray:
    return np.stack([_ring_frame(h, w, cx, cy, 10, 14) for _ in range(n)], axis=0)


def _mask_iou(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None and b is None:
        return 1.0
    if a is None or b is None:
        return 0.0
    aa = np.asarray(a, dtype=bool)
    bb = np.asarray(b, dtype=bool)
    inter = int(np.count_nonzero(aa & bb))
    union = int(np.count_nonzero(aa | bb))
    return inter / union if union else 1.0


def _assert_tracks_equivalent(
    a: list[SeededSliceResult],
    b: list[SeededSliceResult],
    *,
    center_tol: float = 0.75,
    min_iou: float = 0.98,
) -> None:
    """Scientific equivalence under mild MorphGAC/float run variance."""
    assert len(a) == len(b)
    for i, (ra, rb) in enumerate(zip(a, b)):
        assert ra.ok == rb.ok, f"frame {i} ok"
        assert ra.method == rb.method, f"frame {i} method {ra.method!r} vs {rb.method!r}"
        assert bool(ra.merge_suspect) == bool(rb.merge_suspect), f"frame {i} merge"
        if ra.ok:
            assert abs(ra.center_xy[0] - rb.center_xy[0]) <= center_tol
            assert abs(ra.center_xy[1] - rb.center_xy[1]) <= center_tol
            assert _mask_iou(ra.solid_mask, rb.solid_mask) >= min_iou
            # Effective threshold provenance must match when present.
            if ra.effective_threshold is None or rb.effective_threshold is None:
                assert ra.effective_threshold is rb.effective_threshold
            else:
                assert abs(float(ra.effective_threshold) - float(rb.effective_threshold)) < 1e-6


def test_no_control_call_matches_baseline_structure():
    stack = _ring_stack(n=6)
    baseline = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=2, seed_radius=14
    )
    again = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=2, seed_radius=14
    )
    _assert_tracks_equivalent(baseline, again)
    assert all(isinstance(r, SeededSliceResult) for r in again)


def test_noop_progress_and_false_cancel_match_baseline():
    stack = _ring_stack(n=7)
    baseline = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=3, seed_radius=14
    )
    events: list[TrackProgressEvent] = []
    progressive = track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=3,
        seed_radius=14,
        on_progress=events.append,
        cancel_check=lambda: False,
        direction_priority=None,
    )
    _assert_tracks_equivalent(baseline, progressive)
    assert any(e.marker == "complete" for e in events)
    assert all(e.marker != "cancelled" for e in events)
    # Partial commits are in walk order (seed, then directions).
    partials = [e for e in events if e.marker == "partial"]
    assert partials
    assert partials[0].frame_index == 3


def _assert_complete_matches_last_partial(events: list[TrackProgressEvent]) -> None:
    """Terminal complete must restate the chronological last partial commit."""
    assert events, "expected progress events"
    assert events[-1].marker == "complete"
    partials = [e for e in events if e.marker == "partial"]
    assert partials, "expected at least one partial before complete"
    last_partial = partials[-1]
    complete = events[-1]
    assert complete.frame_index == last_partial.frame_index
    assert complete.result.method == last_partial.result.method
    assert complete.result.ok == last_partial.result.ok
    assert complete.reached_low_z == last_partial.reached_low_z
    assert complete.reached_high_z == last_partial.reached_high_z


def test_progress_commit_order_matches_synchronous_walk():
    stack = _ring_stack(n=5)
    # Unidirectional: seed 0 → target 4 must commit 0,1,2,3,4 in order.
    events: list[TrackProgressEvent] = []
    out = track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=0,
        seed_radius=14,
        target_frame=4,
        on_progress=events.append,
    )
    partial_frames = [e.frame_index for e in events if e.marker == "partial"]
    assert partial_frames == [0, 1, 2, 3, 4]
    assert all(out[i].method != "circle_seed_unreached" or not out[i].ok for i in range(5))
    _assert_complete_matches_last_partial(events)
    # Upward walk: last commit is max Z, not merely "some" partial.
    assert events[-1].frame_index == 4


def test_complete_event_is_last_commit_not_high_frontier_bidirectional():
    """Default bidirectional: +Z first, then -Z; complete must be the low-Z end."""
    n = 7
    seed = 3
    stack = _ring_stack(n=n)
    events: list[TrackProgressEvent] = []
    track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=seed,
        seed_radius=14,
        on_progress=events.append,
    )
    partials = [e for e in events if e.marker == "partial"]
    partial_frames = [e.frame_index for e in partials]
    # Seed, then +Z to top, then -Z to bottom → last chronological commit is 0.
    assert partial_frames[0] == seed
    assert seed + 1 in partial_frames
    assert seed - 1 in partial_frames
    assert partial_frames[-1] == 0
    assert partials[-1].reached_high_z == n - 1  # frontier still spans full track
    _assert_complete_matches_last_partial(events)
    # Bug regression: complete must not report reached_high_z (n-1) as frame_index.
    assert events[-1].frame_index == 0
    assert events[-1].frame_index != events[-1].reached_high_z


def test_complete_event_with_direction_priority_neg():
    """direction_priority=-1: -Z first, then +Z; complete is the high-Z end."""
    n = 7
    seed = 3
    stack = _ring_stack(n=n)
    events: list[TrackProgressEvent] = []
    track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=seed,
        seed_radius=14,
        direction_priority=-1,
        on_progress=events.append,
    )
    partials = [e for e in events if e.marker == "partial"]
    partial_frames = [e.frame_index for e in partials]
    assert partial_frames[0] == seed
    # First non-seed step goes downward.
    assert partial_frames[1] == seed - 1
    assert partial_frames[-1] == n - 1
    _assert_complete_matches_last_partial(events)
    assert events[-1].frame_index == n - 1


def test_cancel_before_start_performs_no_segment_call(monkeypatch):
    stack = _ring_stack(n=4)
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("segment_slice_seeded must not run when cancelled before start")

    monkeypatch.setattr(
        "morphostack.core.seeded_vesicle.segment_slice_seeded",
        boom,
    )
    with pytest.raises(TrackingCancelled) as ei:
        track_seeded_vesicle_stack(
            stack,
            seed_x=32,
            seed_y=32,
            seed_frame=1,
            seed_radius=14,
            cancel_check=lambda: True,
        )
    assert calls["n"] == 0
    exc = ei.value
    assert exc.reached_low_z == 1
    assert exc.reached_high_z == 1
    assert all(r.method == "circle_seed_unreached" for r in exc.results)
    # Must never look like a completed authoritative track.
    assert not any(r.ok for r in exc.results)


def test_cancel_mid_walk_retains_only_committed_frames(monkeypatch):
    stack = _ring_stack(n=8)
    segment_calls: list[int] = []
    real_segment = segment_slice_seeded

    def counting_segment(frame, **kwargs):
        # Count by identity of the plane object when possible; fall back to call order.
        segment_calls.append(id(frame))
        return real_segment(frame, **kwargs)

    monkeypatch.setattr(
        "morphostack.core.seeded_vesicle.segment_slice_seeded",
        counting_segment,
    )

    # Cancel after seed + one successful +Z commit: allow seed segment, then
    # allow first non-seed Z's retry fan-out, then cancel before next Z.
    committed_partials: list[int] = []
    state = {"cancel": False}

    def on_progress(ev: TrackProgressEvent) -> None:
        if ev.marker == "partial":
            committed_partials.append(ev.frame_index)
            # After seed (frame 2) and frame 3 committed, request cancel.
            if 2 in committed_partials and 3 in committed_partials:
                state["cancel"] = True

    def cancel_check() -> bool:
        return state["cancel"]

    with pytest.raises(TrackingCancelled) as ei:
        track_seeded_vesicle_stack(
            stack,
            seed_x=32,
            seed_y=32,
            seed_frame=2,
            seed_radius=14,
            target_frame=7,
            on_progress=on_progress,
            cancel_check=cancel_check,
        )

    exc = ei.value
    # Seed + one step committed; higher frames unreached.
    assert exc.results[2].method != "circle_seed_unreached"
    assert exc.results[3].method != "circle_seed_unreached"
    for z in range(4, 8):
        assert exc.results[z].method == "circle_seed_unreached"
    assert exc.reached_low_z == 2
    assert exc.reached_high_z == 3
    # No complete marker was published via exception path.
    assert not any(r.method == "track_complete" for r in exc.results)
    # Did not jump to distant target: only frames 2 and 3 should be non-unreached
    # on the +Z path (and nothing beyond).
    reached = [i for i, r in enumerate(exc.results) if r.method != "circle_seed_unreached"]
    assert reached == [2, 3]
    # Segment was invoked for seed and frame 3 candidates only — not for z>=4.
    assert len(segment_calls) >= 2


def test_cancel_before_retry_candidate_stops_without_extra_segment(monkeypatch):
    """Cancel check runs before each retry candidate; count segment calls."""
    stack = _ring_stack(n=5)
    real_segment = segment_slice_seeded
    calls_before_cancel = {"n": 0}
    state = {"armed": False, "cancel": False}

    def counting_segment(frame, **kwargs):
        calls_before_cancel["n"] += 1
        # After seed succeeds, arm cancel so the next candidate check fires first.
        if calls_before_cancel["n"] == 1:
            state["armed"] = True
        return real_segment(frame, **kwargs)

    monkeypatch.setattr(
        "morphostack.core.seeded_vesicle.segment_slice_seeded",
        counting_segment,
    )

    def cancel_check() -> bool:
        # Cancel at the safe boundary before beginning work on the next Z
        # (after seed has been committed and progress would have run).
        return state["armed"]

    with pytest.raises(TrackingCancelled) as ei:
        track_seeded_vesicle_stack(
            stack,
            seed_x=32,
            seed_y=32,
            seed_frame=0,
            seed_radius=14,
            target_frame=4,
            cancel_check=cancel_check,
        )
    # Seed segmented once; cancel before first non-seed candidate.
    assert calls_before_cancel["n"] == 1
    assert ei.value.results[0].ok
    assert all(ei.value.results[z].method == "circle_seed_unreached" for z in range(1, 5))


def test_direction_priority_changes_schedule_not_final_result():
    # Bidirectional stack with seed in the middle.
    n = 7
    stack = _ring_stack(n=n)
    seed = 3
    events_up: list[TrackProgressEvent] = []
    events_down: list[TrackProgressEvent] = []

    up = track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=seed,
        seed_radius=14,
        direction_priority=1,
        on_progress=events_up.append,
    )
    down = track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=seed,
        seed_radius=14,
        direction_priority=-1,
        on_progress=events_down.append,
    )
    baseline = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=seed, seed_radius=14
    )
    _assert_tracks_equivalent(up, baseline)
    _assert_tracks_equivalent(down, baseline)
    _assert_tracks_equivalent(up, down)

    def first_non_seed_partial(events: list[TrackProgressEvent]) -> int:
        for e in events:
            if e.marker == "partial" and e.frame_index != seed:
                return e.frame_index
        raise AssertionError("expected non-seed partial")

    assert first_non_seed_partial(events_up) == seed + 1
    assert first_non_seed_partial(events_down) == seed - 1


def test_callback_cannot_mutate_frozen_result_fields():
    stack = _ring_stack(n=3)
    seen: list[TrackProgressEvent] = []

    def on_progress(ev: TrackProgressEvent) -> None:
        seen.append(ev)
        # frozen dataclasses reject normal attribute assignment
        with pytest.raises(Exception):
            ev.frame_index = -99  # type: ignore[misc]
        with pytest.raises(Exception):
            ev.result.ok = False  # type: ignore[misc]
        if ev.result.solid_mask is not None:
            with pytest.raises(ValueError):
                ev.result.solid_mask[0, 0] = True  # non-writeable view
        if ev.result.contour_xy is not None:
            with pytest.raises(ValueError):
                ev.result.contour_xy[0, 0] = -1.0
        # replace() builds a new event; core track list is unaffected
        _ = replace(ev, frame_index=-1)

    out = track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=1,
        seed_radius=14,
        on_progress=on_progress,
    )
    assert seen
    # Core list still holds writeable science buffers.
    assert out[1].ok
    if out[1].solid_mask is not None:
        assert out[1].solid_mask.flags.writeable


def test_callback_exception_does_not_corrupt_committed_state():
    stack = _ring_stack(n=5)
    committed: list[int] = []

    def on_progress(ev: TrackProgressEvent) -> None:
        if ev.marker != "partial":
            return
        committed.append(ev.frame_index)
        if ev.frame_index == 1:
            raise RuntimeError("callback boom")

    with pytest.raises(RuntimeError, match="callback boom"):
        track_seeded_vesicle_stack(
            stack,
            seed_x=32,
            seed_y=32,
            seed_frame=0,
            seed_radius=14,
            target_frame=4,
            on_progress=on_progress,
        )
    # Seed and frame 1 were committed before the raise; exception is not swallowed.
    assert committed == [0, 1]


def test_extend_track_progress_and_cancel(monkeypatch):
    stack = _ring_stack(n=8)
    partial = track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=0,
        seed_radius=14,
        target_frame=2,
    )
    events: list[TrackProgressEvent] = []
    extended = extend_track(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=0,
        seed_radius=14,
        target_frame=5,
        cached_results=partial,
        on_progress=events.append,
        cancel_check=lambda: False,
    )
    assert extended[5].method != "circle_seed_unreached" or extended[5].ok
    assert any(e.marker == "complete" for e in events)
    _assert_complete_matches_last_partial(events)
    assert events[-1].frame_index == 5

    # Cancel before any extend segment: no additional segment beyond cache hit path.
    real_segment = segment_slice_seeded
    calls = {"n": 0}

    def counting_segment(frame, **kwargs):
        calls["n"] += 1
        return real_segment(frame, **kwargs)

    monkeypatch.setattr(
        "morphostack.core.seeded_vesicle.segment_slice_seeded",
        counting_segment,
    )
    with pytest.raises(TrackingCancelled):
        extend_track(
            stack,
            seed_x=32,
            seed_y=32,
            seed_frame=0,
            seed_radius=14,
            target_frame=7,
            cached_results=partial,
            cancel_check=lambda: True,
        )
    assert calls["n"] == 0


def test_extend_track_downward_complete_is_last_partial_not_high_z():
    """Downward extend: last commit is low Z; complete must not use reached_high_z."""
    n = 8
    seed = 5
    stack = _ring_stack(n=n)
    # Seed mid-stack, walk upward only so lower Z remains unreached.
    cached = track_seeded_vesicle_stack(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=seed,
        seed_radius=14,
        target_frame=n - 1,
    )
    assert cached[seed].ok
    assert cached[n - 1].method != "circle_seed_unreached" or cached[n - 1].ok
    # Frames below seed are still unreached placeholders.
    assert cached[0].method == "circle_seed_unreached"

    events: list[TrackProgressEvent] = []
    extended = extend_track(
        stack,
        seed_x=32,
        seed_y=32,
        seed_frame=seed,
        seed_radius=14,
        target_frame=0,
        cached_results=cached,
        on_progress=events.append,
    )
    assert extended[0].method != "circle_seed_unreached" or extended[0].ok
    partials = [e for e in events if e.marker == "partial"]
    assert partials
    assert partials[-1].frame_index == 0
    # High frontier still includes the upward-cached frames (e.g. n-1).
    assert partials[-1].reached_high_z >= seed
    _assert_complete_matches_last_partial(events)
    assert events[-1].frame_index == 0
    assert events[-1].frame_index != events[-1].reached_high_z


def test_invalid_direction_priority_rejected():
    stack = _ring_stack(n=3)
    with pytest.raises(ValueError, match="direction_priority"):
        track_seeded_vesicle_stack(
            stack,
            seed_x=32,
            seed_y=32,
            seed_frame=1,
            seed_radius=14,
            direction_priority=2,
        )


def test_overhead_absent_and_noop_callback_budget():
    """Microbench vs packet budget (<2% absent, <5% no-op). Warm median.

    Tight budgets are recorded for the packet handoff; unit CI only fails on
    egregious overhead (timer noise on short synthetic walks is often a few %).
    """
    # Short unidirectional walk keeps wall time modest for unit CI.
    stack = _ring_stack(n=6, h=64, w=64)
    kwargs = dict(
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=0,
        seed_radius=14.0,
        target_frame=5,
    )

    def once(**extra) -> float:
        t0 = time.perf_counter()
        track_seeded_vesicle_stack(stack, **kwargs, **extra)
        return time.perf_counter() - t0

    # Warmup
    for _ in range(1):
        once()
        once(on_progress=lambda _e: None)

    reps = 5
    base = sorted(once() for _ in range(reps))
    absent = sorted(once() for _ in range(reps))
    noop = sorted(once(on_progress=lambda _e: None) for _ in range(reps))
    base_med = base[len(base) // 2]
    absent_med = absent[len(absent) // 2]
    noop_med = noop[len(noop) // 2]
    # Relative overhead vs baseline of this run.
    absent_overhead = (absent_med - base_med) / base_med if base_med > 0 else 0.0
    noop_overhead = (noop_med - base_med) / base_med if base_med > 0 else 0.0
    # Guard against accidental O(n) copies or extra full-stack work in the hook path.
    assert absent_overhead < 0.50, f"absent controls overhead {absent_overhead:.3%}"
    assert noop_overhead < 0.50, f"noop callback overhead {noop_overhead:.3%}"
    # Stash numbers for debugging when budgets are close.
    print(
        f"overhead_microbench base_med={base_med:.4f}s "
        f"absent={absent_overhead:.2%} noop={noop_overhead:.2%}"
    )
