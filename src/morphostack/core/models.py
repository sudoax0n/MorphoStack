"""Shared core data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

import numpy as np


@dataclass(frozen=True)
class VoxelSize:
    """Physical voxel spacing in micrometers."""

    x_um: float
    y_um: float
    z_um: float

    def __post_init__(self) -> None:
        for name, value in (
            ("x_um", self.x_um),
            ("y_um", self.y_um),
            ("z_um", self.z_um),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

    @property
    def marching_cubes_spacing(self) -> tuple[float, float, float]:
        """Spacing order for arrays shaped as (z, y, x)."""

        return (self.z_um, self.y_um, self.x_um)

    def to_dict(self) -> dict[str, float]:
        """JSON-safe voxel spacing (finite positives only)."""

        return {
            "x_um": _json_safe_finite(self.x_um, default=1.0),
            "y_um": _json_safe_finite(self.y_um, default=1.0),
            "z_um": _json_safe_finite(self.z_um, default=1.0),
        }


@dataclass(frozen=True)
class ImageStack:
    """Loaded microscope stack with standardized arrays and physical spacing."""

    source_path: Path
    grayscale: np.ndarray
    color: np.ndarray
    voxel_size: VoxelSize
    voxel_source: str = "unknown"
    # Optional per-axis provenance (Phase 1 RBC gates). Legacy callers may omit it.
    calibration: Any = None

    def __post_init__(self) -> None:
        if self.grayscale.ndim != 3:
            raise ValueError("grayscale stack must have shape (z, y, x)")
        if self.color.ndim != 4:
            raise ValueError("color stack must have shape (z, y, x, c)")
        if self.color.shape[:3] != self.grayscale.shape:
            raise ValueError("color and grayscale stacks must share z/y/x dimensions")


# ---------------------------------------------------------------------------
# Result authority / provenance (Milestone B lock before 3D viewer)
#
# Product roles (must never be conflated):
#   1. DisplayVolumeSpec  — navigation-only volume level
#   2. SegmentationCandidate — provisional / algorithm-produced mask
#   3. AuthoritativeMask  — accepted full-resolution scientific mask
#   4. ScientificMesh     — complete measured mesh from AuthoritativeMask
#   5. DisplayMesh        — LOD/derived geometry; no measurement authority
# ---------------------------------------------------------------------------

ResultRole = Literal[
    "display_volume",
    "segmentation_candidate",
    "authoritative_mask",
    "scientific_mesh",
    "display_mesh",
]

CandidateCompleteness = Literal["partial", "complete"]
AcceptanceState = Literal["provisional", "accepted", "rejected", "unaccepted"]


class ResultAuthorityError(TypeError):
    """Raised when a non-authoritative product is used as scientific input."""

    def __init__(self, message: str, *, role: str | None = None) -> None:
        super().__init__(message)
        self.role = role


def _json_safe_finite(value: float, *, default: float | None = None) -> float | None:
    """Coerce to a finite float or a default; never NaN/Inf for JSON."""

    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(v):
        return default
    return v


def _json_safe_mapping(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recursively replace non-finite floats with None for JSON serialization."""

    if not data:
        return {}
    out: dict[str, Any] = {}
    for key, value in data.items():
        out[str(key)] = _json_safe_value(value)
    return out


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return _json_safe_finite(float(value), default=None)
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return {
            "shape": [int(s) for s in value.shape],
            "dtype": str(value.dtype),
        }
    return str(value)


def _read_only_array(array: np.ndarray, *, name: str = "array") -> np.ndarray:
    """Return a write-protected view of ``array`` without an obligatory copy.

    When the input is already non-writeable, it is returned as-is (view
    semantics). Otherwise a view with ``write=False`` is used so wrappers do
    not force a full-mask copy solely for authority packaging.
    """

    arr = np.asarray(array)
    if arr is not array and not arr.flags.owndata:
        # asarray produced a view of something else; still lock it.
        pass
    if not arr.flags.writeable:
        return arr
    view = arr.view()
    try:
        view.setflags(write=False)
    except ValueError:
        # Rare: array base does not allow flag changes; keep original.
        return arr
    return view


