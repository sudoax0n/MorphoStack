"""Single-flight tracking job service (packet 03)."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from morphostack.api import create_app
from morphostack.api.tracking_jobs import TrackingJobService
from morphostack.core.seeded_vesicle import (
    SeededSliceResult,
    track_seeded_vesicle_stack,
)
from morphostack.core.stack_cache import (
    TrackingResultCache,
    make_tracking_cache_key,
    tracking_key_revision,
)


def _ring_frame(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = 1.0
    return frame


def _ring_stack(n: int = 8, h: int = 64, w: int = 64) -> np.ndarray:
    return np.stack([_ring_frame(h, w, 32, 32, 10, 14) for _ in range(n)], axis=0)


def _key(**overrides):
    base = dict(
        stack_identity="test:stack-v1",
        seed_x=32.0,
        seed_y=32.0,
        seed_frame=3,
        seed_radius=14.0,
        gray_shape=(8, 64, 64),
    )
    base.update(overrides)
    return make_tracking_cache_key(**base)


def _assert_exact_scientific_parity(
    a: list[SeededSliceResult], b: list[SeededSliceResult]
) -> None:
    """Packet gate: ordered frames, methods, centers, masks, contours, thresholds."""
    assert len(a) == len(b)
    for i, (ra, rb) in enumerate(zip(a, b)):
        assert ra.ok is rb.ok, f"frame {i} ok"
        assert ra.method == rb.method, f"frame {i} method {ra.method!r} vs {rb.method!r}"
        assert bool(ra.merge_suspect) is bool(rb.merge_suspect), f"frame {i} merge"
        assert ra.center_xy == rb.center_xy, f"frame {i} center"
        assert ra.area_px == rb.area_px, f"frame {i} area"
        assert ra.perimeter_px == rb.perimeter_px, f"frame {i} perimeter"
        assert ra.effective_threshold == rb.effective_threshold, f"frame {i} thr"
        if ra.contour_xy is None or rb.contour_xy is None:
            assert ra.contour_xy is rb.contour_xy, f"frame {i} contour nullness"
        else:
            np.testing.assert_array_equal(ra.contour_xy, rb.contour_xy, err_msg=f"frame {i} contour")
        if ra.solid_mask is None or rb.solid_mask is None:
            assert ra.solid_mask is rb.solid_mask, f"frame {i} mask nullness"
        else:
            np.testing.assert_array_equal(ra.solid_mask, rb.solid_mask, err_msg=f"frame {i} mask")


@pytest.fixture
def service():
    cache = TrackingResultCache(maxsize=8)
    svc = TrackingJobService(result_cache=cache, max_active_jobs=1, max_retained_jobs=8)
    yield svc
    svc.shutdown(timeout=10.0)


def test_single_flight_attach_with_fake_track(service: TrackingJobService):
    """N starts for one key → one science call; attach returns same job_id."""
    stack = _ring_stack(n=6)
    key = _key(gray_shape=stack.shape, seed_frame=1)
    release = threading.Event()
    started = threading.Event()
    calls = {"n": 0}
    real = track_seeded_vesicle_stack

    def slow_track(*args, **kwargs):
        calls["n"] += 1
        started.set()
        assert release.wait(timeout=5)
        return real(*args, **kwargs)

    service._track_fn = slow_track  # type: ignore[method-assign]

    s1 = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=5
    )
    assert started.wait(timeout=3)
    s2 = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=4
    )
    s3 = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=3
    )
    assert s1.job_id == s2.job_id == s3.job_id
    assert s2.attached and s3.attached
    assert not s1.attached
    assert calls["n"] == 1
    assert s3.requested_target_z == 3  # last attach wins target
    assert s2.requested_target_z == 4  # snapshot at attach time for s2
    release.set()
    done = service.wait(s1.job_id, timeout=30)
    assert done.state == "complete"
    assert service.track_invocations == 1


def test_progressive_frames_monotonic_and_cache_write(service: TrackingJobService):
    stack = _ring_stack(n=6)
    key = _key(gray_shape=stack.shape, seed_frame=0)
    observed: list[tuple[int, ...]] = []
    lock = threading.Lock()

    real = track_seeded_vesicle_stack

    def tracking(*args, **kwargs):
        on_progress = kwargs.get("on_progress")

        def wrapped(ev):
            if on_progress is not None:
                on_progress(ev)
            with lock:
                snap = service.status_for_key(key)
                if snap is not None:
                    observed.append(snap.available_exact_frames)

        kwargs = dict(kwargs)
        kwargs["on_progress"] = wrapped
        return real(*args, **kwargs)

    service._track_fn = tracking  # type: ignore[method-assign]
    snap = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=0, seed_radius=14, target_z=5
    )
    done = service.wait(snap.job_id, timeout=60)
    assert done.state == "complete"
    assert done.available_exact_frames
    # Monotonic growth of available frame sets
    prev: set[int] = set()
    for frames in observed:
        cur = set(frames)
        assert prev.issubset(cur)
        prev = cur
    cached = service.result_cache.get(key)
    assert cached is not None
    assert cached[0].ok
    assert cached[5].method != "circle_seed_unreached" or cached[5].ok


def test_reprioritize_updates_requested_target(service: TrackingJobService):
    stack = _ring_stack(n=8)
    key = _key(gray_shape=stack.shape, seed_frame=2)
    release = threading.Event()
    started = threading.Event()
    seen: dict[str, object] = {}

    def slow_track(*args, **kwargs):
        started.set()
        # Service must pass live callables, not frozen ints.
        seen["target_frame"] = kwargs.get("target_frame")
        seen["direction_priority"] = kwargs.get("direction_priority")
        assert release.wait(timeout=5)
        return track_seeded_vesicle_stack(*args, **kwargs)

    service._track_fn = slow_track  # type: ignore[method-assign]
    snap = service.start(
        key=key,
        stack=stack,
        seed_x=32,
        seed_y=32,
        seed_frame=2,
        seed_radius=14,
        target_z=4,
        direction_priority=1,
    )
    assert started.wait(timeout=3)
    updated = service.reprioritize(snap.job_id, target_z=7, direction_priority=-1)
    assert updated.requested_target_z == 7
    assert updated.direction_priority == -1
    # Live callables reflect reprioritize before science continues.
    assert callable(seen["target_frame"])
    assert callable(seen["direction_priority"])
    assert seen["target_frame"]() == 7
    assert seen["direction_priority"]() == -1
    release.set()
    service.wait(snap.job_id, timeout=30)


def test_live_reprioritize_changes_next_frontier(service: TrackingJobService):
    """Mid-walk direction_priority flip changes the next committed non-seed frame side."""
    n = 9
    seed = 4
    stack = _ring_stack(n=n)
    key = _key(gray_shape=stack.shape, seed_frame=seed)
    partial_frames: list[int] = []
    flip_at = threading.Event()
    flipped = threading.Event()

    def tracking(*args, **kwargs):
        on_progress = kwargs.get("on_progress")

        def wrapped(ev):
            if on_progress is not None:
                on_progress(ev)
            if getattr(ev, "marker", None) == "partial":
                partial_frames.append(int(ev.frame_index))
                # After seed + first step toward +Z, flip priority to -Z.
                if len(partial_frames) == 2 and partial_frames[1] == seed + 1:
                    flip_at.set()
                    assert flipped.wait(timeout=5)

        kwargs = dict(kwargs)
        kwargs["on_progress"] = wrapped
        return track_seeded_vesicle_stack(*args, **kwargs)

    service._track_fn = tracking  # type: ignore[method-assign]
    snap = service.start(
        key=key,
        stack=stack,
        seed_x=32,
        seed_y=32,
        seed_frame=seed,
        seed_radius=14,
        # Full bidirectional so both frontiers exist; priority steers next step.
        target_z=None,
        direction_priority=1,
    )
    assert flip_at.wait(timeout=30)
    service.reprioritize(snap.job_id, direction_priority=-1)
    flipped.set()
    done = service.wait(snap.job_id, timeout=60)
    assert done.state == "complete"
    # Second commit was +Z; third must prefer -Z after live reprioritize.
    assert partial_frames[0] == seed
    assert partial_frames[1] == seed + 1
    assert partial_frames[2] == seed - 1


def test_cancel_releases_ownership_not_complete(service: TrackingJobService):
    stack = _ring_stack(n=12)
    key = _key(gray_shape=stack.shape, seed_frame=1)
    started = threading.Event()

    def slow_track(*args, **kwargs):
        cancel_check = kwargs.get("cancel_check")
        started.set()
        # Spin until cancel is visible.
        deadline = time.time() + 5
        while time.time() < deadline:
            if cancel_check is not None and cancel_check():
                from morphostack.core.seeded_vesicle import TrackingCancelled

                n = stack.shape[0]
                results = [
                    SeededSliceResult(
                        None, None, (32.0, 32.0), 0.0, 0.0, "circle_seed_unreached", False
                    )
                    for _ in range(n)
                ]
                results[1] = SeededSliceResult(
                    None, None, (32.0, 32.0), 1.0, 1.0, "circle_seed", True
                )
                raise TrackingCancelled(results, reached_low_z=1, reached_high_z=1)
            time.sleep(0.01)
        return track_seeded_vesicle_stack(*args, **kwargs)

    service._track_fn = slow_track  # type: ignore[method-assign]
    snap = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=10
    )
    assert started.wait(timeout=3)
    service.cancel(snap.job_id)
    # Ownership released: same key can start a new job.
    assert service.status_for_key(key) is None or service.status_for_key(key).job_id != snap.job_id or service.status_for_key(key).state == "cancelled"
    done = service.wait(snap.job_id, timeout=10)
    assert done.state == "cancelled"
    assert done.state != "complete"


def test_failed_job_not_complete(service: TrackingJobService):
    stack = _ring_stack(n=4)
    key = _key(gray_shape=stack.shape, seed_frame=0)

    def boom(*_a, **_k):
        raise RuntimeError("science exploded")

    service._track_fn = boom  # type: ignore[method-assign]
    snap = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=0, seed_radius=14
    )
    done = service.wait(snap.job_id, timeout=10)
    assert done.state == "failed"
    assert done.error_code == "RuntimeError"
    assert "exploded" in (done.message or "")


def test_revision_isolates_results(service: TrackingJobService):
    stack = _ring_stack(n=5)
    key_a = _key(stack_identity="rev-a", gray_shape=stack.shape, seed_frame=1)
    key_b = replace(key_a, stack_identity="rev-b")
    assert tracking_key_revision(key_a) != tracking_key_revision(key_b)

    s_a = service.start(
        key=key_a, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=3
    )
    service.wait(s_a.job_id, timeout=60)
    assert service.result_cache.get(key_a) is not None
    assert service.result_cache.get(key_b) is None

    s_b = service.start(
        key=key_b, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=3
    )
    service.wait(s_b.job_id, timeout=60)
    assert service.result_cache.get(key_b) is not None
    # Keys remain isolated
    ca = service.result_cache.get(key_a)
    cb = service.result_cache.get(key_b)
    assert ca is not None and cb is not None
    assert ca is not cb


def test_completed_matches_synchronous_reference(service: TrackingJobService, monkeypatch):
    """Exact scientific-field equivalence: methods, centers, masks, contours, thr."""
    import morphostack.core.seeded_vesicle as sv

    real_segment = sv.segment_slice_seeded

    def deterministic_segment(frame, **kwargs):
        # Disable MorphGAC refinement for bit-stable parity across two runs.
        kwargs = dict(kwargs)
        kwargs["refine"] = False
        return real_segment(frame, **kwargs)

    monkeypatch.setattr(sv, "segment_slice_seeded", deterministic_segment)

    stack = _ring_stack(n=7)
    key = _key(gray_shape=stack.shape, seed_frame=2)
    ref = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=2, seed_radius=14, target_frame=6
    )
    snap = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=2, seed_radius=14, target_z=6
    )
    done = service.wait(snap.job_id, timeout=60)
    assert done.state == "complete"
    cached = service.result_cache.get(key)
    assert cached is not None
    _assert_exact_scientific_parity(ref, cached)


def test_completed_cache_is_exact_track_return(service: TrackingJobService):
    """Service must put the exact list returned by track_fn (no field rewrite)."""
    stack = _ring_stack(n=4)
    key = _key(gray_shape=stack.shape, seed_frame=1)
    canned = [
        SeededSliceResult(None, None, (1.0, 2.0), 0.0, 0.0, "circle_seed_unreached", False),
        SeededSliceResult(
            np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64),
            np.zeros((64, 64), dtype=bool),
            (32.5, 31.5),
            12.0,
            8.0,
            "circle_seed",
            True,
            merge_suspect=False,
            effective_threshold=0.25,
        ),
        SeededSliceResult(None, None, (32.0, 32.0), 0.0, 0.0, "circle_seed_gap", False),
        SeededSliceResult(None, None, (32.0, 32.0), 0.0, 0.0, "circle_seed_unreached", False),
    ]
    canned[1].solid_mask[30:35, 30:35] = True

    def fake_track(*_a, **_k):
        return list(canned)

    service._track_fn = fake_track  # type: ignore[method-assign]
    snap = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=2
    )
    done = service.wait(snap.job_id, timeout=10)
    assert done.state == "complete"
    cached = service.result_cache.get(key)
    assert cached is not None
    _assert_exact_scientific_parity(canned, cached)


def test_shutdown_leaves_no_live_worker(service: TrackingJobService):
    stack = _ring_stack(n=10)
    key = _key(gray_shape=stack.shape, seed_frame=0)
    started = threading.Event()

    def slow(*args, **kwargs):
        from morphostack.core.seeded_vesicle import TrackingCancelled

        started.set()
        cancel_check = kwargs.get("cancel_check")
        # Poll cancel (shutdown sets cancel + service flag) instead of blocking forever.
        deadline = time.time() + 10
        while time.time() < deadline:
            if cancel_check is not None and cancel_check():
                n = stack.shape[0]
                results = [
                    SeededSliceResult(
                        None, None, (32.0, 32.0), 0.0, 0.0, "circle_seed_unreached", False
                    )
                    for _ in range(n)
                ]
                raise TrackingCancelled(results, reached_low_z=0, reached_high_z=0)
            time.sleep(0.01)
        return track_seeded_vesicle_stack(*args, **kwargs)

    service._track_fn = slow  # type: ignore[method-assign]
    service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=0, seed_radius=14, target_z=9
    )
    assert started.wait(timeout=3)
    service.shutdown(timeout=5)
    assert service.live_worker_count() == 0
    assert service.active_job_count() == 0


def test_start_status_timing_budget(service: TrackingJobService):
    stack = _ring_stack(n=4)
    key = _key(gray_shape=stack.shape, seed_frame=0)
    release = threading.Event()
    started = threading.Event()

    def slow(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return track_seeded_vesicle_stack(*args, **kwargs)

    service._track_fn = slow  # type: ignore[method-assign]
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        snap = service.start(
            key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=0, seed_radius=14
        )
        times.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        service.status(snap.job_id)
        times.append(time.perf_counter() - t0)
    release.set()
    service.wait(snap.job_id, timeout=30)
    times_sorted = sorted(times)
    p95 = times_sorted[int(0.95 * (len(times_sorted) - 1))]
    assert p95 < 0.05, f"start/status p95 {p95:.4f}s exceeds 50ms"


def test_stale_job_cannot_write_after_supersede(service: TrackingJobService):
    stack = _ring_stack(n=6)
    key = _key(gray_shape=stack.shape, seed_frame=1)
    old_started = threading.Event()
    old_release = threading.Event()
    writes = {"old": 0, "new": 0}
    real = track_seeded_vesicle_stack
    phase = {"use_old": True}

    def controlled(*args, **kwargs):
        on_progress = kwargs.get("on_progress")
        if phase["use_old"]:
            old_started.set()
            assert old_release.wait(timeout=5)
            # Simulate cancel mid-flight after supersede.
            from morphostack.core.seeded_vesicle import TrackingCancelled

            n = stack.shape[0]
            results = [
                SeededSliceResult(
                    None, None, (32.0, 32.0), 0.0, 0.0, "circle_seed_unreached", False
                )
                for _ in range(n)
            ]
            # Poison payload that must not land if superseded.
            results[1] = SeededSliceResult(
                None, None, (1.0, 1.0), 999.0, 999.0, "circle_seed_poison", True
            )
            if on_progress is not None:
                # Try to progress-write (service should ignore if not owner).
                from morphostack.core.seeded_vesicle import TrackProgressEvent

                on_progress(
                    TrackProgressEvent(
                        frame_index=1,
                        result=results[1],
                        reached_low_z=1,
                        reached_high_z=1,
                        marker="partial",
                    )
                )
                writes["old"] += 1
            raise TrackingCancelled(results, reached_low_z=1, reached_high_z=1)
        return real(*args, **kwargs)

    service._track_fn = controlled  # type: ignore[method-assign]
    old = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=4
    )
    assert old_started.wait(timeout=3)
    # Capacity-1 + cancel ownership: start again same key after cancel.
    service.cancel(old.job_id)
    phase["use_old"] = False
    new = service.start(
        key=key, stack=stack, seed_x=32, seed_y=32, seed_frame=1, seed_radius=14, target_z=4
    )
    assert new.job_id != old.job_id
    old_release.set()
    service.wait(old.job_id, timeout=10)
    done = service.wait(new.job_id, timeout=60)
    assert done.state == "complete"
    cached = service.result_cache.get(key)
    assert cached is not None
    assert cached[1].method != "circle_seed_poison"


def test_api_tracking_job_lifecycle(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    stack = (_ring_stack(n=5, h=48, w=48) * 200).astype(np.uint8)
    path = tmp_path / "rings.tif"
    tifffile.imwrite(path, stack, photometric="minisblack")

    with TestClient(create_app()) as client:
        start = client.post(
            "/tracking/jobs/start",
            json={
                "path": str(path),
                "object_seed": {"x": 24, "y": 24, "frame_index": 1, "radius": 14},
                "target_z": 4,
                "profile": "vesicle",
            },
        )
        assert start.status_code == 200, start.text
        body = start.json()
        assert body["process_local"] is True
        job_id = body["job_id"]
        assert body["state"] in ("queued", "running", "partial", "complete")

        # Attach
        start2 = client.post(
            "/tracking/jobs/start",
            json={
                "path": str(path),
                "object_seed": {"x": 24, "y": 24, "frame_index": 1, "radius": 14},
                "target_z": 3,
                "profile": "vesicle",
            },
        )
        assert start2.status_code == 200
        assert start2.json()["job_id"] == job_id

        # Poll until terminal
        deadline = time.time() + 60
        state = body["state"]
        while state not in ("complete", "cancelled", "failed") and time.time() < deadline:
            time.sleep(0.05)
            st = client.get(f"/tracking/jobs/{job_id}")
            assert st.status_code == 200
            state = st.json()["state"]
        assert state == "complete"

        health = client.get("/health")
        assert health.json().get("tracking_jobs_process_local") is True


def test_api_cancel_endpoint(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    # Larger stack so cancel can race before complete.
    stack = (_ring_stack(n=20, h=64, w=64) * 200).astype(np.uint8)
    path = tmp_path / "long.tif"
    tifffile.imwrite(path, stack, photometric="minisblack")

    with TestClient(create_app()) as client:
        start = client.post(
            "/tracking/jobs/start",
            json={
                "path": str(path),
                "object_seed": {"x": 32, "y": 32, "frame_index": 0, "radius": 14},
                "target_z": 19,
            },
        )
        assert start.status_code == 200
        job_id = start.json()["job_id"]
        cancel = client.post(f"/tracking/jobs/{job_id}/cancel")
        assert cancel.status_code == 200
        # Wait for terminal
        deadline = time.time() + 30
        state = cancel.json()["state"]
        while state not in ("complete", "cancelled", "failed") and time.time() < deadline:
            time.sleep(0.05)
            state = client.get(f"/tracking/jobs/{job_id}").json()["state"]
        assert state == "cancelled"
