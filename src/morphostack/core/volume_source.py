"""Calibrated volume source and display plane cache (Milestone B).

Display / navigation path only. Exact analysis continues to use the existing
full-array ``load_image_stack`` / ``analyze_stack`` reference path until a later
packet deliberately switches science to streaming.

Identity is shared with ``stack_cache.path_source_identity`` — do not invent a
second revision scheme.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Literal
from uuid import uuid4

import numpy as np

from morphostack.core.images import as_grayscale_stack, rgb_to_gray
from morphostack.core.io import (
    DEFAULT_VOXEL_SIZE,
    SUPPORTED_EXTENSIONS,
    load_image_stack,
    standardize_shapes,
    voxel_from_czi_metadata,
    voxel_from_tiff,
)
from morphostack.core.models import VoxelSize
from morphostack.core.stack_cache import _file_signature, path_source_identity

PlaneAccessMode = Literal[
    "native_plane",  # true per-plane decode without full stack materialization
    "full_materialize_fallback",  # one full decode then plane views (explicit)
    "array_backed",  # already-resident array (session / in-memory)
]


@dataclass(frozen=True)
class StackRevision:
    """Immutable stack identity for volume cache and tracking keys.

    ``identity`` matches tracking/cache conventions:
    - path files: ``path_source_identity`` → ``path:…|m…|s…``
    - upload session: ``session:{stack_id}``
    - in-memory array: ``array:{token}``
    """

    identity: str
    kind: Literal["path", "session", "array", "upload_ephemeral"]
    path: str | None = None
    mtime_ns: int | None = None
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "kind": self.kind,
            "path": self.path,
            "mtime_ns": self.mtime_ns,
            "size_bytes": self.size_bytes,
        }


def stack_revision_from_path(path: str | Path) -> StackRevision:
    """Build a path StackRevision using the canonical path identity helper."""

    file_path = Path(path).resolve()
    identity = path_source_identity(file_path)
    mtime_ns, size = _file_signature(file_path)
    return StackRevision(
        identity=identity,
        kind="path",
        path=str(file_path),
        mtime_ns=int(mtime_ns),
        size_bytes=int(size),
    )


def stack_revision_from_session(stack_id: str) -> StackRevision:
    from morphostack.core.stack_cache import session_source_identity

    return StackRevision(
        identity=session_source_identity(stack_id),
        kind="session",
        path=None,
    )


def stack_revision_for_array(*, token: str | None = None) -> StackRevision:
    tok = (token or "").strip() or uuid4().hex[:12]
    return StackRevision(identity=f"array:{tok}", kind="array", path=None)


@dataclass(frozen=True)
class VolumeMetadata:
    """Calibrated volume metadata. Axes default to MorphoStack science order ZYX."""

    shape: tuple[int, int, int]  # (z, y, x) grayscale science shape
    dtype: str
    axes: str = "ZYX"
    channels: int = 1
    series: int = 0
    voxel_size: VoxelSize = field(default_factory=lambda: DEFAULT_VOXEL_SIZE)
    voxel_source: str = "unknown"  # metadata | override | default
    raw_shape: tuple[int, ...] | None = None
    raw_axes: str | None = None
    plane_access_mode: PlaneAccessMode = "native_plane"
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": list(self.shape),
            "dtype": self.dtype,
            "axes": self.axes,
            "channels": int(self.channels),
            "series": int(self.series),
            "voxel_size": {
                "x_um": float(self.voxel_size.x_um),
                "y_um": float(self.voxel_size.y_um),
                "z_um": float(self.voxel_size.z_um),
            },
            "voxel_source": self.voxel_source,
            "raw_shape": list(self.raw_shape) if self.raw_shape is not None else None,
            "raw_axes": self.raw_axes,
            "plane_access_mode": self.plane_access_mode,
            "source_path": self.source_path,
        }


class VolumeSource(ABC):
    """Backend-neutral calibrated volume reader (display + science materialize)."""

    @property
    @abstractmethod
    def revision(self) -> StackRevision:
        raise NotImplementedError

    @abstractmethod
    def metadata(self) -> VolumeMetadata:
        raise NotImplementedError

    @abstractmethod
    def read_plane(self, z: int, c: int = 0, t: int = 0) -> np.ndarray:
        """Exact full-resolution source plane as 2D (y, x) grayscale."""

        raise NotImplementedError

    @abstractmethod
    def read_block(
        self,
        z0: int,
        z1: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        *,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        """Exact full-resolution block as (z, y, x) grayscale."""

        raise NotImplementedError

    @abstractmethod
    def materialize_roi(
        self,
        *,
        z0: int | None = None,
        z1: int | None = None,
        y0: int | None = None,
        y1: int | None = None,
        x0: int | None = None,
        x1: int | None = None,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        """Full-resolution science-compatible grayscale array (possibly cropped)."""

        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> VolumeSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Plane cache (display residency only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlaneKey:
    revision_identity: str
    z: int
    c: int
    t: int


class PlaneCache:
    """Budgeted Z-neighbor plane cache for display. Not scientific authority."""

    def __init__(
        self,
        *,
        max_planes: int = 5,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if max_planes < 1:
            raise ValueError("max_planes must be >= 1")
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self._max_planes = int(max_planes)
        self._max_bytes = int(max_bytes)
        self._lock = Lock()
        self._entries: OrderedDict[_PlaneKey, np.ndarray] = OrderedDict()
        self._nbytes = 0

    @property
    def max_planes(self) -> int:
        return self._max_planes

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def nbytes(self) -> int:
        with self._lock:
            return int(self._nbytes)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._nbytes = 0

    def invalidate_revision(self, revision_identity: str) -> None:
        with self._lock:
            drop = [k for k in self._entries if k.revision_identity == revision_identity]
            for key in drop:
                arr = self._entries.pop(key)
                self._nbytes -= int(arr.nbytes)
            if self._nbytes < 0:
                self._nbytes = 0

    def get(self, revision_identity: str, z: int, c: int = 0, t: int = 0) -> np.ndarray | None:
        key = _PlaneKey(str(revision_identity), int(z), int(c), int(t))
        with self._lock:
            arr = self._entries.get(key)
            if arr is None:
                return None
            self._entries.move_to_end(key)
            return arr

    def put(
        self,
        revision_identity: str,
        z: int,
        plane: np.ndarray,
        *,
        c: int = 0,
        t: int = 0,
    ) -> None:
        arr = np.ascontiguousarray(plane)
        key = _PlaneKey(str(revision_identity), int(z), int(c), int(t))
        nbytes = int(arr.nbytes)
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._nbytes -= int(old.nbytes)
            while self._entries and (
                len(self._entries) >= self._max_planes or self._nbytes + nbytes > self._max_bytes
            ):
                _, victim = self._entries.popitem(last=False)
                self._nbytes -= int(victim.nbytes)
            # Single oversized plane: keep only that plane (budget + one in-flight).
            if nbytes > self._max_bytes:
                self._entries.clear()
                self._nbytes = 0
            self._entries[key] = arr
            self._entries.move_to_end(key)
            self._nbytes += nbytes
            while len(self._entries) > self._max_planes:
                _, victim = self._entries.popitem(last=False)
                self._nbytes -= int(victim.nbytes)
            if self._nbytes < 0:
                self._nbytes = 0


_DEFAULT_PLANE_CACHE = PlaneCache()


def default_plane_cache() -> PlaneCache:
    return _DEFAULT_PLANE_CACHE


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_voxel(
    detected: VoxelSize | None,
    voxel_override: VoxelSize | None,
) -> tuple[VoxelSize, str]:
    if voxel_override is not None:
        return voxel_override, "override"
    if detected is not None:
        return detected, "metadata"
    return DEFAULT_VOXEL_SIZE, "default"


def _plane_to_gray2d(plane: np.ndarray) -> np.ndarray:
    """Normalize a decoded page/plane to 2D grayscale (y, x)."""

    arr = np.asarray(plane)
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return np.ascontiguousarray(arr)
    if arr.ndim == 3 and arr.shape[-1] in (3, 4):
        return np.ascontiguousarray(rgb_to_gray(arr[..., :3]))
    if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[0] < min(arr.shape[1], arr.shape[2]):
        # (c, y, x)
        channel_last = np.moveaxis(arr[:3], 0, -1)
        return np.ascontiguousarray(rgb_to_gray(channel_last))
    raise ValueError(f"unsupported plane shape for grayscale conversion: {arr.shape}")


def _clamp_block(
    shape: tuple[int, int, int],
    z0: int,
    z1: int,
    y0: int,
    y1: int,
    x0: int,
    x1: int,
) -> tuple[int, int, int, int, int, int]:
    nz, ny, nx = shape
    z0 = max(0, min(nz, int(z0)))
    z1 = max(0, min(nz, int(z1)))
    y0 = max(0, min(ny, int(y0)))
    y1 = max(0, min(ny, int(y1)))
    x0 = max(0, min(nx, int(x0)))
    x1 = max(0, min(nx, int(x1)))
    if z1 <= z0 or y1 <= y0 or x1 <= x0:
        raise ValueError("empty block bounds")
    return z0, z1, y0, y1, x0, x1


class _BaseVolumeSource(VolumeSource):
    """Reader lock + optional plane cache around decode hooks."""

    def __init__(
        self,
        *,
        plane_cache: PlaneCache | None = None,
        use_cache: bool = True,
    ) -> None:
        self._plane_cache = plane_cache if plane_cache is not None else default_plane_cache()
        self._use_cache = bool(use_cache)
        self._reader_lock = RLock()
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("VolumeSource is closed")

    def read_plane(self, z: int, c: int = 0, t: int = 0) -> np.ndarray:
        self._ensure_open()
        meta = self.metadata()
        z_i, c_i, t_i = int(z), int(c), int(t)
        if z_i < 0 or z_i >= meta.shape[0]:
            raise ValueError(f"z={z_i} out of range for shape {meta.shape}")
        if c_i != 0:
            raise ValueError("only channel c=0 is supported in this packet")
        if t_i != 0:
            raise ValueError("only time t=0 is supported in this packet")

        rev = self.revision.identity
        if self._use_cache:
            hit = self._plane_cache.get(rev, z_i, c_i, t_i)
            if hit is not None:
                return hit

        with self._reader_lock:
            self._ensure_open()
            if self._use_cache:
                hit = self._plane_cache.get(rev, z_i, c_i, t_i)
                if hit is not None:
                    return hit
            plane = np.ascontiguousarray(self._decode_plane(z_i, c=c_i, t=t_i))
            if self._use_cache:
                self._plane_cache.put(rev, z_i, plane, c=c_i, t=t_i)
            return plane

    def read_block(
        self,
        z0: int,
        z1: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        *,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        self._ensure_open()
        meta = self.metadata()
        bounds = _clamp_block(meta.shape, z0, z1, y0, y1, x0, x1)
        with self._reader_lock:
            self._ensure_open()
            return np.ascontiguousarray(self._decode_block(*bounds, c=int(c), t=int(t)))

    def materialize_roi(
        self,
        *,
        z0: int | None = None,
        z1: int | None = None,
        y0: int | None = None,
        y1: int | None = None,
        x0: int | None = None,
        x1: int | None = None,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        self._ensure_open()
        meta = self.metadata()
        nz, ny, nx = meta.shape
        return self.read_block(
            0 if z0 is None else z0,
            nz if z1 is None else z1,
            0 if y0 is None else y0,
            ny if y1 is None else y1,
            0 if x0 is None else x0,
            nx if x1 is None else x1,
            c=c,
            t=t,
        )

    def close(self) -> None:
        with self._reader_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._plane_cache.invalidate_revision(self.revision.identity)
            except Exception:
                pass
            self._close_impl()

    @abstractmethod
    def _decode_plane(self, z: int, *, c: int = 0, t: int = 0) -> np.ndarray:
        raise NotImplementedError

    @abstractmethod
    def _decode_block(
        self,
        z0: int,
        z1: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        *,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        raise NotImplementedError

    @abstractmethod
    def _close_impl(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Array-backed (session / fallback materialization)
# ---------------------------------------------------------------------------


class ArrayVolumeSource(_BaseVolumeSource):
    """VolumeSource over an already-resident (z, y, x) grayscale array."""

    def __init__(
        self,
        grayscale: np.ndarray,
        *,
        revision: StackRevision,
        voxel_size: VoxelSize,
        voxel_source: str = "unknown",
        source_path: str | None = None,
        plane_access_mode: PlaneAccessMode = "array_backed",
        plane_cache: PlaneCache | None = None,
        use_cache: bool = True,
    ) -> None:
        super().__init__(plane_cache=plane_cache, use_cache=use_cache)
        gray = as_grayscale_stack(grayscale)
        if gray.ndim != 3:
            raise ValueError("ArrayVolumeSource expects grayscale shape (z, y, x)")
        self._gray = gray
        self._revision = revision
        self._meta = VolumeMetadata(
            shape=(int(gray.shape[0]), int(gray.shape[1]), int(gray.shape[2])),
            dtype=str(gray.dtype),
            axes="ZYX",
            channels=1,
            series=0,
            voxel_size=voxel_size,
            voxel_source=voxel_source,
            raw_shape=tuple(int(s) for s in gray.shape),
            raw_axes="ZYX",
            plane_access_mode=plane_access_mode,
            source_path=source_path,
        )

    @property
    def revision(self) -> StackRevision:
        return self._revision

    def metadata(self) -> VolumeMetadata:
        return self._meta

    def _decode_plane(self, z: int, *, c: int = 0, t: int = 0) -> np.ndarray:
        return self._gray[int(z)]

    def _decode_block(
        self,
        z0: int,
        z1: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        *,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        return self._gray[z0:z1, y0:y1, x0:x1]

    def _close_impl(self) -> None:
        # Do not free caller-owned arrays; sessions own the stack.
        return


# ---------------------------------------------------------------------------
# TIFF (native plane when multipage ZYX-like)
# ---------------------------------------------------------------------------


class TiffVolumeSource(_BaseVolumeSource):
    """Long-lived tifffile reader with serialized plane access."""

    def __init__(
        self,
        path: str | Path,
        *,
        voxel_override: VoxelSize | None = None,
        plane_cache: PlaneCache | None = None,
        use_cache: bool = True,
    ) -> None:
        super().__init__(plane_cache=plane_cache, use_cache=use_cache)
        try:
            import tifffile
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("tifffile is required for TiffVolumeSource") from exc

        self._path = Path(path).resolve()
        self._revision = stack_revision_from_path(self._path)
        self._tifffile = tifffile
        self._tif = tifffile.TiffFile(self._path)
        self._fallback_gray: np.ndarray | None = None

        series = self._tif.series[0] if self._tif.series else None
        if series is not None:
            raw_shape = tuple(int(s) for s in series.shape)
            raw_axes = str(getattr(series, "axes", "") or "")
            dtype = str(series.dtype)
        elif self._tif.pages:
            page0 = self._tif.pages[0].asarray()
            raw_shape = (len(self._tif.pages),) + tuple(int(s) for s in page0.shape)
            raw_axes = "ZYX" if page0.ndim == 2 else None
            dtype = str(page0.dtype)
        else:
            arr = self._tif.asarray()
            raw_shape = tuple(int(s) for s in arr.shape)
            raw_axes = None
            dtype = str(arr.dtype)

        g_shape, _ = standardize_shapes(raw_shape)
        shape = (int(g_shape[0]), int(g_shape[1]), int(g_shape[2]))
        detected = voxel_from_tiff(self._tif)
        voxel, voxel_source = _resolve_voxel(detected, voxel_override)

        self._native_plane = self._can_native_plane(raw_axes, raw_shape, shape)
        mode: PlaneAccessMode = "native_plane" if self._native_plane else "full_materialize_fallback"
        self._meta = VolumeMetadata(
            shape=shape,
            dtype=dtype,
            axes="ZYX",
            channels=1,
            series=0,
            voxel_size=voxel,
            voxel_source=voxel_source,
            raw_shape=raw_shape,
            raw_axes=raw_axes,
            plane_access_mode=mode,
            source_path=str(self._path),
        )

    @staticmethod
    def _can_native_plane(
        raw_axes: str | None,
        raw_shape: tuple[int, ...],
        science_shape: tuple[int, int, int],
    ) -> bool:
        if raw_axes:
            axes = raw_axes.upper()
            if axes in {"ZYX", "YXS", "YX"} or axes.replace("S", "") == "ZYX":
                return True
            if axes.endswith("YX") and axes.count("Z") == 1 and "T" not in axes:
                return True
        # Multipage Z stack: pages == z and page is 2D
        if len(raw_shape) == 3 and raw_shape == science_shape:
            return True
        return False

    @property
    def revision(self) -> StackRevision:
        return self._revision

    def metadata(self) -> VolumeMetadata:
        return self._meta

    def _ensure_fallback(self) -> np.ndarray:
        if self._fallback_gray is None:
            override = self._meta.voxel_size if self._meta.voxel_source == "override" else None
            stack = load_image_stack(self._path, voxel_override=override)
            self._fallback_gray = stack.grayscale
            self._meta = VolumeMetadata(
                shape=(
                    int(self._fallback_gray.shape[0]),
                    int(self._fallback_gray.shape[1]),
                    int(self._fallback_gray.shape[2]),
                ),
                dtype=str(self._fallback_gray.dtype),
                axes=self._meta.axes,
                channels=self._meta.channels,
                series=self._meta.series,
                voxel_size=stack.voxel_size,
                voxel_source=stack.voxel_source,
                raw_shape=self._meta.raw_shape,
                raw_axes=self._meta.raw_axes,
                plane_access_mode="full_materialize_fallback",
                source_path=self._meta.source_path,
            )
            self._native_plane = False
        return self._fallback_gray

    def _decode_plane(self, z: int, *, c: int = 0, t: int = 0) -> np.ndarray:
        if not self._native_plane:
            gray = self._ensure_fallback()
            return gray[z]

        try:
            if self._tif.pages and len(self._tif.pages) == self._meta.shape[0]:
                plane = self._tif.pages[z].asarray()
                return _plane_to_gray2d(plane)
            plane = self._tif.asarray(key=z)
            return _plane_to_gray2d(plane)
        except Exception:
            gray = self._ensure_fallback()
            return gray[z]

    def _decode_block(
        self,
        z0: int,
        z1: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        *,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        if not self._native_plane or (z1 - z0) > 8:
            gray = self._ensure_fallback()
            return gray[z0:z1, y0:y1, x0:x1]
        planes = [self._decode_plane(z)[y0:y1, x0:x1] for z in range(z0, z1)]
        return np.stack(planes, axis=0)

    def _close_impl(self) -> None:
        tif = getattr(self, "_tif", None)
        self._tif = None
        self._fallback_gray = None
        if tif is not None:
            try:
                tif.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CZI (header metadata without full load; plane via explicit full fallback)
# ---------------------------------------------------------------------------


class CziVolumeSource(_BaseVolumeSource):
    """CZI volume source.

    ``czifile`` does not expose a reliable single-plane reader for general
    multi-dimensional CZI files. This implementation:

    - reads metadata (shape/calibration) without materializing pixels;
    - on first pixel access, fully materializes via the reference loader and
      serves planes from the resident array with
      ``plane_access_mode='full_materialize_fallback'``.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        voxel_override: VoxelSize | None = None,
        plane_cache: PlaneCache | None = None,
        use_cache: bool = True,
    ) -> None:
        super().__init__(plane_cache=plane_cache, use_cache=use_cache)
        try:
            import czifile
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("czifile is required for CziVolumeSource") from exc

        self._path = Path(path).resolve()
        self._revision = stack_revision_from_path(self._path)
        self._czifile = czifile
        self._gray: np.ndarray | None = None
        self._voxel_override = voxel_override

        with czifile.CziFile(self._path) as czi:
            raw_shape = tuple(int(s) for s in czi.shape)
            detected = voxel_from_czi_metadata(czi.metadata())
        g_shape, _ = standardize_shapes(raw_shape)
        shape = (int(g_shape[0]), int(g_shape[1]), int(g_shape[2]))
        voxel, voxel_source = _resolve_voxel(detected, voxel_override)
        self._meta = VolumeMetadata(
            shape=shape,
            dtype="unknown",  # refined after first materialize
            axes="ZYX",
            channels=1,
            series=0,
            voxel_size=voxel,
            voxel_source=voxel_source,
            raw_shape=raw_shape,
            raw_axes=None,
            plane_access_mode="full_materialize_fallback",
            source_path=str(self._path),
        )

    @property
    def revision(self) -> StackRevision:
        return self._revision

    def metadata(self) -> VolumeMetadata:
        return self._meta

    def _ensure_materialized(self) -> np.ndarray:
        if self._gray is None:
            stack = load_image_stack(self._path, voxel_override=self._voxel_override)
            self._gray = stack.grayscale
            self._meta = VolumeMetadata(
                shape=(
                    int(self._gray.shape[0]),
                    int(self._gray.shape[1]),
                    int(self._gray.shape[2]),
                ),
                dtype=str(self._gray.dtype),
                axes="ZYX",
                channels=1,
                series=0,
                voxel_size=stack.voxel_size,
                voxel_source=stack.voxel_source,
                raw_shape=self._meta.raw_shape,
                raw_axes=self._meta.raw_axes,
                plane_access_mode="full_materialize_fallback",
                source_path=self._meta.source_path,
            )
        return self._gray

    def _decode_plane(self, z: int, *, c: int = 0, t: int = 0) -> np.ndarray:
        return self._ensure_materialized()[z]

    def _decode_block(
        self,
        z0: int,
        z1: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        *,
        c: int = 0,
        t: int = 0,
    ) -> np.ndarray:
        return self._ensure_materialized()[z0:z1, y0:y1, x0:x1]

    def _close_impl(self) -> None:
        self._gray = None