def _binary_mask(array: np.ndarray, *, name: str = "mask") -> np.ndarray:
    arr = np.asarray(array)
    if arr.ndim != 3:
        raise ValueError(f"{name} must have shape (z, y, x)")
    # Prefer view/read-only lock when the array is already a clean binary mask.
    # Avoid a full copy solely for authority packaging.
    if arr.dtype == np.bool_ or arr.dtype == bool:
        binary = arr.astype(np.uint8, copy=False)
    elif arr.dtype == np.uint8:
        # Common pipeline path: uint8 {0,1} or {0,255}. Only renormalize if needed.
        # Peek without scanning the full volume when flags already imply binary use.
        sample = arr.flat[: min(arr.size, 4096)]
        mx = int(sample.max()) if sample.size else 0
        if mx <= 1:
            binary = arr
        else:
            binary = (arr != 0).astype(np.uint8, copy=False)
    else:
        binary = (arr != 0).astype(np.uint8, copy=False)
    return _read_only_array(binary, name=name)


@dataclass(frozen=True)
class DisplayVolumeSpec:
    """Viewer-only volume level. Never a measurement or segmentation input."""

    source_revision: str | None
    level: int
    shape: tuple[int, ...]
    dtype: str
    axes: str = "zyx"
    level_voxel_size: VoxelSize = field(default_factory=lambda: VoxelSize(1.0, 1.0, 1.0))
    downsampling: Mapping[str, Any] = field(default_factory=dict)
    intensity_window: tuple[float, float] | None = None
    display_only: bool = True

    role: ResultRole = field(default="display_volume", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.level < 0:
            raise ValueError("display volume level must be >= 0")
        if not self.axes:
            raise ValueError("axes must be non-empty")
        if len(self.shape) < 2:
            raise ValueError("shape must describe at least a 2D plane")
        # Force display_only=True even if a caller tried to override.
        object.__setattr__(self, "display_only", True)
        object.__setattr__(self, "downsampling", dict(self.downsampling or {}))
        if self.intensity_window is not None:
            lo, hi = self.intensity_window
            lo_f = _json_safe_finite(lo, default=None)
            hi_f = _json_safe_finite(hi, default=None)
            if lo_f is None or hi_f is None:
                object.__setattr__(self, "intensity_window", None)
            else:
                object.__setattr__(self, "intensity_window", (lo_f, hi_f))

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": "display_volume",
            "source_revision": self.source_revision,
            "level": int(self.level),
            "shape": [int(s) for s in self.shape],
            "dtype": str(self.dtype),
            "axes": str(self.axes),
            "level_voxel_size": self.level_voxel_size.to_dict(),
            "downsampling": _json_safe_mapping(self.downsampling),
            "intensity_window": (
                list(self.intensity_window) if self.intensity_window is not None else None
            ),
            "display_only": True,
        }


@dataclass(frozen=True)
class SegmentationCandidate:
    """Provisional or algorithm-produced mask/contour. Not automatically authoritative.

    Active-surfaces and progressive exact tracks produce candidates. A partial
    or provisional candidate cannot be silently accepted as AuthoritativeMask.
    """

    source_revision: str | None
    method: str
    algorithm_version: str
    completeness: CandidateCompleteness
    is_full_resolution: bool = True
    provisional: bool = False
    mask: np.ndarray | None = None
    contours: tuple[Any, ...] | None = None
    # Declared mapping when the mask is not full-resolution level-0.
    resolution_mapping: Mapping[str, Any] = field(default_factory=dict)
    qc: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    threshold_provenance: Mapping[str, Any] = field(default_factory=dict)

    role: ResultRole = field(default="segmentation_candidate", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.completeness not in ("partial", "complete"):
            raise ValueError("completeness must be 'partial' or 'complete'")
        if not self.method:
            raise ValueError("method is required")
        if not self.algorithm_version:
            raise ValueError("algorithm_version is required")
        if self.mask is not None:
            object.__setattr__(self, "mask", _read_only_array(np.asarray(self.mask), name="mask"))
        object.__setattr__(self, "resolution_mapping", dict(self.resolution_mapping or {}))
        object.__setattr__(self, "qc", dict(self.qc or {}))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))
        object.__setattr__(self, "threshold_provenance", dict(self.threshold_provenance or {}))

    @property
    def is_accepted(self) -> bool:
        return False

    @property
    def can_accept(self) -> bool:
        """Whether this candidate is eligible for the acceptance gate."""

        return bool(
            self.completeness == "complete"
            and not self.provisional
            and self.is_full_resolution
            and self.mask is not None
            and int(np.count_nonzero(self.mask)) > 0
        )

    def to_dict(self) -> dict[str, Any]:
        mask_meta = None
        if self.mask is not None:
            mask_meta = {
                "shape": [int(s) for s in self.mask.shape],
                "dtype": str(self.mask.dtype),
                "nonzero": int(np.count_nonzero(self.mask)),
            }
        return {
            "role": "segmentation_candidate",
            "source_revision": self.source_revision,
            "method": str(self.method),
            "algorithm_version": str(self.algorithm_version),
            "completeness": self.completeness,
            "is_full_resolution": bool(self.is_full_resolution),
            "provisional": bool(self.provisional),
            "mask": mask_meta,
            "contour_count": (
                None if self.contours is None else int(sum(1 for c in self.contours if c is not None))
            ),
            "resolution_mapping": _json_safe_mapping(self.resolution_mapping),
            "qc": _json_safe_mapping(self.qc),
            "provenance": _json_safe_mapping(self.provenance),
            "threshold_provenance": _json_safe_mapping(self.threshold_provenance),
            "can_accept": self.can_accept,
        }


