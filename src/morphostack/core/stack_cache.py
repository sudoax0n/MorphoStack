"""Process-local LRU cache for loaded image stacks.

Avoids re-decoding large CZI/TIFF files on every /preview, /threshold, and
related path-based API call within the same process.

Also holds **upload sessions**: one decode of a browser-uploaded stack under a
``stack_id``, so subsequent preview/mesh/analyze calls skip re-upload.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass, fields, replace
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from morphostack.core.io import load_image_stack
from morphostack.core.models import ImageStack, VoxelSize
from morphostack.core.profiles import DEFAULT_PROFILE, normalize_profile

if TYPE_CHECKING:
    from morphostack.core.seeded_vesicle import SeededSliceResult

_DEFAULT_MAX_ENTRIES = 3
_DEFAULT_SESSION_MAX_ENTRIES = 3
_DEFAULT_TRACKING_MAX_ENTRIES = 8

TrackingJobStateName = Literal[
    "queued",
    "running",
    "partial",
    "complete",
    "cancelled",
    "failed",
]
TRACKING_JOB_STATES: tuple[TrackingJobStateName, ...] = (
    "queued",
    "running",
    "partial",
    "complete",
    "cancelled",
    "failed",
)


def _voxel_key(voxel: VoxelSize | None) -> tuple[float, float, float] | None:
    if voxel is None:
        return None
    return (float(voxel.x_um), float(voxel.y_um), float(voxel.z_um))


def _file_signature(path: Path) -> tuple[int, int]:
    """Return (mtime_ns, size) for invalidation; (0, 0) if unreadable."""
    try:
        stat = path.stat()
        mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
        return int(mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


class StackCache:
    """Thread-safe LRU of ``ImageStack`` keyed by absolute path + voxel override."""

    def __init__(self, *, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max_entries = int(max_entries)
        self._lock = Lock()
        # key -> (stack, mtime_ns, size)
        self._entries: OrderedDict[tuple[Any, ...], tuple[ImageStack, int, int]] = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(
        self,
        path: str | Path,
        *,
        voxel_override: VoxelSize | None = None,
    ) -> ImageStack:
        file_path = Path(path).resolve()
        key = (str(file_path), _voxel_key(voxel_override))
        mtime_ns, size = _file_signature(file_path)

        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                stack, cached_mtime, cached_size = cached
                if cached_mtime == mtime_ns and cached_size == size:
                    self._entries.move_to_end(key)
                    return stack
                del self._entries[key]

        stack = load_image_stack(file_path, voxel_override=voxel_override)

        with self._lock:
            self._entries[key] = (stack, mtime_ns, size)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return stack


@dataclass(frozen=True)
class SessionStackEntry:
    """In-memory upload session: decoded stack + display metadata."""

    stack: ImageStack
    source_name: str
    source_sha256: str = ""


class SessionStackStore:
    """Thread-safe LRU of upload sessions keyed by ``stack_id`` (UUID string).

    Keeps grayscale ``ImageStack`` in process memory so browser file-mode clients
    upload once and call preview/mesh/analyze with ``stack_id`` only.
    """

    def __init__(self, *, max_entries: int = _DEFAULT_SESSION_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max_entries = int(max_entries)
        self._lock = Lock()
        self._entries: OrderedDict[str, SessionStackEntry] = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def put(
        self,
        stack: ImageStack,
        *,
        source_name: str,
        source_sha256: str = "",
    ) -> str:
        """Store ``stack`` under a new ``stack_id`` and return that id."""
        name = source_name.strip() or "upload"
        # Prefer a stable display path (original filename) over a deleted temp path.
        display_stack = replace(stack, source_path=Path(name))
        stack_id = str(uuid4())
        entry = SessionStackEntry(
            stack=display_stack,
            source_name=name,
            source_sha256=source_sha256,
        )
        with self._lock:
            self._entries[stack_id] = entry
            self._entries.move_to_end(stack_id)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return stack_id

    def get(self, stack_id: str) -> SessionStackEntry:
        """Return session entry; raises ``KeyError`` if missing/expired."""
        key = (stack_id or "").strip()
        if not key:
            raise KeyError("empty stack_id")
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise KeyError(key)
            self._entries.move_to_end(key)
            return entry


# Seed coordinates/radius are canonicalized to 6 decimal places — finer than
# any UI selector (sub-pixel click/drag) while remaining stable across JSON
# round-trips. Integer rounding is intentionally NOT used: 32.10 vs 32.49 must
# not share a tracking cache entry.
_SEED_COORD_DECIMALS = 6


def canonicalize_seed_coord(value: float) -> float:
    """Stable seed coordinate for cache keys (not pixel-rounded)."""
    return round(float(value), _SEED_COORD_DECIMALS)


def path_source_identity(path: str | Path) -> str:
    """Cheap path + file revision identity for tracking cache keys.

    Uses resolved path with ``st_mtime_ns`` and size — not a full content hash —
    so preview scrubbing stays fast while file replacement invalidates cache.

    Canonical identity shared with :class:`~morphostack.core.volume_source.StackRevision`
    for path-backed volumes — do not invent a second path revision scheme.
    """
    file_path = Path(path).resolve()
    mtime_ns, size = _file_signature(file_path)
    return f"path:{file_path}|m{mtime_ns}|s{size}"


def session_source_identity(stack_id: str) -> str:
    """Canonical session stack identity (``session:{stack_id}``)."""

    key = (stack_id or "").strip()
    if not key:
        raise ValueError("stack_id is required")
    return f"session:{key}"


@dataclass(frozen=True)
class TrackingCacheKey:
    """Identity for a seeded exact tracking chain.

    Scoped so a cached track is never reused across a different source,
    seed, ROI/crop, Z-range, spatial stack shape, profile, exact tracking
    mode, or algorithm version. Intentionally omits the UI threshold: the
    exact seeded tracker uses adaptive local thresholds, not the preview
    slider value.
    """

    stack_identity: str  # session id, or path+revision (never sparse upload hash)
    seed_x: float  # canonical local seed X (after ROI offset)
    seed_y: float  # canonical local seed Y (after ROI offset)
    seed_frame: int  # local seed frame index (after Z offset)
    seed_radius: float  # canonical radius (not integer-rounded)
    shape_z: int  # gray volume depth used for tracking
    shape_y: int
    shape_x: int
    profile: str  # vesicle | rbc | active_surfaces
    tracking_mode: str  # exact mode token (e.g. seeded_exact)
    algorithm_version: str  # EXACT_TRACKING_ALGORITHM_VERSION
    roi_xmin: int | None = None
    roi_xmax: int | None = None
    roi_ymin: int | None = None
    roi_ymax: int | None = None
    zmin: int | None = None
    zmax: int | None = None


def _default_exact_tracking_mode() -> str:
    from morphostack.core.seeded_vesicle import EXACT_TRACKING_MODE

    return str(EXACT_TRACKING_MODE)


def _default_exact_algorithm_version() -> str:
    from morphostack.core.seeded_vesicle import EXACT_TRACKING_ALGORITHM_VERSION

    return str(EXACT_TRACKING_ALGORITHM_VERSION)


def make_tracking_cache_key(
    *,
    stack_identity: str,
    seed_x: float,
    seed_y: float,
    seed_frame: int,
    seed_radius: float,
    gray_shape: tuple[int, ...],
    roi: object | None = None,
    z_range: object | None = None,
    profile: str | None = None,
    tracking_mode: str | None = None,
    algorithm_version: str | None = None,
) -> TrackingCacheKey:
    """Build a :class:`TrackingCacheKey` from request/source spatial context.

    ``gray_shape`` must be the ``(z, y, x)`` volume actually passed to the
    tracker (after ROI crop and Z-range slicing). ROI/Z bounds are taken from
    the original request so two crops that happen to share a local seed and
    shape still cannot collide. Seed x/y/radius keep sub-pixel precision
    (see :func:`canonicalize_seed_coord`).

    ``profile``, ``tracking_mode``, and ``algorithm_version`` are always
    filled from canonical defaults when omitted so callers cannot silently
    drop scientific identity fields. Requested UI threshold is never a field.
    """
    if len(gray_shape) < 3:
        raise ValueError("gray_shape must be (z, y, x)")
    roi_xmin = roi_xmax = roi_ymin = roi_ymax = None
    if roi is not None:
        roi_xmin = int(getattr(roi, "xmin"))
        roi_xmax = int(getattr(roi, "xmax"))
        roi_ymin = int(getattr(roi, "ymin"))
        roi_ymax = int(getattr(roi, "ymax"))
    zmin = zmax = None
    if z_range is not None:
        zmin = int(getattr(z_range, "zmin"))
        zmax = int(getattr(z_range, "zmax"))
    mode = (tracking_mode or "").strip() or _default_exact_tracking_mode()
    version = (algorithm_version or "").strip() or _default_exact_algorithm_version()
    return TrackingCacheKey(
        stack_identity=str(stack_identity),
        seed_x=canonicalize_seed_coord(seed_x),
        seed_y=canonicalize_seed_coord(seed_y),
        seed_frame=int(seed_frame),
        seed_radius=canonicalize_seed_coord(seed_radius),
        shape_z=int(gray_shape[0]),
        shape_y=int(gray_shape[1]),
        shape_x=int(gray_shape[2]),
        profile=normalize_profile(profile if profile is not None else DEFAULT_PROFILE),
        tracking_mode=str(mode),
        algorithm_version=str(version),
        roi_xmin=roi_xmin,
        roi_xmax=roi_xmax,
        roi_ymin=roi_ymin,
        roi_ymax=roi_ymax,
        zmin=zmin,
        zmax=zmax,
    )


def tracking_key_revision(key: TrackingCacheKey) -> str:
    """Stable short digest of a :class:`TrackingCacheKey` (no full-file hash)."""
    payload = json.dumps(
        {f.name: getattr(key, f.name) for f in fields(key)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _json_safe_scalar(value: Any) -> Any:
    """Coerce job-state scalars for JSON (no NaN/Infinity)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return float(value)
    if isinstance(value, str):
        return value
    return value