# ---------------------------------------------------------------------------
# Open registry (bounded long-lived readers)
# ---------------------------------------------------------------------------


class VolumeSourceRegistry:
    """Process-local LRU of open path-backed volume sources."""

    def __init__(self, *, max_entries: int = 3) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = int(max_entries)
        self._lock = Lock()
        self._entries: OrderedDict[str, VolumeSource] = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            items = list(self._entries.items())
            self._entries.clear()
        for _, src in items:
            try:
                src.close()
            except Exception:
                pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get_or_open(
        self,
        path: str | Path,
        *,
        voxel_override: VoxelSize | None = None,
        plane_cache: PlaneCache | None = None,
    ) -> VolumeSource:
        file_path = Path(path).resolve()
        current = stack_revision_from_path(file_path)
        key = f"{file_path}|vox={_voxel_key(voxel_override)}"
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                if existing.revision.identity == current.identity:
                    self._entries.move_to_end(key)
                    return existing
                del self._entries[key]
                try:
                    existing.close()
                except Exception:
                    pass
            source = open_volume_source(
                file_path,
                voxel_override=voxel_override,
                plane_cache=plane_cache,
                register=False,
            )
            self._entries[key] = source
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                _, old = self._entries.popitem(last=False)
                try:
                    old.close()
                except Exception:
                    pass
            return source


