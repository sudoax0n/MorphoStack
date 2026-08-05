"""RBC-specific capability, calibration, and authority contracts.

These types are the shared vocabulary for the RBC path. Later phases import
them rather than inventing parallel strings or optional vesicle fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class RbcCapability(str, Enum):
    """Highest measured capability tier currently supported for a run."""

    PIXEL_PREVIEW = "PIXEL_PREVIEW"
    CALIBRATED_2D = "2D_OUTER_CONTOUR"
    VALIDATED_3D_OCCUPANCY = "3D_OCCUPANCY_VALIDATED"
    VALIDATED_3D_SURFACE = "3D_SURFACE_VALIDATED"


class RbcAuthority(str, Enum):
    """Scientific authority of a reported RBC quantity or geometry."""

    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"
    WITHHELD = "WITHHELD"

    @property
    def is_measured(self) -> bool:
        return self is RbcAuthority.MEASURED


class RbcSignalSemantics(str, Enum):
    """How the fluorescence/intensity signal relates to cell geometry.

    Engineering QC must not treat UNKNOWN as solid filled volume. Membrane vs
    interior labeling is settled with lab acquisition evidence (Phase 5).
    """

    UNKNOWN = "unknown"
    MEMBRANE = "membrane"
    INTERIOR = "interior"


class RbcRefusalCode(str, Enum):
    """Stable machine codes for fail-closed RBC input refusal."""

    SEED_REQUIRED = "seed_required"
    LSM_REQUIRES_CONVERSION_OR_MANUAL = "lsm_requires_conversion_or_manual_calibration"
    INCOMPLETE_AXIS_CALIBRATION = "incomplete_axis_calibration"
    UNVERIFIED_CONVERTED_METADATA = "unverified_converted_metadata"


class EngineeringQcStatus(str, Enum):
    """Software-side QC only — not lab biological validation."""

    NOT_RUN = "not_run"
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


REFUSAL_GUIDANCE: dict[RbcRefusalCode, str] = {
    RbcRefusalCode.SEED_REQUIRED: (
        "RBC analysis requires one explicit circle or polygon seed. "
        "Select a single cell before running analysis."
    ),
    RbcRefusalCode.LSM_REQUIRES_CONVERSION_OR_MANUAL: (
        "Direct .lsm input is inspectable but cannot start calibrated RBC analysis. "
        "Convert to a metadata-preserving TIFF/OME-TIFF, or supply manual X, Y, and Z "
        "voxel sizes in micrometers."
    ),
    RbcRefusalCode.INCOMPLETE_AXIS_CALIBRATION: (
        "RBC physical measurements require verified X, Y, and Z calibration. "
        "Provide complete metadata or manual overrides for all three axes."
    ),
    RbcRefusalCode.UNVERIFIED_CONVERTED_METADATA: (
        "Converted TIFF/OME-TIFF metadata is incomplete or unverified for at least "
        "one axis. Supply manual X, Y, and Z calibration or a verified conversion."
    ),
}


@dataclass(frozen=True)
class CalibrationAxis:
    """Per-axis spacing and provenance for scientific gating."""

    value_um: float | None
    source: str
    verified: bool


@dataclass(frozen=True)
class CalibrationAssessment:
    """Independent X/Y/Z calibration status for one loaded stack."""

    x: CalibrationAxis
    y: CalibrationAxis
    z: CalibrationAxis
    source_format: str
    signal_semantics: RbcSignalSemantics = RbcSignalSemantics.UNKNOWN

    @property
    def all_axes_verified(self) -> bool:
        return all(
            axis.verified and axis.value_um is not None for axis in (self.x, self.y, self.z)
        )

    @property
    def all_axes_from_override(self) -> bool:
        return all(axis.source == "override" and axis.verified for axis in (self.x, self.y, self.z))

    def to_dict(self) -> dict[str, object]:
        def axis_dict(axis: CalibrationAxis) -> dict[str, object]:
            return {
                "value_um": axis.value_um,
                "source": axis.source,
                "verified": axis.verified,
            }

        return {
            "x": axis_dict(self.x),
            "y": axis_dict(self.y),
            "z": axis_dict(self.z),
            "source_format": self.source_format,
            "signal_semantics": self.signal_semantics.value,
            "all_axes_verified": self.all_axes_verified,
            "all_axes_from_override": self.all_axes_from_override,
        }


@dataclass(frozen=True)
class RbcInputDecision:
    """Outcome of the shared RBC input gate (pure evaluation)."""

    allowed: bool
    reasons: tuple[RbcRefusalCode, ...]
    capability: RbcCapability | None = None
    guidance: str = ""

    @property
    def primary_code(self) -> RbcRefusalCode | None:
        return self.reasons[0] if self.reasons else None

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "codes": [code.value for code in self.reasons],
            "code": self.primary_code.value if self.primary_code is not None else None,
            "capability": self.capability.value if self.capability is not None else None,
            "guidance": self.guidance,
        }


class RbcInputRefused(Exception):
    """Raised when RBC analysis is blocked before segmentation."""

    def __init__(self, decision: RbcInputDecision) -> None:
        self.decision = decision
        message = decision.guidance or (
            decision.primary_code.value if decision.primary_code is not None else "RBC input refused"
        )
        super().__init__(message)


class RbcTopologyIssue(str, Enum):
    """Topology / association issues for loop-aware RBC reconstruction."""

    EMPTY = "empty"
    MULTIPLE_OUTER_COMPONENTS = "multiple_outer_components"
    UNSUPPORTED_NESTING = "unsupported_nesting"
    RASTER_MISMATCH = "raster_mismatch"
    LATERAL_CLIPPING = "lateral_clipping"
    UNRESOLVED_MERGE = "unresolved_merge"
    INTERNAL_GAP = "internal_gap"
    NO_VALID_SLICES = "no_valid_slices"
    SEED_SLICE_FAILED = "seed_slice_failed"


@dataclass(frozen=True)
class RbcBoundaryLoop:
    """Closed polyline in full-image XY coordinates (N, 2)."""

    xy: np.ndarray
    role: str  # "outer" | "inner"

    def __post_init__(self) -> None:
        arr = np.asarray(self.xy, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] != 2:
            raise ValueError("boundary loop must have shape (N, 2)")
        object.__setattr__(self, "xy", arr)


@dataclass(frozen=True)
class RbcSliceTopology:
    """Loop-aware representation of one RBC Z slice."""

    frame_index: int
    outer_loop_xy: np.ndarray | None
    inner_loops_xy: tuple[np.ndarray, ...]
    occupancy_mask: np.ndarray | None
    issues: tuple[RbcTopologyIssue, ...]
    ok: bool
    method: str = ""
    center_xy: tuple[float, float] | None = None
    area_px: float = 0.0
    merge_suspect: bool = False

    @property
    def inner_loop_count(self) -> int:
        return len(self.inner_loops_xy)


@dataclass(frozen=True)
class RbcStackCandidate:
    """Full-stack topology-preserving occupancy candidate (provisional)."""

    seed_frame_index: int
    slices: tuple[RbcSliceTopology, ...]
    occupancy_mask: np.ndarray | None
    valid_slice_indices: tuple[int, ...]
    internal_gap_indices: tuple[int, ...]
    issues: tuple[RbcTopologyIssue, ...]
    withheld: bool
    ok: bool
    method: str = "rbc_topology_occupancy_v1"
    algorithm_version: str = "rbc_topology_v1"
    provenance: dict[str, Any] = field(default_factory=dict)


class RbcQcIssue(str, Enum):
    """Ordered reconstruction / morphometry QC reasons (fail-closed)."""

    CALIBRATION_UNVERIFIED = "calibration_unverified"
    NO_OCCUPANCY = "no_occupancy"
    SEED_SLICE_FAILED = "seed_slice_failed"
    INCOMPLETE_CAP = "incomplete_cap"
    INTERNAL_GAP = "internal_gap"
    LATERAL_CLIPPING = "lateral_clipping"
    UNRESOLVED_MERGE = "unresolved_merge"
    TOPOLOGY_FAILED = "topology_failed"
    MESH_INVALID = "mesh_invalid"
    VOLUME_DISAGREEMENT = "volume_disagreement"
    SIGNAL_SEMANTICS_UNKNOWN = "signal_semantics_unknown"


@dataclass(frozen=True)
class RbcProjectedMetrics:
    """Rotation-safe 2D morphometry from a physical-coordinate occupancy mask."""

    area_um2: float
    perimeter_um: float
    perimeter_method: str
    major_axis_um: float
    minor_axis_um: float
    aspect_ratio_L_over_W: float
    static_elongation_index: float
    circularity: float
    solidity: float
    equivalent_diameter_um: float
    method_version: str = "rbc_projected_moments_v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "area_um2": self.area_um2,
            "perimeter_um": self.perimeter_um,
            "perimeter_method": self.perimeter_method,
            "major_axis_um": self.major_axis_um,
            "minor_axis_um": self.minor_axis_um,
            "aspect_ratio_L_over_W": self.aspect_ratio_L_over_W,
            "static_elongation_index": self.static_elongation_index,
            "circularity": self.circularity,
            "solidity": self.solidity,
            "equivalent_diameter_um": self.equivalent_diameter_um,
            "method_version": self.method_version,
        }


@dataclass(frozen=True)
class RbcVolumeCrossCheck:
    """Voxel occupancy volume vs mesh volume consistency check."""

    voxel_volume_um3: float
    mesh_volume_um3: float | None
    surface_area_um2: float | None
    relative_disagreement: float | None
    method_version: str = "rbc_occupancy_volume_v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "voxel_volume_um3": self.voxel_volume_um3,
            "mesh_volume_um3": self.mesh_volume_um3,
            "surface_area_um2": self.surface_area_um2,
            "relative_disagreement": self.relative_disagreement,
            "method_version": self.method_version,
        }


@dataclass(frozen=True)
class RbcMeshQc:
    """Engineering mesh QC (not biological validation)."""

    ok: bool
    boundary_edge_count: int
    watertight: bool
    finite_vertices: bool
    positive_volume: bool
    component_count: int
    issues: tuple[RbcQcIssue, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "boundary_edge_count": self.boundary_edge_count,
            "watertight": self.watertight,
            "finite_vertices": self.finite_vertices,
            "positive_volume": self.positive_volume,
            "component_count": self.component_count,
            "issues": [i.value for i in self.issues],
        }


@dataclass(frozen=True)
class RbcQcResult:
    """Central reconstruction QC outcome and highest permitted capability."""

    capability: RbcCapability
    authority: RbcAuthority
    engineering_qc: EngineeringQcStatus
    issues: tuple[RbcQcIssue, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability.value,
            "authority": self.authority.value,
            "engineering_qc": self.engineering_qc.value,
            "issues": [i.value for i in self.issues],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RbcAnalysisResult:
    """Capability-scoped RBC morphometry attached to a stack analysis."""

    capability: RbcCapability
    authority: RbcAuthority
    engineering_qc: EngineeringQcStatus
    projected_metrics: RbcProjectedMetrics | None
    volume_um3: float | None
    surface_area_um2: float | None
    voxel_volume_um3: float | None
    mesh_volume_um3: float | None
    volume_relative_disagreement: float | None
    dimple_thickness_um: float | None
    rim_thickness_um: float | None
    issues: tuple[str, ...]
    method_versions: dict[str, str] = field(default_factory=dict)
    mesh_qc: RbcMeshQc | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability.value,
            "authority": self.authority.value,
            "engineering_qc": self.engineering_qc.value,
            "projected_metrics": (
                self.projected_metrics.to_dict() if self.projected_metrics is not None else None
            ),
            "volume_um3": self.volume_um3,
            "surface_area_um2": self.surface_area_um2,
            "voxel_volume_um3": self.voxel_volume_um3,
            "mesh_volume_um3": self.mesh_volume_um3,
            "volume_relative_disagreement": self.volume_relative_disagreement,
            "dimple_thickness_um": self.dimple_thickness_um,
            "rim_thickness_um": self.rim_thickness_um,
            "issues": list(self.issues),
            "method_versions": dict(self.method_versions),
            "mesh_qc": self.mesh_qc.to_dict() if self.mesh_qc is not None else None,
        }