@dataclass(frozen=True)
class TrackingJobState:
    """Serializable exact-tracking job lifecycle contract (no service yet).

    Progressive frames and single-flight execution land in later packets; this
    type is the shared state schema for job status payloads.
    """

    job_id: str
    tracking_key_revision: str
    state: TrackingJobStateName
    requested_target_z: int | None
    reached_low_z: int | None
    reached_high_z: int | None
    available_exact_frames: tuple[int, ...]
    started_at: str | None
    updated_at: str | None
    error_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.state not in TRACKING_JOB_STATES:
            raise ValueError(f"invalid tracking job state: {self.state!r}")
        # Normalize frames to a sorted unique tuple for equality stability.
        frames = tuple(sorted({int(z) for z in self.available_exact_frames}))
        object.__setattr__(self, "available_exact_frames", frames)

    def to_json_dict(self) -> dict[str, Any]:
        """JSON-safe dict: no NaN/Infinity; frames as a list."""
        return {
            "job_id": str(self.job_id),
            "tracking_key_revision": str(self.tracking_key_revision),
            "state": str(self.state),
            "requested_target_z": _json_safe_scalar(self.requested_target_z),
            "reached_low_z": _json_safe_scalar(self.reached_low_z),
            "reached_high_z": _json_safe_scalar(self.reached_high_z),
            "available_exact_frames": [int(z) for z in self.available_exact_frames],
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error_code": self.error_code,
            "message": self.message,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> TrackingJobState:
        """Reconstruct from :meth:`to_json_dict` (or equivalent API payload)."""
        state = str(data.get("state", "")).strip()
        if state not in TRACKING_JOB_STATES:
            raise ValueError(f"invalid tracking job state: {state!r}")
        raw_frames = data.get("available_exact_frames") or ()
        frames = tuple(int(z) for z in raw_frames)
        return cls(
            job_id=str(data["job_id"]),
            tracking_key_revision=str(data["tracking_key_revision"]),
            state=state,  # type: ignore[arg-type]
            requested_target_z=_optional_int(data.get("requested_target_z")),
            reached_low_z=_optional_int(data.get("reached_low_z")),
            reached_high_z=_optional_int(data.get("reached_high_z")),
            available_exact_frames=frames,
            started_at=_optional_str(data.get("started_at")),
            updated_at=_optional_str(data.get("updated_at")),
            error_code=_optional_str(data.get("error_code")),
            message=_optional_str(data.get("message")),
        )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


class TrackingResultCache:
    """LRU cache for exact ``SeededSliceResult`` lists from seeded Z tracking.

    Keyed by the full :class:`TrackingCacheKey` (source revision, seed, ROI/Z,
    shape, profile, exact mode, algorithm version). Stores only exact/committed
    results — never provisional one-plane overlays. Indexed by local frame.
    """

    def __init__(self, maxsize: int = _DEFAULT_TRACKING_MAX_ENTRIES) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self._maxsize = int(maxsize)
        self._lock = Lock()
        self._entries: OrderedDict[TrackingCacheKey, list[Any]] = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, key: TrackingCacheKey) -> list[SeededSliceResult] | None:
        with self._lock:
            cached = self._entries.get(key)
            if cached is None:
                return None
            self._entries.move_to_end(key)
            # Return a shallow copy so callers can merge without mutating the
            # live cache entry under the lock.
            return list(cached)

    def put(self, key: TrackingCacheKey, results: list[SeededSliceResult]) -> None:
        with self._lock:
            self._entries[key] = list(results)
            self._entries.move_to_end(key)
            while len(self._entries) > self._maxsize:
                self._entries.popitem(last=False)

    def merge(self, key: TrackingCacheKey, results: list[SeededSliceResult]) -> None:
        """Merge new results into an existing entry — keep best (ok=True) per frame."""
        with self._lock:
            existing = self._entries.get(key)
            if existing is None:
                merged = list(results)
            else:
                n = max(len(existing), len(results))
                merged = []
                for i in range(n):
                    old = existing[i] if i < len(existing) else None
                    new = results[i] if i < len(results) else None
                    if old is None:
                        merged.append(new)
                    elif new is None:
                        merged.append(old)
                    elif getattr(old, "ok", False) and not getattr(new, "ok", False):
                        merged.append(old)
                    else:
                        # Prefer new when both ok or old failed (fresher track).
                        merged.append(new if new is not None else old)
            self._entries[key] = merged
            self._entries.move_to_end(key)
            while len(self._entries) > self._maxsize:
                self._entries.popitem(last=False)


# Process-wide defaults used by the API layer.
default_stack_cache = StackCache(max_entries=_DEFAULT_MAX_ENTRIES)
default_session_store = SessionStackStore(max_entries=_DEFAULT_SESSION_MAX_ENTRIES)
default_tracking_cache = TrackingResultCache(maxsize=_DEFAULT_TRACKING_MAX_ENTRIES)


def cached_load_image_stack(
    path: str | Path,
    *,
    voxel_override: VoxelSize | None = None,
    cache: StackCache | None = None,
) -> ImageStack:
    """Load an image stack via ``cache`` (defaults to the process-global cache)."""
    active = cache if cache is not None else default_stack_cache
    return active.get(path, voxel_override=voxel_override)