# Content-bound analysis result identity (no process-global registry).
# revision form: "analysis:{scientific_mask_fingerprint}"
ANALYSIS_RESULT_REVISION_PREFIX = "analysis:"


def scientific_mask_fingerprint(
    mask: np.ndarray,
    *,
    voxel_size: VoxelSize,
    method: str,
    algorithm_version: str,
    source_revision: str | None = None,
    threshold_provenance: Mapping[str, Any] | None = None,
    roi_mapping: Mapping[str, Any] | None = None,
    z_mapping: Mapping[str, Any] | None = None,
) -> str:
    """Stable fingerprint of accepted mask content + scientific provenance.

    Binds identity to full-resolution binary mask bytes and the scientific
    fields that may change measurements. Diagnostic ``qc`` / free-form adapter
    ``provenance`` are intentionally excluded so re-acceptance of the same
    science is idempotent across call sites.
    """

    import hashlib
    import json

    binary = np.ascontiguousarray(_binary_mask(mask, name="fingerprint.mask"), dtype=np.uint8)
    hasher = hashlib.sha256()
    hasher.update(b"AuthoritativeMask.scientific_identity.v1\0")
    hasher.update(np.asarray(binary.shape, dtype=np.int64).tobytes())
    hasher.update(binary.tobytes())
    meta = {
        "source_revision": source_revision,
        "method": str(method),
        "algorithm_version": str(algorithm_version),
        "voxel_size": voxel_size.to_dict(),
        "threshold_provenance": _json_safe_mapping(threshold_provenance),
        "roi_mapping": _json_safe_mapping(roi_mapping),
        "z_mapping": _json_safe_mapping(z_mapping),
    }
    hasher.update(
        json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    return hasher.hexdigest()[:32]


def bound_analysis_result_revision(fingerprint: str) -> str:
    """Canonical content-bound analysis result revision string."""

    fp = str(fingerprint).strip()
    if not fp:
        raise ValueError("fingerprint is required")
    if fp.startswith(ANALYSIS_RESULT_REVISION_PREFIX):
        return fp
    return f"{ANALYSIS_RESULT_REVISION_PREFIX}{fp}"


def resolve_analysis_result_revision(
    requested: str | None,
    fingerprint: str,
) -> str:
    """Return the content-bound revision, or fail closed on conflict.

    Allowed ``requested`` values:
    - ``None`` / empty → bind to this fingerprint
    - bare fingerprint or ``analysis:{fingerprint}`` matching this content

    Any other claimed revision (including ``analysis:{other_fingerprint}``)
    is a same-revision / identity conflict and raises
    :class:`ResultAuthorityError`.
    """

    bound = bound_analysis_result_revision(fingerprint)
    if requested is None:
        return bound
    req = str(requested).strip()
    if not req or req == fingerprint or req == bound:
        return bound
    if req.startswith(ANALYSIS_RESULT_REVISION_PREFIX):
        claimed = req[len(ANALYSIS_RESULT_REVISION_PREFIX) :]
        if claimed == fingerprint:
            return bound
        raise ResultAuthorityError(
            "analysis_result_revision conflicts with mask/scientific provenance: "
            f"requested {req!r} but content binds to {bound!r}",
            role="authoritative_mask",
        )
    raise ResultAuthorityError(
        "analysis_result_revision must be content-bound "
        f"({bound!r} or bare fingerprint); got {req!r}",
        role="authoritative_mask",
    )


@dataclass(frozen=True)
class AuthoritativeMask:
    """Accepted, complete, full-resolution binary mask for scientific metrics.

    ``analysis_result_revision`` is **content-bound**: it is always
    ``analysis:{scientific_fingerprint}`` for this mask and scientific
    provenance. Identical science re-acceptance is idempotent (same revision).
    Conflicting mask content or scientific provenance under a claimed revision
    fails closed. No process-global registry is used.

    Display volumes, provisional previews, and unaccepted candidates must not
    construct this type without going through :func:`accept_segmentation_candidate`.
    """

    source_revision: str | None
    mask: np.ndarray
    voxel_size: VoxelSize
    method: str
    algorithm_version: str
    # Empty / None-equivalent → auto-bind from scientific fingerprint.
    # Non-empty must match this mask's bound identity or construction fails.
    analysis_result_revision: str = ""
    acceptance_state: AcceptanceState = "accepted"
    # ROI/Z mapping into the source stack (full-resolution coordinates).
    roi_mapping: Mapping[str, Any] = field(default_factory=dict)
    z_mapping: Mapping[str, Any] = field(default_factory=dict)
    threshold_provenance: Mapping[str, Any] = field(default_factory=dict)
    qc: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    # Set in __post_init__ from scientific_mask_fingerprint.
    scientific_fingerprint: str = field(default="", init=False, repr=True)

    role: ResultRole = field(default="authoritative_mask", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.acceptance_state != "accepted":
            raise ResultAuthorityError(
                "AuthoritativeMask requires acceptance_state='accepted'; "
                f"got {self.acceptance_state!r}",
                role="authoritative_mask",
            )
        if not self.method:
            raise ValueError("method is required")
        if not self.algorithm_version:
            raise ValueError("algorithm_version is required")
        binary = _binary_mask(self.mask, name="AuthoritativeMask.mask")
        if np.count_nonzero(binary) == 0:
            raise ValueError("AuthoritativeMask mask must contain at least one foreground voxel")
        object.__setattr__(self, "mask", binary)
        object.__setattr__(self, "roi_mapping", dict(self.roi_mapping or {}))
        object.__setattr__(self, "z_mapping", dict(self.z_mapping or {}))
        object.__setattr__(self, "threshold_provenance", dict(self.threshold_provenance or {}))
        object.__setattr__(self, "qc", dict(self.qc or {}))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))

        fingerprint = scientific_mask_fingerprint(
            binary,
            voxel_size=self.voxel_size,
            method=self.method,
            algorithm_version=self.algorithm_version,
            source_revision=self.source_revision,
            threshold_provenance=self.threshold_provenance,
            roi_mapping=self.roi_mapping,
            z_mapping=self.z_mapping,
        )
        bound = resolve_analysis_result_revision(self.analysis_result_revision, fingerprint)
        object.__setattr__(self, "scientific_fingerprint", fingerprint)
        object.__setattr__(self, "analysis_result_revision", bound)

    @property
    def is_accepted(self) -> bool:
        return self.acceptance_state == "accepted"

    @property
    def is_complete(self) -> bool:
        return True

    @property
    def is_full_resolution(self) -> bool:
        return True

    @property
    def shape(self) -> tuple[int, int, int]:
        z, y, x = (int(self.mask.shape[0]), int(self.mask.shape[1]), int(self.mask.shape[2]))
        return (z, y, x)

    def mask_array(self) -> np.ndarray:
        """Read-only binary mask view (z, y, x)."""

        return self.mask

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": "authoritative_mask",
            "source_revision": self.source_revision,
            "analysis_result_revision": self.analysis_result_revision,
            "scientific_fingerprint": self.scientific_fingerprint,
            "shape": list(self.shape),
            "dtype": str(self.mask.dtype),
            "nonzero": int(np.count_nonzero(self.mask)),
            "voxel_size": self.voxel_size.to_dict(),
            "method": str(self.method),
            "algorithm_version": str(self.algorithm_version),
            "acceptance_state": self.acceptance_state,
            "roi_mapping": _json_safe_mapping(self.roi_mapping),
            "z_mapping": _json_safe_mapping(self.z_mapping),
            "threshold_provenance": _json_safe_mapping(self.threshold_provenance),
            "qc": _json_safe_mapping(self.qc),
            "provenance": _json_safe_mapping(self.provenance),
        }


