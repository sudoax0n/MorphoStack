"""Derived multiresolution **display** pyramid (Milestone B packet 11).

Display-only artifact. Lower levels must never feed scientific metrics
(:class:`~morphostack.core.models.DisplayVolumeSpec` / authority gates).

## Storage decision (recorded)

**Chosen:** bounded internal local cache (one ``.npy`` file per level + JSON
manifest/state), schema ``morphostack_display_pyramid/1``.

**Rejected for this packet:** OME-NGFF/Zarr — ``zarr`` / ``numcodecs`` are not
declared in ``pyproject.toml`` and are not installed in the environment. Packet
rules forbid installing undeclared dependencies without user approval. The same
:class:`DisplayPyramid` interface can later gain a Zarr backend once a concrete
NGFF/Zarr version is pinned and Windows benchmarks pass.

Lossless per-level storage uses NumPy ``.npy`` (no lossy codec). Downsampling
uses explicit mean-pool (values change by design; scales recorded).
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

import numpy as np

from morphostack.core.models import DisplayVolumeSpec, ResultAuthorityError, VoxelSize, reject_non_scientific_input
from morphostack.core.volume_source import StackRevision, VolumeSource

PyramidState = Literal["queued", "running", "partial", "complete", "failed"]

PYRAMID_ALGORITHM_VERSION = "1"
CACHE_FORMAT_VERSION = "1"
CACHE_SCHEMA = "morphostack_display_pyramid"
DOWNSAMPLE_KERNEL = "mean_pool"
STORAGE_BACKEND = "internal_npy_v1"
DEFAULT_MAX_LEVELS = 4
DEFAULT_SCALE_FACTOR = 2
DEFAULT_MAX_LEVEL_BYTES = 8 * 1024 * 1024  # transfer/GPU bound for one level
DEFAULT_MAX_SOURCE_BYTES = 256 * 1024 * 1024
# Process store bounds (retention + concurrency)
DEFAULT_MAX_CACHE_ENTRIES = 8
DEFAULT_MAX_CACHE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_ACTIVE_BUILDS = 2


def default_cache_root() -> Path:
    """Process-local default cache directory (disposable)."""

    env = os.environ.get("MORPHOSTACK_DISPLAY_PYRAMID_CACHE", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".morphostack" / "display_pyramid_cache"


# ---------------------------------------------------------------------------
# Config / key / manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PyramidConfig:
    """Build configuration baked into the cache key."""

    max_levels: int = DEFAULT_MAX_LEVELS
    scale_factor: int = DEFAULT_SCALE_FACTOR
    max_level_bytes: int = DEFAULT_MAX_LEVEL_BYTES
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    downsample_kernel: str = DOWNSAMPLE_KERNEL
    algorithm_version: str = PYRAMID_ALGORITHM_VERSION
    cache_format_version: str = CACHE_FORMAT_VERSION
    storage_backend: str = STORAGE_BACKEND

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_levels": int(self.max_levels),
            "scale_factor": int(self.scale_factor),
            "max_level_bytes": int(self.max_level_bytes),
            "max_source_bytes": int(self.max_source_bytes),
            "downsample_kernel": self.downsample_kernel,
            "algorithm_version": self.algorithm_version,
            "cache_format_version": self.cache_format_version,
            "storage_backend": self.storage_backend,
            "cache_schema": CACHE_SCHEMA,
        }


@dataclass(frozen=True)
class LevelDescriptor:
    level: int
    shape: tuple[int, int, int]
    dtype: str
    axes: str
    scale_zyx: tuple[float, float, float]  # relative to level-0 science voxels
    voxel_size: VoxelSize
    nbytes: int
    display_only: bool
    downsample_from_source: tuple[int, int, int]  # integer factors vs source

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": int(self.level),
            "shape": list(self.shape),
            "dtype": self.dtype,
            "axes": self.axes,
            "scale_zyx": list(self.scale_zyx),
            "voxel_size": self.voxel_size.to_dict(),
            "nbytes": int(self.nbytes),
            "display_only": bool(self.display_only),
            "downsample_from_source": list(self.downsample_from_source),
        }

    def as_display_volume_spec(self, *, source_revision: str | None) -> DisplayVolumeSpec:
        return DisplayVolumeSpec(
            source_revision=source_revision,
            level=self.level,
            shape=self.shape,
            dtype=self.dtype,
            axes=self.axes.lower(),
            level_voxel_size=self.voxel_size,
            downsampling={
                "kernel": DOWNSAMPLE_KERNEL,
                "factors_zyx": list(self.downsample_from_source),
                "scale_zyx": list(self.scale_zyx),
                "display_only": True,
            },
            display_only=True,
        )


def pyramid_cache_key(
    revision: StackRevision,
    *,
    source_axes: str,
    source_dtype: str,
    voxel_size: VoxelSize,
    voxel_source: str,
    config: PyramidConfig,
) -> str:
    """Deterministic cache key (hex). Same source+config → same key."""

    payload = {
        "schema": CACHE_SCHEMA,
        "cache_format_version": config.cache_format_version,
        "algorithm_version": config.algorithm_version,
        "storage_backend": config.storage_backend,
        "source_revision": revision.identity,
        "source_kind": revision.kind,
        "source_axes": source_axes,
        "source_dtype": str(source_dtype),
        "voxel_size": voxel_size.to_dict(),
        "voxel_source": voxel_source,
        "downsample_kernel": config.downsample_kernel,
        "scale_factor": int(config.scale_factor),
        "max_levels": int(config.max_levels),
        # Transfer budget affects which levels exist / selection, not identity of
        # stored levels for a given max_levels plan — still include for safety.
        "max_level_bytes": int(config.max_level_bytes),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _atomic_replace(tmp: Path, path: Path, *, attempts: int = 12, delay_s: float = 0.05) -> None:
    """``os.replace`` with short retries for Windows sharing/AV races.

    Concurrent status readers can briefly lock the destination on Win32 and
    raise ``PermissionError`` (WinError 5). Retry keeps display-pyramid builds
    from failing while the browser polls ``/display-pyramid/status``.
    """

    last: BaseException | None = None
    for i in range(max(1, int(attempts))):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(delay_s * (1.0 + 0.25 * i))
        except OSError as exc:
            # Transient sharing violations also surface as WinError 32/33.
            if getattr(exc, "winerror", None) not in {5, 32, 33} and exc.errno not in {
                errno.EACCES,
                errno.EPERM,
                errno.EBUSY,
            }:
                raise
            last = exc
            time.sleep(delay_s * (1.0 + 0.25 * i))
    assert last is not None
    raise last


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(dict(data), indent=2, sort_keys=True, ensure_ascii=True)
    tmp.write_text(text, encoding="utf-8")
    _atomic_replace(tmp, path)


def _atomic_save_npy(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # np.save adds .npy if missing; write to explicit tmp path via file handle.
    with open(tmp, "wb") as handle:
        np.save(handle, np.ascontiguousarray(array), allow_pickle=False)
    _atomic_replace(tmp, path)


def mean_pool_downsample(volume: np.ndarray, factor: int) -> np.ndarray:
    """Mean-pool downsample a (z,y,x) volume by integer ``factor`` per axis.

    Truncates to a multiple of ``factor`` on each axis (no edge padding).
    """

    if factor < 1:
        raise ValueError("factor must be >= 1")
    if factor == 1:
        return np.ascontiguousarray(volume)
    arr = np.asarray(volume)
    if arr.ndim != 3:
        raise ValueError("mean_pool_downsample expects (z, y, x)")
    z, y, x = arr.shape
    z2, y2, x2 = (z // factor) * factor, (y // factor) * factor, (x // factor) * factor
    if z2 == 0 or y2 == 0 or x2 == 0:
        raise ValueError(f"volume too small to downsample by {factor}: shape={arr.shape}")
    cropped = arr[:z2, :y2, :x2]
    shape = (z2 // factor, factor, y2 // factor, factor, x2 // factor, factor)
    blocks = cropped.reshape(shape)
    # float64 mean then cast back
    pooled = blocks.mean(axis=(1, 3, 5))
    if np.issubdtype(arr.dtype, np.integer):
        return np.ascontiguousarray(np.rint(pooled).astype(arr.dtype, copy=False))
    return np.ascontiguousarray(pooled.astype(arr.dtype, copy=False))


def plan_levels(
    source_shape: tuple[int, int, int],
    source_dtype: np.dtype,
    *,
    config: PyramidConfig,
) -> list[tuple[int, tuple[int, int, int], tuple[int, int, int]]]:
    """Return list of (level_index, shape, factors_zyx) from fine (0) to coarse.

    Level 0 is the finest **stored** level (may still be downsampled from source
    if source exceeds max_level_bytes). Higher indices are coarser.
    """

    itemsize = max(1, int(np.dtype(source_dtype).itemsize))
    z, y, x = (int(source_shape[0]), int(source_shape[1]), int(source_shape[2]))
    factors = (1, 1, 1)
    # If full source exceeds transfer budget, start with enough downsample so
    # level 0 fits max_level_bytes when possible.
    while z * y * x * itemsize > config.max_level_bytes and min(z, y, x) >= config.scale_factor * 2:
        f = config.scale_factor
        z, y, x = z // f, y // f, x // f
        factors = (factors[0] * f, factors[1] * f, factors[2] * f)

    levels: list[tuple[int, tuple[int, int, int], tuple[int, int, int]]] = []
    level = 0
    cur_shape = (z, y, x)
    cur_factors = factors
    while level < config.max_levels:
        levels.append((level, cur_shape, cur_factors))
        if level + 1 >= config.max_levels:
            break
        f = config.scale_factor
        nz, ny, nx = cur_shape[0] // f, cur_shape[1] // f, cur_shape[2] // f
        if min(nz, ny, nx) < 2:
            break
        cur_shape = (nz, ny, nx)
        cur_factors = (cur_factors[0] * f, cur_factors[1] * f, cur_factors[2] * f)
        level += 1
    return levels


def select_level_for_budget(
    levels: list[LevelDescriptor],
    *,
    max_bytes: int,
) -> LevelDescriptor | None:
    """Pick the finest ready level that fits ``max_bytes``; else coarsest that fits."""

    if not levels:
        return None
    # Prefer finest (lowest level index) that fits.
    fitting = [lv for lv in levels if lv.nbytes <= max_bytes]
    if fitting:
        return min(fitting, key=lambda lv: lv.level)
    # None fit: return coarsest (largest level index) anyway for progressive UI.
    return max(levels, key=lambda lv: lv.level)


# ---------------------------------------------------------------------------
# Builder / store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoreRetentionConfig:
    """Bounded process-local pyramid store retention and concurrency."""

    max_entries: int = DEFAULT_MAX_CACHE_ENTRIES
    max_total_bytes: int = DEFAULT_MAX_CACHE_BYTES
    max_active_builds: int = DEFAULT_MAX_ACTIVE_BUILDS

    def __post_init__(self) -> None:
        if self.max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if self.max_total_bytes < 1:
            raise ValueError("max_total_bytes must be >= 1")
        if self.max_active_builds < 1:
            raise ValueError("max_active_builds must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_entries": int(self.max_entries),
            "max_total_bytes": int(self.max_total_bytes),
            "max_active_builds": int(self.max_active_builds),
        }


@dataclass
class PyramidBuildStatus:
    cache_key: str
    state: PyramidState
    source_revision: str
    levels_ready: list[int] = field(default_factory=list)
    planned_levels: list[int] = field(default_factory=list)
    error: str | None = None
    generation: str | None = None
    build_started_s: float | None = None
    build_finished_s: float | None = None
    config: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] | None = None
    attached: bool = False  # True when start returned an existing job/result

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "state": self.state,
            "source_revision": self.source_revision,
            "levels_ready": list(self.levels_ready),
            "planned_levels": list(self.planned_levels),
            "error": self.error,
            "generation": self.generation,
            "build_started_s": self.build_started_s,
            "build_finished_s": self.build_finished_s,
            "config": self.config,
            "manifest": self.manifest,
            "attached": bool(self.attached),
            "storage_backend": STORAGE_BACKEND,
            "cache_schema": CACHE_SCHEMA,
        }


class ActiveBuildLimitError(RuntimeError):
    """Raised when a new pyramid build would exceed max_active_builds."""


class DisplayPyramidStore:
    """Filesystem-backed pyramid cache with atomic level/manifest publish.

    Retention: deterministic LRU by last access, bounded by entry count and
    total bytes. **Active builds are never evicted.** Concurrent background
    builds are capped (``max_active_builds``); same-key start **attaches**.
    """

    def __init__(
        self,
        cache_root: Path | None = None,
        *,
        retention: StoreRetentionConfig | None = None,
    ) -> None:
        self.cache_root = Path(cache_root) if cache_root is not None else default_cache_root()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.retention = retention or StoreRetentionConfig()
        self._lock = threading.RLock()
        self._jobs: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        # LRU: oldest at front. Touched on access / successful build.
        self._lru: OrderedDict[str, float] = OrderedDict()
        self._shutting_down = False
        self._rebuild_lru_from_disk()

    def cache_dir(self, cache_key: str) -> Path:
        return self.cache_root / cache_key

    def state_path(self, cache_key: str) -> Path:
        return self.cache_dir(cache_key) / "state.json"

    def manifest_path(self, cache_key: str) -> Path:
        return self.cache_dir(cache_key) / "manifest.json"

    def level_path(self, cache_key: str, level: int) -> Path:
        return self.cache_dir(cache_key) / "levels" / f"level_{int(level)}.npy"

    def _rebuild_lru_from_disk(self) -> None:
        """Seed LRU from existing cache dirs (mtime)."""

        if not self.cache_root.is_dir():
            return
        entries: list[tuple[float, str]] = []
        for child in self.cache_root.iterdir():
            if not child.is_dir():
                continue
            key = child.name
            try:
                mtime = child.stat().st_mtime
            except OSError:
                mtime = 0.0
            entries.append((mtime, key))
        for _, key in sorted(entries, key=lambda t: t[0]):
            self._lru[key] = time.time()
            self._lru.move_to_end(key)

    def _touch(self, cache_key: str) -> None:
        self._lru[cache_key] = time.time()
        self._lru.move_to_end(cache_key)

    def _dir_nbytes(self, path: Path) -> int:
        total = 0
        if not path.is_dir():
            return 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += int((Path(root) / name).stat().st_size)
                except OSError:
                    continue
        return total

    def total_cache_bytes(self) -> int:
        with self._lock:
            return sum(self._dir_nbytes(self.cache_dir(k)) for k in list(self._lru.keys()))

    def entry_count(self) -> int:
        with self._lock:
            return len(self._lru)

    def active_build_count(self) -> int:
        with self._lock:
            return self._active_build_count_unlocked()

    def _active_build_count_unlocked(self) -> int:
        n = 0
        for key, th in list(self._jobs.items()):
            if th.is_alive():
                n += 1
            else:
                # Reap dead threads
                self._jobs.pop(key, None)
                self._cancel.pop(key, None)
        return n

    def _is_active_build(self, cache_key: str) -> bool:
        """True only while a live build thread is registered for this key."""

        th = self._jobs.get(cache_key)
        return th is not None and th.is_alive()

    def list_cache_keys(self) -> list[str]:
        with self._lock:
            return list(self._lru.keys())

    def enforce_retention(self) -> list[str]:
        """Evict LRU complete/failed/partial entries until within bounds.

        Never evicts keys with an active live build thread. Returns evicted keys.
        """

        with self._lock:
            return self._enforce_retention_unlocked()

    def _enforce_retention_unlocked(self) -> list[str]:
        evicted: list[str] = []
        # Reap dead jobs first
        self._active_build_count_unlocked()

        def over_budget() -> bool:
            if len(self._lru) > self.retention.max_entries:
                return True
            total = sum(self._dir_nbytes(self.cache_dir(k)) for k in self._lru)
            return total > self.retention.max_total_bytes

        # Evict oldest first (OrderedDict front)
        guard = 0
        while over_budget() and self._lru and guard < 10_000:
            guard += 1
            # Find oldest non-active key
            victim: str | None = None
            for key in self._lru.keys():
                if self._is_active_build(key):
                    continue
                victim = key
                break
            if victim is None:
                # Only active builds remain; stop (may still be over budget).
                break
            self._invalidate_unlocked(victim, cancel_active=False)
            evicted.append(victim)
        return evicted

    def read_status(self, cache_key: str) -> PyramidBuildStatus | None:
        sp = self.state_path(cache_key)
        if not sp.is_file():
            return None
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        manifest = None
        mp = self.manifest_path(cache_key)
        if mp.is_file() and data.get("state") in {"partial", "complete"}:
            try:
                manifest = json.loads(mp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = None
        return PyramidBuildStatus(
            cache_key=cache_key,
            state=data.get("state", "failed"),  # type: ignore[arg-type]
            source_revision=str(data.get("source_revision", "")),
            levels_ready=[int(x) for x in data.get("levels_ready", [])],
            planned_levels=[int(x) for x in data.get("planned_levels", [])],
            error=data.get("error"),
            generation=data.get("generation"),
            build_started_s=data.get("build_started_s"),
            build_finished_s=data.get("build_finished_s"),
            config=dict(data.get("config") or {}),
            manifest=manifest,
            attached=bool(data.get("attached", False)),
        )

    def _write_state(self, status: PyramidBuildStatus) -> None:
        payload = status.to_dict()
        # Keep manifest out of state file body size; stored separately.
        payload.pop("manifest", None)
        _atomic_write_json(self.state_path(status.cache_key), payload)

    def invalidate(self, cache_key: str) -> None:
        """Remove a cache entry (disposable). Cancels active build if any."""

        with self._lock:
            self._invalidate_unlocked(cache_key, cancel_active=True)

    def _invalidate_unlocked(self, cache_key: str, *, cancel_active: bool) -> None:
        if cancel_active:
            ev = self._cancel.get(cache_key)
            if ev is not None:
                ev.set()
        d = self.cache_dir(cache_key)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
        self._jobs.pop(cache_key, None)
        self._cancel.pop(cache_key, None)
        self._lru.pop(cache_key, None)

    def shutdown(self, timeout: float = 30.0) -> None:
        """Cancel all active builds, join threads, stop accepting new builds."""

        with self._lock:
            self._shutting_down = True
            for ev in list(self._cancel.values()):
                ev.set()
            threads = list(self._jobs.values())
        deadline = time.time() + max(0.0, float(timeout))
        for th in threads:
            remaining = max(0.0, deadline - time.time())
            th.join(timeout=remaining)
        with self._lock:
            self._jobs.clear()
            self._cancel.clear()

    def build_from_array(
        self,
        volume: np.ndarray,
        *,
        revision: StackRevision,
        voxel_size: VoxelSize,
        voxel_source: str = "unknown",
        axes: str = "ZYX",
        config: PyramidConfig | None = None,
        cache_key: str | None = None,
    ) -> str:
        """Synchronously build pyramid from a (z,y,x) array. Returns cache_key."""

        cfg = config or PyramidConfig()
        gray = np.ascontiguousarray(volume)
        if gray.ndim != 3:
            raise ValueError("volume must be (z, y, x)")
        if gray.nbytes > cfg.max_source_bytes:
            raise ValueError(
                f"source volume {gray.nbytes} bytes exceeds max_source_bytes={cfg.max_source_bytes}"
            )
        key = cache_key or pyramid_cache_key(
            revision,
            source_axes=axes,
            source_dtype=str(gray.dtype),
            voxel_size=voxel_size,
            voxel_source=voxel_source,
            config=cfg,
        )
        with self._lock:
            if self._shutting_down:
                raise RuntimeError("DisplayPyramidStore is shutting down")
            self._touch(key)
        self._run_build(
            key,
            gray,
            revision=revision,
            voxel_size=voxel_size,
            voxel_source=voxel_source,
            axes=axes,
            config=cfg,
            cancel=threading.Event(),
        )
        with self._lock:
            self._touch(key)
            self._enforce_retention_unlocked()
        return key

    def start_build_from_volume_source(
        self,
        source: VolumeSource,
        *,
        config: PyramidConfig | None = None,
        background: bool = True,
    ) -> str:
        """Build from VolumeSource. Same key attaches; new builds respect max_active_builds."""

        cfg = config or PyramidConfig()
        meta = source.metadata()
        revision = source.revision
        key = pyramid_cache_key(
            revision,
            source_axes=meta.axes,
            source_dtype=str(meta.dtype),
            voxel_size=meta.voxel_size,
            voxel_source=meta.voxel_source,
            config=cfg,
        )

        with self._lock:
            if self._shutting_down:
                raise RuntimeError("DisplayPyramidStore is shutting down")

            existing = self.read_status(key)
            # Attach to complete cache hit
            if existing is not None and existing.state == "complete":
                if existing.source_revision == revision.identity:
                    self._touch(key)
                    return key
            # Attach to in-flight same-key job
            th_existing = self._jobs.get(key)
            if th_existing is not None and th_existing.is_alive():
                self._touch(key)
                return key

            # New build: enforce concurrency bound
            active = self._active_build_count_unlocked()
            if active >= self.retention.max_active_builds:
                raise ActiveBuildLimitError(
                    f"active display-pyramid builds at limit "
                    f"({self.retention.max_active_builds}); attach to an existing "
                    f"cache_key or retry later"
                )

            cancel = threading.Event()
            self._cancel[key] = cancel
            started = time.time()
            status = PyramidBuildStatus(
                cache_key=key,
                state="queued",
                source_revision=revision.identity,
                config=cfg.to_dict(),
                generation=None,
                build_started_s=started,
            )
            self.cache_dir(key).mkdir(parents=True, exist_ok=True)
            self._write_state(status)
            self._touch(key)

            def worker() -> None:
                try:
                    if cancel.is_set():
                        failed = PyramidBuildStatus(
                            cache_key=key,
                            state="failed",
                            source_revision=revision.identity,
                            error="cancelled",
                            config=cfg.to_dict(),
                            build_started_s=started,
                            build_finished_s=time.time(),
                        )
                        self._write_state(failed)
                        return
                    vol = source.materialize_roi()
                    self._run_build(
                        key,
                        vol,
                        revision=revision,
                        voxel_size=meta.voxel_size,
                        voxel_source=meta.voxel_source,
                        axes=meta.axes,
                        config=cfg,
                        cancel=cancel,
                    )
                except Exception as exc:  # noqa: BLE001 — surface in state
                    failed = PyramidBuildStatus(
                        cache_key=key,
                        state="failed",
                        source_revision=revision.identity,
                        error=str(exc),
                        config=cfg.to_dict(),
                        build_started_s=started,
                        build_finished_s=time.time(),
                    )
                    self._write_state(failed)
                finally:
                    with self._lock:
                        self._jobs.pop(key, None)
                        self._cancel.pop(key, None)
                        self._touch(key)
                        self._enforce_retention_unlocked()

            if background:
                th = threading.Thread(
                    target=worker,
                    name=f"display-pyramid-{key[:8]}",
                    daemon=True,
                )
                self._jobs[key] = th
                th.start()
                return key

            # Synchronous: register current thread as active, run outside lock.
            self._jobs[key] = threading.current_thread()

        try:
            worker()
        finally:
            with self._lock:
                self._jobs.pop(key, None)
                self._cancel.pop(key, None)
                self._touch(key)
                self._enforce_retention_unlocked()
        return key

    def _run_build(
        self,
        cache_key: str,
        volume: np.ndarray,
        *,
        revision: StackRevision,
        voxel_size: VoxelSize,
        voxel_source: str,
        axes: str,
        config: PyramidConfig,
        cancel: threading.Event,
    ) -> None:
        gray = np.ascontiguousarray(volume)
        started = time.time()
        generation = hashlib.sha1(f"{cache_key}:{started}".encode()).hexdigest()[:12]
        planned = plan_levels(gray.shape, gray.dtype, config=config)
        planned_ids = [p[0] for p in planned]

        status = PyramidBuildStatus(
            cache_key=cache_key,
            state="running",
            source_revision=revision.identity,
            levels_ready=[],
            planned_levels=planned_ids,
            generation=generation,
            build_started_s=started,
            config=config.to_dict(),
        )
        cache_dir = self.cache_dir(cache_key)
        cache_dir.mkdir(parents=True, exist_ok=True)
        levels_dir = cache_dir / "levels"
        levels_dir.mkdir(parents=True, exist_ok=True)
        self._write_state(status)

        # Coarse-first: reverse planned order for publish, but compute from fine chain.
        # Build fine→coarse in memory chain without keeping all levels:
        # start from appropriately pre-downsampled source for level 0.
        if not planned:
            status.state = "failed"
            status.error = "no levels planned"
            status.build_finished_s = time.time()
            self._write_state(status)
            return

        # Prepare level-0 array from source using first planned factors.
        _, shape0, factors0 = planned[0]
        cur = gray
        fz0, fy0, fx0 = factors0
        # Apply successive mean pools for initial factors (powers of scale_factor).
        f = config.scale_factor
        # factors are products of f; apply log times
        while cur.shape[0] > shape0[0] or cur.shape[1] > shape0[1] or cur.shape[2] > shape0[2]:
            if cancel.is_set():
                status.state = "failed"
                status.error = "cancelled"
                status.build_finished_s = time.time()
                self._write_state(status)
                return
            try:
                cur = mean_pool_downsample(cur, f)
            except ValueError:
                break
        # Crop/pad to exact planned shape0 if off-by-one from truncation
        cur = cur[: shape0[0], : shape0[1], : shape0[2]]
        if cur.shape != shape0:
            # If still larger factors mismatch, recompute via successive pool until match or fail
            status.state = "failed"
            status.error = f"level0 shape mismatch got {cur.shape} expected {shape0}"
            status.build_finished_s = time.time()
            self._write_state(status)
            return

        level_arrays: dict[int, np.ndarray] = {0: cur}
        # Build coarser from previous
        for level_idx, shape, factors in planned[1:]:
            if cancel.is_set():
                status.state = "failed"
                status.error = "cancelled"
                status.build_finished_s = time.time()
                self._write_state(status)
                return
            prev = level_arrays[level_idx - 1]
            coarser = mean_pool_downsample(prev, config.scale_factor)
            coarser = coarser[: shape[0], : shape[1], : shape[2]]
            level_arrays[level_idx] = coarser
            # Free previous only after coarser built if we don't need fine for publish order
            # Keep all until published coarse-first for simplicity on small stacks.

        # Publish coarse-first (highest level index first)
        ready: list[int] = []
        level_descs: list[dict[str, Any]] = []
        for level_idx, shape, factors in sorted(planned, key=lambda t: -t[0]):
            if cancel.is_set():
                status.state = "partial" if ready else "failed"
                status.error = "cancelled"
                status.levels_ready = ready
                status.build_finished_s = time.time()
                self._write_state(status)
                return
            arr = level_arrays[level_idx]
            _atomic_save_npy(self.level_path(cache_key, level_idx), arr)
            scale = (float(factors[0]), float(factors[1]), float(factors[2]))
            level_voxel = VoxelSize(
                x_um=float(voxel_size.x_um) * scale[2],
                y_um=float(voxel_size.y_um) * scale[1],
                z_um=float(voxel_size.z_um) * scale[0],
            )
            desc = LevelDescriptor(
                level=level_idx,
                shape=(int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2])),
                dtype=str(arr.dtype),
                axes=axes if axes else "ZYX",
                scale_zyx=scale,
                voxel_size=level_voxel,
                nbytes=int(arr.nbytes),
                display_only=True,  # all pyramid levels display-only in this packet
                downsample_from_source=factors,
            )
            level_descs.append(desc.to_dict())
            ready.append(level_idx)
            ready.sort()
            # Partial manifest after each level (atomic)
            manifest = {
                "cache_key": cache_key,
                "schema": CACHE_SCHEMA,
                "cache_format_version": config.cache_format_version,
                "algorithm_version": config.algorithm_version,
                "storage_backend": config.storage_backend,
                "source_revision": revision.identity,
                "source_axes": axes,
                "source_dtype": str(gray.dtype),
                "source_shape": list(gray.shape),
                "voxel_size": voxel_size.to_dict(),
                "voxel_source": voxel_source,
                "downsample_kernel": config.downsample_kernel,
                "scale_factor": config.scale_factor,
                "generation": generation,
                "levels": sorted(level_descs, key=lambda d: d["level"]),
                "complete": False,
                "display_only": True,
            }
            _atomic_write_json(self.manifest_path(cache_key), manifest)
            status.state = "partial"
            status.levels_ready = list(ready)
            status.manifest = manifest
            self._write_state(status)

        # Mark complete only when all planned levels published
        if sorted(ready) == sorted(planned_ids):
            manifest = json.loads(self.manifest_path(cache_key).read_text(encoding="utf-8"))
            manifest["complete"] = True
            _atomic_write_json(self.manifest_path(cache_key), manifest)
            status.state = "complete"
            status.levels_ready = list(ready)
            status.manifest = manifest
            status.build_finished_s = time.time()
            status.error = None
            self._write_state(status)
        else:
            status.state = "partial"
            status.build_finished_s = time.time()
            self._write_state(status)
        with self._lock:
            self._touch(cache_key)
            self._enforce_retention_unlocked()

    def load_level_array(self, cache_key: str, level: int) -> np.ndarray:
        path = self.level_path(cache_key, level)
        if not path.is_file():
            raise FileNotFoundError(f"level {level} not published for key {cache_key}")
        with open(path, "rb") as handle:
            arr = np.load(handle, allow_pickle=False)
        return np.ascontiguousarray(arr)

    def get_ready_level_descriptors(self, cache_key: str) -> list[LevelDescriptor]:
        status = self.read_status(cache_key)
        if status is None or not status.manifest:
            return []
        out: list[LevelDescriptor] = []
        for raw in status.manifest.get("levels", []):
            if int(raw["level"]) not in status.levels_ready:
                continue
            vs = raw["voxel_size"]
            out.append(
                LevelDescriptor(
                    level=int(raw["level"]),
                    shape=tuple(int(x) for x in raw["shape"]),  # type: ignore[arg-type]
                    dtype=str(raw["dtype"]),
                    axes=str(raw["axes"]),
                    scale_zyx=tuple(float(x) for x in raw["scale_zyx"]),  # type: ignore[arg-type]
                    voxel_size=VoxelSize(float(vs["x_um"]), float(vs["y_um"]), float(vs["z_um"])),
                    nbytes=int(raw["nbytes"]),
                    display_only=True,
                    downsample_from_source=tuple(int(x) for x in raw["downsample_from_source"]),  # type: ignore[arg-type]
                )
            )
        return out

    def select_and_load_level(
        self,
        cache_key: str,
        *,
        level: int | None = None,
        max_bytes: int | None = None,
    ) -> tuple[LevelDescriptor, np.ndarray, DisplayVolumeSpec]:
        """Return (descriptor, array, DisplayVolumeSpec) for a ready level."""

        status = self.read_status(cache_key)
        if status is None:
            raise FileNotFoundError(f"unknown pyramid cache_key {cache_key}")
        if status.state not in {"partial", "complete"}:
            raise RuntimeError(f"pyramid not ready: state={status.state}")
        descs = self.get_ready_level_descriptors(cache_key)
        if not descs:
            raise RuntimeError("no levels ready")
        if level is not None:
            chosen = next((d for d in descs if d.level == int(level)), None)
            if chosen is None:
                raise FileNotFoundError(f"level {level} not ready")
        else:
            budget = int(max_bytes if max_bytes is not None else DEFAULT_MAX_LEVEL_BYTES)
            chosen = select_level_for_budget(descs, max_bytes=budget)
            if chosen is None:
                raise RuntimeError("no level selectable")
        arr = self.load_level_array(cache_key, chosen.level)
        # Sanity: shape match
        if tuple(arr.shape) != chosen.shape:
            raise RuntimeError("level array shape does not match manifest")
        spec = chosen.as_display_volume_spec(source_revision=status.source_revision)
        # Hard isolation: science entry must reject this.
        try:
            reject_non_scientific_input(spec, context="display_pyramid level")
        except ResultAuthorityError:
            pass  # expected; we still return the display product
        with self._lock:
            self._touch(cache_key)
        return chosen, arr, spec


_DEFAULT_STORE: DisplayPyramidStore | None = None
_STORE_LOCK = threading.Lock()


def default_display_pyramid_store() -> DisplayPyramidStore:
    global _DEFAULT_STORE
    with _STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = DisplayPyramidStore()
        return _DEFAULT_STORE


def shutdown_default_display_pyramid_store(timeout: float = 30.0) -> None:
    """Cancel/join the process default store (app lifespan)."""

    global _DEFAULT_STORE
    with _STORE_LOCK:
        store = _DEFAULT_STORE
    if store is not None:
        store.shutdown(timeout=timeout)


def reset_default_display_pyramid_store_for_tests() -> None:
    """Drop the process singleton (tests only)."""

    global _DEFAULT_STORE
    with _STORE_LOCK:
        if _DEFAULT_STORE is not None:
            try:
                _DEFAULT_STORE.shutdown(timeout=2.0)
            except Exception:
                pass
        _DEFAULT_STORE = None


def storage_decision_record() -> dict[str, Any]:
    """Evidence for handoff: why internal NPY vs OME-Zarr."""

    zarr_available = False
    try:
        import importlib.util

        zarr_available = importlib.util.find_spec("zarr") is not None
    except Exception:
        zarr_available = False
    return {
        "chosen": STORAGE_BACKEND,
        "schema": CACHE_SCHEMA,
        "cache_format_version": CACHE_FORMAT_VERSION,
        "algorithm_version": PYRAMID_ALGORITHM_VERSION,
        "ome_ngff_zarr": "not_selected",
        "reason": (
            "zarr/numcodecs not declared in pyproject.toml and not installed; "
            "packet forbids undeclared dependency install without approval. "
            "Bounded internal NPY levels (one file per level) avoid Windows "
            "many-small-chunk risk and keep the same DisplayPyramid interface "
            "for a future pinned NGFF backend."
        ),
        "zarr_available_in_env": zarr_available,
        "lossy_compression": False,
        "downsample_kernel": DOWNSAMPLE_KERNEL,
    }