def _voxel_key(voxel: VoxelSize | None) -> tuple[float, float, float] | None:
    if voxel is None:
        return None
    return (float(voxel.x_um), float(voxel.y_um), float(voxel.z_um))


_DEFAULT_REGISTRY = VolumeSourceRegistry(max_entries=3)


def default_volume_source_registry() -> VolumeSourceRegistry:
    return _DEFAULT_REGISTRY


def open_volume_source(
    path: str | Path,
    *,
    voxel_override: VoxelSize | None = None,
    plane_cache: PlaneCache | None = None,
    use_cache: bool = True,
    register: bool = True,
) -> VolumeSource:
    """Open a path-backed VolumeSource (TIFF native plane; CZI explicit fallback)."""

    file_path = Path(path)
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported image format {ext!r}; expected one of {supported}")

    if register:
        return default_volume_source_registry().get_or_open(
            file_path,
            voxel_override=voxel_override,
            plane_cache=plane_cache,
        )

    if ext in {".tif", ".tiff", ".lsm"}:
        return TiffVolumeSource(
            file_path,
            voxel_override=voxel_override,
            plane_cache=plane_cache,
            use_cache=use_cache,
        )
    return CziVolumeSource(
        file_path,
        voxel_override=voxel_override,
        plane_cache=plane_cache,
        use_cache=use_cache,
    )


