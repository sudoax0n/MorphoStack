"""Process-local single-flight authoritative seeded tracking jobs.

One running writer job per :class:`~morphostack.core.stack_cache.TrackingCacheKey`.
Duplicate starts attach and may reprioritize; they never launch a second science
walk for the same key. Progressive frames write through
:class:`~morphostack.core.stack_cache.TrackingResultCache`.

**Process-local limitation:** each API worker process has its own registry and
result cache. There is no cross-worker shared job bus. Scale-out must pin
sessions or accept per-worker isolation.

Packet 03: service + narrow API endpoints only. Exact preview HTTP remains the
synchronous diagnostic path until packet 04; do not run the sync writer and a
service job for the same key concurrently from the same client.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

import numpy as np

from morphostack.core.seeded_vesicle import (
    SeededSliceResult,
    TrackingCancelled,
    TrackProgressEvent,
    extend_track,
    frame_is_terminal_exact,
    furthest_accepted_frontier,
    is_tracking_instrumentation_enabled,
    record_tracking_observe_event,
    track_seeded_vesicle_stack,
)
from morphostack.core.stack_cache import (
    TrackingCacheKey,
    TrackingJobState,
    TrackingJobStateName,
    TrackingResultCache,
    tracking_key_revision,
)

# Conservative: one active authoritative track writer per process.
DEFAULT_MAX_ACTIVE_JOBS = 1
# Finished job snapshots retained for status lookup.
DEFAULT_MAX_RETAINED_JOBS = 32

_TERMINAL: frozenset[str] = frozenset({"complete", "cancelled", "failed"})
_ACTIVE: frozenset[str] = frozenset({"queued", "running", "partial"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unreached(seed_x: float, seed_y: float) -> SeededSliceResult:
    return SeededSliceResult(
        None, None, (float(seed_x), float(seed_y)), 0.0, 0.0, "circle_seed_unreached", False
    )


@dataclass(frozen=True)
class TrackingJobSnapshot:
    """Immutable public view of a job (safe to return across threads/API)."""

    job_id: str
    tracking_key_revision: str
    state: TrackingJobStateName
    requested_target_z: int | None
    direction_priority: int | None
    reached_low_z: int | None
    reached_high_z: int | None
    available_exact_frames: tuple[int, ...]
    started_at: str | None
    updated_at: str | None
    error_code: str | None = None
    message: str | None = None
    attached: bool = False  # True when start() attached to an existing job

    def to_job_state(self) -> TrackingJobState:
        return TrackingJobState(
            job_id=self.job_id,
            tracking_key_revision=self.tracking_key_revision,
            state=self.state,
            requested_target_z=self.requested_target_z,
            reached_low_z=self.reached_low_z,
            reached_high_z=self.reached_high_z,
            available_exact_frames=self.available_exact_frames,
            started_at=self.started_at,
            updated_at=self.updated_at,
            error_code=self.error_code,
            message=self.message,
        )

    def to_json_dict(self) -> dict[str, Any]:
        d = self.to_job_state().to_json_dict()
        d["direction_priority"] = self.direction_priority
        d["attached"] = bool(self.attached)
        return d


class _JobRecord:
    """Mutable internal job record (guarded by service lock for fields used by API)."""

    def __init__(
        self,
        *,
        job_id: str,
        key: TrackingCacheKey,
        stack: np.ndarray,
        seed_x: float,
        seed_y: float,
        seed_frame: int,
        seed_radius: float | None,
        requested_target_z: int | None,
        direction_priority: int | None,
    ) -> None:
        self.job_id = job_id
        self.key = key
        self.key_revision = tracking_key_revision(key)
        self.stack = np.asarray(stack)
        self.seed_x = float(seed_x)
        self.seed_y = float(seed_y)
        self.seed_frame = int(seed_frame)
        self.seed_radius = seed_radius
        self.n = int(self.stack.shape[0])

        self.state: TrackingJobStateName = "queued"
        self.requested_target_z = requested_target_z
        self.direction_priority = direction_priority
        self.reached_low_z: int | None = None
        self.reached_high_z: int | None = None
        self.available_exact_frames: set[int] = set()
        self.started_at: str | None = None
        self.updated_at: str | None = _utc_now_iso()
        self.error_code: str | None = None
        self.message: str | None = None

        self.cancel_flag = threading.Event()
        self.thread: threading.Thread | None = None
        # Generation / ownership: only the active owner may write cache/state.
        self.owner_token = uuid.uuid4().hex
        self._results: list[SeededSliceResult] | None = None
        # Test/sync hooks
        self.progress_barrier: threading.Event | None = None
        self.started_barrier: threading.Event | None = None

    def snapshot(self, *, attached: bool = False) -> TrackingJobSnapshot:
        return TrackingJobSnapshot(
            job_id=self.job_id,
            tracking_key_revision=self.key_revision,
            state=self.state,
            requested_target_z=self.requested_target_z,
            direction_priority=self.direction_priority,
            reached_low_z=self.reached_low_z,
            reached_high_z=self.reached_high_z,
            available_exact_frames=tuple(sorted(self.available_exact_frames)),
            started_at=self.started_at,
            updated_at=self.updated_at,
            error_code=self.error_code,
            message=self.message,
            attached=attached,
        )


class TrackingJobService:
    """Bounded single-flight registry for exact seeded tracking.

    Parameters
    ----------
    result_cache:
        Exact-frame cache (process-local). Default constructs a private cache;
        the API wires :data:`default_tracking_cache`.
    max_active_jobs:
        Max concurrent running writers (default 1).
    max_retained_jobs:
        Finished jobs kept for status-by-id (LRU by completion order).
    track_fn:
        Injectable full-walk science entry (tests). Defaults to
        :func:`~morphostack.core.seeded_vesicle.track_seeded_vesicle_stack`.
    extend_fn:
        Injectable frontier-extension entry (tests). Defaults to
        :func:`~morphostack.core.seeded_vesicle.extend_track`.
    """

    def __init__(
        self,
        *,
        result_cache: TrackingResultCache | None = None,
        max_active_jobs: int = DEFAULT_MAX_ACTIVE_JOBS,
        max_retained_jobs: int = DEFAULT_MAX_RETAINED_JOBS,
        track_fn: Callable[..., list[SeededSliceResult]] | None = None,
        extend_fn: Callable[..., list[SeededSliceResult]] | None = None,
    ) -> None:
        if max_active_jobs < 1:
            raise ValueError("max_active_jobs must be >= 1")
        if max_retained_jobs < 1:
            raise ValueError("max_retained_jobs must be >= 1")
        self._cache = result_cache if result_cache is not None else TrackingResultCache()
        self._max_active = int(max_active_jobs)
        self._max_retained = int(max_retained_jobs)
        self._track_fn = track_fn or track_seeded_vesicle_stack
        self._extend_fn = extend_fn or extend_track
        self._lock = threading.RLock()
        # key -> active (non-terminal) job
        self._active_by_key: dict[TrackingCacheKey, _JobRecord] = {}
        # job_id -> record (active + retained terminal)
        self._jobs: dict[str, _JobRecord] = {}
        # terminal retention order
        self._finished: OrderedDict[str, None] = OrderedDict()
        self._shutdown = False
        # Count science invocations for single-flight / frontier-reuse tests.
        self.track_invocations = 0
        self.extend_invocations = 0
        self._track_invocations_lock = threading.Lock()

    @property
    def result_cache(self) -> TrackingResultCache:
        return self._cache

    def start(
        self,
        *,
        key: TrackingCacheKey,
        stack: np.ndarray,
        seed_x: float,
        seed_y: float,
        seed_frame: int,
        seed_radius: float | None = None,
        target_z: int | None = None,
        direction_priority: int | None = None,
    ) -> TrackingJobSnapshot:
        """Start a job or attach to the existing active job for ``key``."""
        with self._lock:
            if self._shutdown:
                raise RuntimeError("tracking job service is shut down")
            existing = self._active_by_key.get(key)
            if existing is not None and existing.state in _ACTIVE:
                if target_z is not None:
                    existing.requested_target_z = int(target_z)
                if direction_priority is not None:
                    if direction_priority not in (-1, 1):
                        raise ValueError("direction_priority must be None, +1, or -1")
                    existing.direction_priority = int(direction_priority)
                existing.updated_at = _utc_now_iso()
                snap = existing.snapshot(attached=True)
                if is_tracking_instrumentation_enabled():
                    record_tracking_observe_event(
                        "job_start",
                        job_id=snap.job_id,
                        key_revision=snap.tracking_key_revision,
                        target_z=snap.requested_target_z,
                        direction_priority=snap.direction_priority,
                        attached=True,
                    )
                return snap

            # Capacity: cancel other active keys when at max (single-writer default).
            while len(self._active_by_key) >= self._max_active:
                # Prefer cancelling a different key; if only this key somehow stuck, break.
                victim_key = next(
                    (k for k in self._active_by_key if k != key),
                    next(iter(self._active_by_key), None),
                )
                if victim_key is None:
                    break
                victim = self._active_by_key[victim_key]
                self._request_cancel_unlocked(victim, reason="superseded_by_capacity")

            if direction_priority is not None and direction_priority not in (-1, 1):
                raise ValueError("direction_priority must be None, +1, or -1")

            job = _JobRecord(
                job_id=uuid.uuid4().hex,
                key=key,
                stack=stack,
                seed_x=seed_x,
                seed_y=seed_y,
                seed_frame=seed_frame,
                seed_radius=seed_radius,
                requested_target_z=int(target_z) if target_z is not None else None,
                direction_priority=int(direction_priority) if direction_priority is not None else None,
            )
            self._jobs[job.job_id] = job
            self._active_by_key[key] = job
            thread = threading.Thread(
                target=self._run_job,
                args=(job,),
                name=f"tracking-job-{job.job_id[:8]}",
                daemon=True,
            )
            job.thread = thread
            thread.start()
            snap = job.snapshot(attached=False)
            if is_tracking_instrumentation_enabled():
                record_tracking_observe_event(
                    "job_start",
                    job_id=snap.job_id,
                    key_revision=snap.tracking_key_revision,
                    target_z=snap.requested_target_z,
                    direction_priority=snap.direction_priority,
                    attached=False,
                )
            return snap

    def reprioritize(
        self,
        job_id: str,
        *,
        target_z: int | None = None,
        direction_priority: int | None = None,
    ) -> TrackingJobSnapshot:
        with self._lock:
            job = self._require_job(job_id)
            if job.state in _TERMINAL:
                return job.snapshot()
            if target_z is not None:
                job.requested_target_z = int(target_z)
            if direction_priority is not None:
                if direction_priority not in (-1, 1):
                    raise ValueError("direction_priority must be None, +1, or -1")
                job.direction_priority = int(direction_priority)
            job.updated_at = _utc_now_iso()
            snap = job.snapshot()
        if is_tracking_instrumentation_enabled():
            record_tracking_observe_event(
                "job_reprioritize",
                job_id=snap.job_id,
                key_revision=snap.tracking_key_revision,
                target_z=snap.requested_target_z,
                direction_priority=snap.direction_priority,
            )
        return snap

    def cancel(self, job_id: str) -> TrackingJobSnapshot:
        with self._lock:
            job = self._require_job(job_id)
            self._request_cancel_unlocked(job, reason="cancelled_by_client")
            return job.snapshot()

    def status(self, job_id: str) -> TrackingJobSnapshot:
        with self._lock:
            return self._require_job(job_id).snapshot()

    def status_for_key(self, key: TrackingCacheKey) -> TrackingJobSnapshot | None:
        with self._lock:
            job = self._active_by_key.get(key)
            if job is None:
                return None
            return job.snapshot()

    def wait(self, job_id: str, timeout: float | None = None) -> TrackingJobSnapshot:
        """Block until the job reaches a terminal state (tests/diagnostics)."""
        with self._lock:
            job = self._require_job(job_id)
            thread = job.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            return self._require_job(job_id).snapshot()

    def active_job_count(self) -> int:
        with self._lock:
            return len(self._active_by_key)

    def live_worker_count(self) -> int:
        with self._lock:
            n = 0
            for job in self._jobs.values():
                if job.thread is not None and job.thread.is_alive():
                    n += 1
            return n

    def shutdown(self, *, timeout: float = 30.0) -> None:
        """Cancel all active jobs and join workers. Idempotent."""
        with self._lock:
            self._shutdown = True
            jobs = list(self._active_by_key.values())
            for job in jobs:
                self._request_cancel_unlocked(job, reason="service_shutdown")
            threads = [(j.job_id, j.thread) for j in self._jobs.values() if j.thread is not None]
        for _jid, th in threads:
            if th is not None and th.is_alive():
                th.join(timeout=timeout)
        with self._lock:
            # Drop active map; terminal states already retained.
            self._active_by_key.clear()

    def _require_job(self, job_id: str) -> _JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"unknown tracking job_id: {job_id}")
        return job

    def _request_cancel_unlocked(self, job: _JobRecord, *, reason: str) -> None:
        job.cancel_flag.set()
        job.updated_at = _utc_now_iso()
        if job.state in _TERMINAL:
            return
        # Release active ownership immediately so a new writer may take the key;
        # the worker must not write cache after this (_still_owner fails).
        if self._active_by_key.get(job.key) is job:
            del self._active_by_key[job.key]
        # Do not mark cancelled until worker acknowledges (unless never started).
        if job.state == "queued" and (job.thread is None or not job.thread.is_alive()):
            job.state = "cancelled"
            job.error_code = "cancelled"
            job.message = reason
            self._retain_finished_unlocked(job)

    def _retain_finished_unlocked(self, job: _JobRecord) -> None:
        """LRU-retain a terminal job id (caller holds lock)."""
        self._finished[job.job_id] = None
        self._finished.move_to_end(job.job_id)
        while len(self._finished) > self._max_retained:
            old_id, _ = self._finished.popitem(last=False)
            old = self._jobs.get(old_id)
            if old is not None and old.state in _TERMINAL and self._active_by_key.get(old.key) is not old:
                self._jobs.pop(old_id, None)

    def _still_owner(self, job: _JobRecord) -> bool:
        active = self._active_by_key.get(job.key)
        return active is job and not self._shutdown

    def _finalize_unlocked(self, job: _JobRecord) -> None:
        """Drop active ownership (if any) and LRU-retain the terminal job."""
        cur = self._active_by_key.get(job.key)
        if cur is job:
            del self._active_by_key[job.key]
        self._retain_finished_unlocked(job)

    def _run_job(self, job: _JobRecord) -> None:
        owner = job.owner_token
        try:
            with self._lock:
                if job.cancel_flag.is_set():
                    job.state = "cancelled"
                    job.error_code = "cancelled"
                    job.message = "cancelled_before_start"
                    job.updated_at = _utc_now_iso()
                    self._finalize_unlocked(job)
                    return
                job.state = "running"
                job.started_at = _utc_now_iso()
                job.updated_at = job.started_at
                if job.started_barrier is not None:
                    job.started_barrier.set()

            def cancel_check() -> bool:
                return job.cancel_flag.is_set() or self._shutdown

            def on_progress(ev: TrackProgressEvent) -> None:
                with self._lock:
                    if not self._still_owner(job) or job.owner_token != owner:
                        return
                    if job._results is None:
                        job._results = [
                            _unreached(job.seed_x, job.seed_y) for _ in range(job.n)
                        ]
                    # Store progress result (shares buffers; frozen fields).
                    job._results[int(ev.frame_index)] = ev.result
                    job.available_exact_frames.add(int(ev.frame_index))
                    job.reached_low_z = int(ev.reached_low_z)
                    job.reached_high_z = int(ev.reached_high_z)
                    if ev.marker == "complete":
                        job.state = "partial"  # final put happens after return
                    else:
                        job.state = "partial"
                    job.updated_at = _utc_now_iso()
                    # Progressive write-through (owner only).
                    self._cache.merge(job.key, list(job._results))
                if job.progress_barrier is not None:
                    job.progress_barrier.set()

            # Live scheduling: re-read at each safe Z boundary inside the tracker.
            def live_direction_priority() -> int | None:
                with self._lock:
                    explicit = job.direction_priority
                    target = job.requested_target_z
                if explicit in (-1, 1):
                    return int(explicit)
                # Prefer the frontier toward the currently requested target Z.
                if target is not None:
                    if int(target) > job.seed_frame:
                        return 1
                    if int(target) < job.seed_frame:
                        return -1
                return None

            def live_target_frame() -> int | None:
                with self._lock:
                    t = job.requested_target_z
                return int(t) if t is not None else None

            # Packet 03: reuse exact cache frontiers — same-direction work extends
            # from the closest accepted frame; opposite-side accepts are preserved
            # via merge (never terminal put of unidirectional unreached placeholders).
            cached = self._cache.get(job.key)
            with self._lock:
                initial_target = job.requested_target_z

            if (
                cached is not None
                and initial_target is not None
                and 0 <= int(initial_target) < job.n
                and frame_is_terminal_exact(cached[int(initial_target)])
            ):
                # Target already exact — complete without resegmenting.
                out = list(cached)
                with self._lock:
                    if job.owner_token != owner:
                        return
                    if not self._still_owner(job):
                        if job.state not in _TERMINAL:
                            job.state = "cancelled"
                            job.error_code = "cancelled"
                            job.message = "cancelled_or_superseded"
                            job.updated_at = _utc_now_iso()
                            self._retain_finished_unlocked(job)
                        return
                    job._results = out
                    job.available_exact_frames = {
                        i
                        for i, r in enumerate(out)
                        if r is not None and r.method != "circle_seed_unreached"
                    }
                    committed = sorted(job.available_exact_frames)
                    if committed:
                        job.reached_low_z = committed[0]
                        job.reached_high_z = committed[-1]
                    job.state = "complete"
                    job.updated_at = _utc_now_iso()
                    self._cache.merge(job.key, list(out))
                    self._finalize_unlocked(job)
                    if is_tracking_instrumentation_enabled():
                        record_tracking_observe_event(
                            "job_complete",
                            job_id=job.job_id,
                            key_revision=tracking_key_revision(job.key),
                            state="complete",
                            reached_low_z=job.reached_low_z,
                            reached_high_z=job.reached_high_z,
                            available_exact_frames=sorted(job.available_exact_frames),
                            reused_cache=True,
                        )
                return

            use_extend = False
            if cached is not None and initial_target is not None:
                direction = 1 if int(initial_target) > job.seed_frame else -1
                frontier = furthest_accepted_frontier(
                    cached, seed_frame=job.seed_frame, direction=direction
                )
                if frontier is not None:
                    # Extensible when the frontier has not yet reached the target.
                    if (direction > 0 and frontier < int(initial_target)) or (
                        direction < 0 and frontier > int(initial_target)
                    ):
                        use_extend = True
                    elif (direction > 0 and frontier >= int(initial_target)) or (
                        direction < 0 and frontier <= int(initial_target)
                    ):
                        # Accepted path already covers target (target may be gap).
                        use_extend = True

            from morphostack.core.seeded_vesicle import competitive_from_tracking_mode

            job_competitive = competitive_from_tracking_mode(job.key.tracking_mode)

            if use_extend and cached is not None:
                with self._track_invocations_lock:
                    self.extend_invocations += 1
                    self.track_invocations += 1
                out = self._extend_fn(
                    job.stack,
                    seed_x=job.seed_x,
                    seed_y=job.seed_y,
                    seed_frame=job.seed_frame,
                    seed_radius=job.seed_radius,
                    target_frame=live_target_frame,
                    cached_results=cached,
                    on_progress=on_progress,
                    cancel_check=cancel_check,
                    direction_priority=live_direction_priority,
                    competitive_isolation=job_competitive,
                )
            else:
                with self._track_invocations_lock:
                    self.track_invocations += 1
                # If a target Z is (or becomes) set, walk that direction with a live
                # stop; otherwise full bidirectional with live direction priority.
                if initial_target is not None:
                    out = self._track_fn(
                        job.stack,
                        seed_x=job.seed_x,
                        seed_y=job.seed_y,
                        seed_frame=job.seed_frame,
                        seed_radius=job.seed_radius,
                        target_frame=live_target_frame,
                        on_progress=on_progress,
                        cancel_check=cancel_check,
                        direction_priority=live_direction_priority,
                        competitive_isolation=job_competitive,
                    )
                else:
                    out = self._track_fn(
                        job.stack,
                        seed_x=job.seed_x,
                        seed_y=job.seed_y,
                        seed_frame=job.seed_frame,
                        seed_radius=job.seed_radius,
                        target_frame=None,
                        on_progress=on_progress,
                        cancel_check=cancel_check,
                        direction_priority=live_direction_priority,
                        competitive_isolation=job_competitive,
                    )
            with self._lock:
                # Successful science return: mark complete only if we still own the key.
                # A superseded/cancelled job that lost ownership must not complete.
                if job.owner_token != owner:
                    return
                if not self._still_owner(job):
                    # Ownership released by cancel/supersede — never mark complete.
                    if job.state not in _TERMINAL:
                        job.state = "cancelled"
                        job.error_code = "cancelled"
                        job.message = "cancelled_or_superseded"
                        job.updated_at = _utc_now_iso()
                        self._retain_finished_unlocked(job)
                    return
                job._results = list(out)
                job.available_exact_frames = {
                    i
                    for i, r in enumerate(out)
                    if r is not None and r.method != "circle_seed_unreached"
                }
                committed = sorted(job.available_exact_frames)
                if committed:
                    job.reached_low_z = committed[0]
                    job.reached_high_z = committed[-1]
                job.state = "complete"
                job.updated_at = _utc_now_iso()
                # Merge — never put — so opposite-side accepted frames survive.
                self._cache.merge(job.key, list(out))
                self._finalize_unlocked(job)
                if is_tracking_instrumentation_enabled():
                    record_tracking_observe_event(
                        "job_complete",
                        job_id=job.job_id,
                        key_revision=tracking_key_revision(job.key),
                        state="complete",
                        reached_low_z=job.reached_low_z,
                        reached_high_z=job.reached_high_z,
                        available_exact_frames=sorted(job.available_exact_frames),
                    )
        except TrackingCancelled as exc:
            with self._lock:
                if job.owner_token != owner:
                    return
                job._results = list(exc.results)
                job.reached_low_z = int(exc.reached_low_z)
                job.reached_high_z = int(exc.reached_high_z)
                job.available_exact_frames = {
                    i
                    for i, r in enumerate(exc.results)
                    if r.method != "circle_seed_unreached"
                }
                job.state = "cancelled"
                job.error_code = "cancelled"
                job.message = str(exc) or "cancelled"
                job.updated_at = _utc_now_iso()
                # Partial only when still the cache owner; superseded jobs skip write.
                if self._still_owner(job) or self._active_by_key.get(job.key) is None:
                    # If we already released ownership on cancel request, still allow
                    # this job's partial merge only when no newer owner holds the key.
                    newer = self._active_by_key.get(job.key)
                    if newer is None or newer is job:
                        self._cache.merge(job.key, list(exc.results))
                self._finalize_unlocked(job)
        except Exception as exc:
            with self._lock:
                if job.owner_token != owner:
                    return
                job.state = "failed"
                job.error_code = type(exc).__name__
                job.message = str(exc) or type(exc).__name__
                tb = traceback.format_exc(limit=6)
                if len(tb) < 800:
                    job.message = f"{job.message}\n{tb}"
                job.updated_at = _utc_now_iso()
                # Keep any progressive partials already merged; do not mark complete.
                self._finalize_unlocked(job)


# ---------------------------------------------------------------------------
# Process-level default for the FastAPI app (replaced on create_app lifespan).
# ---------------------------------------------------------------------------

_default_service: TrackingJobService | None = None
_default_service_lock = threading.Lock()


def get_tracking_job_service() -> TrackingJobService:
    """Return the process default service, creating a lazy instance if needed."""
    global _default_service
    with _default_service_lock:
        if _default_service is None:
            from morphostack.core.stack_cache import default_tracking_cache

            _default_service = TrackingJobService(result_cache=default_tracking_cache)
        return _default_service


def set_tracking_job_service(service: TrackingJobService | None) -> None:
    """Install or clear the process default service (app lifespan / tests)."""
    global _default_service
    with _default_service_lock:
        _default_service = service


def shutdown_tracking_job_service(*, timeout: float = 30.0) -> None:
    global _default_service
    with _default_service_lock:
        svc = _default_service
        _default_service = None
    if svc is not None:
        svc.shutdown(timeout=timeout)