@dataclass(frozen=True)
class ScientificMesh:
    """Complete geometry and measurements derived only from AuthoritativeMask."""

    source_mask_revision: str
    analysis_result_revision: str
    vertices_xyz: np.ndarray
    faces: np.ndarray
    surface_area_um2: float
    volume_um3: float
    algorithm: str = "skimage_lewiner_marching_cubes"
    algorithm_version: str = "1"
    complete: bool = True

    role: ResultRole = field(default="scientific_mesh", init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.source_mask_revision:
            raise ValueError("source_mask_revision is required")
        if not self.analysis_result_revision:
            raise ValueError("analysis_result_revision is required")
        verts = np.asarray(self.vertices_xyz, dtype=np.float64)
        faces = np.asarray(self.faces, dtype=np.int64)
        if verts.ndim != 2 or verts.shape[1] != 3:
            raise ValueError("vertices_xyz must have shape (n, 3)")
        if faces.ndim != 2 or faces.shape[1] != 3:
            raise ValueError("faces must have shape (n, 3)")
        object.__setattr__(self, "vertices_xyz", _read_only_array(verts, name="vertices"))
        object.__setattr__(self, "faces", _read_only_array(faces, name="faces"))
        object.__setattr__(
            self,
            "surface_area_um2",
            float(_json_safe_finite(self.surface_area_um2, default=0.0) or 0.0),
        )
        object.__setattr__(
            self,
            "volume_um3",
            float(_json_safe_finite(self.volume_um3, default=0.0) or 0.0),
        )
        object.__setattr__(self, "complete", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": "scientific_mesh",
            "source_mask_revision": self.source_mask_revision,
            "analysis_result_revision": self.analysis_result_revision,
            "vertex_count": int(len(self.vertices_xyz)),
            "face_count": int(len(self.faces)),
            "surface_area_um2": _json_safe_finite(self.surface_area_um2, default=0.0),
            "volume_um3": _json_safe_finite(self.volume_um3, default=0.0),
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "complete": True,
        }


@dataclass(frozen=True)
class DisplayMesh:
    """Derived LOD/display geometry. Has no scientific measurement authority.

    Measurements cannot be stored or overwritten on this type. Use
    ScientificMesh for surface area / volume.
    """

    source_scientific_mesh_revision: str
    analysis_result_revision: str
    vertices_xyz: np.ndarray
    faces: np.ndarray
    lod_method: str
    source_vertex_count: int
    source_face_count: int
    geometric_error: Mapping[str, Any] = field(default_factory=dict)
    algorithm_version: str = "1"

    role: ResultRole = field(default="display_mesh", init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.source_scientific_mesh_revision:
            raise ValueError("source_scientific_mesh_revision is required")
        if not self.analysis_result_revision:
            raise ValueError("analysis_result_revision is required")
        if not self.lod_method:
            raise ValueError("lod_method is required")
        verts = np.asarray(self.vertices_xyz, dtype=np.float64)
        faces = np.asarray(self.faces, dtype=np.int64)
        if verts.ndim != 2 or verts.shape[1] != 3:
            raise ValueError("vertices_xyz must have shape (n, 3)")
        if faces.ndim != 2 or faces.shape[1] != 3:
            raise ValueError("faces must have shape (n, 3)")
        object.__setattr__(self, "vertices_xyz", _read_only_array(verts, name="vertices"))
        object.__setattr__(self, "faces", _read_only_array(faces, name="faces"))
        object.__setattr__(self, "geometric_error", dict(self.geometric_error or {}))
        # Hard-block accidental measurement *fields* (not the raising property).
        forbidden = {"surface_area_um2", "volume_um3", "measurement"}
        field_names = {f.name for f in self.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        # dataclass fields intentionally exclude the measurement property.
        if forbidden & field_names:
            raise ResultAuthorityError(
                "DisplayMesh cannot carry scientific measurements",
                role="display_mesh",
            )

    @property
    def output_vertex_count(self) -> int:
        return int(len(self.vertices_xyz))

    @property
    def output_face_count(self) -> int:
        return int(len(self.faces))

    @property
    def measurement(self) -> None:
        """Display meshes have no scientific measurement authority."""

        raise ResultAuthorityError(
            "DisplayMesh has no scientific measurement authority; use ScientificMesh",
            role="display_mesh",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": "display_mesh",
            "source_scientific_mesh_revision": self.source_scientific_mesh_revision,
            "analysis_result_revision": self.analysis_result_revision,
            "lod_method": self.lod_method,
            "source_vertex_count": int(self.source_vertex_count),
            "source_face_count": int(self.source_face_count),
            "output_vertex_count": self.output_vertex_count,
            "output_face_count": self.output_face_count,
            "geometric_error": _json_safe_mapping(self.geometric_error),
            "algorithm_version": self.algorithm_version,
            "measurement_authority": None,
        }


def result_role_of(obj: Any) -> ResultRole | None:
    """Return the authority role for a known product type, else None."""

    role = getattr(obj, "role", None)
    if role in (
        "display_volume",
        "segmentation_candidate",
        "authoritative_mask",
        "scientific_mesh",
        "display_mesh",
    ):
        return role  # type: ignore[return-value]
    if isinstance(obj, DisplayVolumeSpec):
        return "display_volume"
    if isinstance(obj, SegmentationCandidate):
        return "segmentation_candidate"
    if isinstance(obj, AuthoritativeMask):
        return "authoritative_mask"
    if isinstance(obj, ScientificMesh):
        return "scientific_mesh"
    if isinstance(obj, DisplayMesh):
        return "display_mesh"
    return None


def reject_non_scientific_input(obj: Any, *, context: str = "scientific measurement") -> None:
    """Raise if ``obj`` is a typed product that must not feed science metrics.

    Raw ``ndarray`` / contour sequences are left to legacy call sites; typed
    display/candidate/display-mesh objects are always rejected here.
    """

    role = result_role_of(obj)
    if role is None:
        return
    if role == "authoritative_mask":
        if not getattr(obj, "is_accepted", False):
            raise ResultAuthorityError(
                f"{context} rejects unaccepted mask",
                role=role,
            )
        return
    if role == "scientific_mesh":
        return
    labels = {
        "display_volume": "DisplayVolumeSpec (display-only volume)",
        "segmentation_candidate": "SegmentationCandidate (provisional/unaccepted)",
        "display_mesh": "DisplayMesh (LOD/display geometry)",
    }
    label = labels.get(role, role)
    raise ResultAuthorityError(
        f"{context} rejects {label}; only AuthoritativeMask / ScientificMesh are allowed",
        role=role,
    )


def require_authoritative_mask(obj: Any, *, context: str = "scientific measurement") -> AuthoritativeMask:
    """Return ``obj`` if it is an accepted AuthoritativeMask; else raise."""

    reject_non_scientific_input(obj, context=context)
    if not isinstance(obj, AuthoritativeMask):
        raise ResultAuthorityError(
            f"{context} requires AuthoritativeMask, got {type(obj).__name__}",
            role=result_role_of(obj),
        )
    if not obj.is_accepted:
        raise ResultAuthorityError(
            f"{context} rejects unaccepted mask",
            role="authoritative_mask",
        )
    return obj


def accept_segmentation_candidate(
    candidate: SegmentationCandidate,
    *,
    voxel_size: VoxelSize,
    analysis_result_revision: str | None = None,
    roi_mapping: Mapping[str, Any] | None = None,
    z_mapping: Mapping[str, Any] | None = None,
    qc: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> AuthoritativeMask:
    """Promote a complete full-resolution candidate to AuthoritativeMask.

    Partial, provisional, empty, or non-full-resolution candidates are rejected.
    Active-surfaces and exact tracks use the same gate.

    ``analysis_result_revision`` is optional: when omitted, the revision is
    derived from the scientific mask fingerprint. When provided, it must match
    that bound identity (idempotent re-accept) or construction fails closed.
    """

    if not isinstance(candidate, SegmentationCandidate):
        raise ResultAuthorityError(
            f"accept_segmentation_candidate requires SegmentationCandidate, got {type(candidate).__name__}",
            role=result_role_of(candidate),
        )
    if candidate.provisional:
        raise ResultAuthorityError(
            "provisional SegmentationCandidate cannot be accepted",
            role="segmentation_candidate",
        )
    if candidate.completeness != "complete":
        raise ResultAuthorityError(
            "partial SegmentationCandidate cannot be accepted",
            role="segmentation_candidate",
        )
    if not candidate.is_full_resolution:
        raise ResultAuthorityError(
            "non-full-resolution SegmentationCandidate cannot be accepted",
            role="segmentation_candidate",
        )
    if candidate.mask is None or np.count_nonzero(candidate.mask) == 0:
        raise ResultAuthorityError(
            "SegmentationCandidate has no usable full-resolution mask",
            role="segmentation_candidate",
        )

    merged_qc = dict(candidate.qc)
    if qc:
        merged_qc.update(qc)
    merged_prov = dict(candidate.provenance)
    if provenance:
        merged_prov.update(provenance)

    return AuthoritativeMask(
        source_revision=candidate.source_revision,
        analysis_result_revision=analysis_result_revision or "",
        mask=candidate.mask,
        voxel_size=voxel_size,
        method=candidate.method,
        algorithm_version=candidate.algorithm_version,
        acceptance_state="accepted",
        roi_mapping=dict(roi_mapping or {}),
        z_mapping=dict(z_mapping or {}),
        threshold_provenance=dict(candidate.threshold_provenance),
        qc=merged_qc,
        provenance=merged_prov,
    )


def display_mesh_from_scientific(
    scientific: ScientificMesh,
    *,
    vertices_xyz: np.ndarray | None = None,
    faces: np.ndarray | None = None,
    lod_method: str = "weld_compact",
    geometric_error: Mapping[str, Any] | None = None,
    algorithm_version: str | None = None,
) -> DisplayMesh:
    """Derive a DisplayMesh from a ScientificMesh (display path only).

    Default ``lod_method`` is ``weld_compact`` (packet 14). When vertices/faces
    are omitted, pure-NumPy weld/compact is applied to the scientific mesh.
    Face-stride is not used.
    """

    if not isinstance(scientific, ScientificMesh):
        raise ResultAuthorityError(
            f"display_mesh_from_scientific requires ScientificMesh, got {type(scientific).__name__}",
            role=result_role_of(scientific),
        )
    from morphostack.core.mesh import (
        DISPLAY_METHOD_WELD_COMPACT,
        count_boundary_edges,
        weld_compact_mesh,
    )

    src_v = int(len(scientific.vertices_xyz))
    src_f = int(len(scientific.faces))
    geo_err = dict(geometric_error or {})
    if vertices_xyz is None or faces is None:
        if lod_method != DISPLAY_METHOD_WELD_COMPACT and lod_method != "weld_compact":
            raise ValueError(
                "automatic display derivation only supports lod_method='weld_compact'; "
                "pass explicit vertices/faces for other methods"
            )
        disp_v, disp_f, stats = weld_compact_mesh(scientific.vertices_xyz, scientific.faces)
        vertices_xyz = disp_v
        faces = disp_f
        geo_err = {
            **geo_err,
            **{k: stats[k] for k in stats if k not in {"display_method"}},
            "display_only": True,
        }
        lod_method = DISPLAY_METHOD_WELD_COMPACT
    else:
        # Caller-supplied derivative: still record boundary counts when missing.
        if "boundary_edge_count_source" not in geo_err:
            geo_err["boundary_edge_count_source"] = count_boundary_edges(scientific.faces)
        if "boundary_edge_count_display" not in geo_err:
            geo_err["boundary_edge_count_display"] = count_boundary_edges(faces)
        geo_err.setdefault("display_only", True)

    return DisplayMesh(
        source_scientific_mesh_revision=scientific.source_mask_revision,
        analysis_result_revision=scientific.analysis_result_revision,
        vertices_xyz=vertices_xyz,
        faces=faces,
        lod_method=lod_method,
        source_vertex_count=src_v,
        source_face_count=src_f,
        geometric_error=geo_err,
        algorithm_version=algorithm_version or scientific.algorithm_version,
    )


def authority_provenance_payload(
    *,
    source_revision: str | None,
    analysis_result_revision: str | None = None,
    method: str | None = None,
    algorithm_version: str | None = None,
    role: ResultRole | str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-safe authority/source revision block (never NaN)."""

    payload: dict[str, Any] = {
        "source_revision": source_revision,
        "analysis_result_revision": analysis_result_revision,
        "method": method,
        "algorithm_version": algorithm_version,
        "role": role,
    }
    if extra:
        for key, value in extra.items():
            payload[str(key)] = _json_safe_value(value)
    return _json_safe_mapping(payload)