def volume_source_from_array(
    grayscale: np.ndarray,
    *,
    voxel_size: VoxelSize,
    voxel_source: str = "unknown",
    source_path: str | None = None,
    revision: StackRevision | None = None,
    plane_cache: PlaneCache | None = None,
    use_cache: bool = False,
) -> ArrayVolumeSource:
    """Wrap a resident grayscale stack (sessions / tests)."""

    rev = revision or stack_revision_for_array()
    return ArrayVolumeSource(
        grayscale,
        revision=rev,
        voxel_size=voxel_size,
        voxel_source=voxel_source,
        source_path=source_path,
        plane_cache=plane_cache,
        use_cache=use_cache,
    )


def format_support_matrix() -> list[dict[str, str]]:
    """Static support/fallback matrix for handoff documentation and tests."""

    return [
        {
            "format": "TIFF/TIF/LSM",
            "metadata": "header via tifffile (no full pixel load)",
            "plane": "native multipage/key when ZYX-like; else full_materialize_fallback",
            "science": "unchanged load_image_stack reference",
        },
        {
            "format": "CZI",
            "metadata": "header via czifile (shape + calibration)",
            "plane": "full_materialize_fallback (czifile has no reliable plane API)",
            "science": "unchanged load_image_stack reference",
        },
        {
            "format": "session/array",
            "metadata": "from resident ImageStack",
            "plane": "array_backed views",
            "science": "same resident array",
        },
    ]
