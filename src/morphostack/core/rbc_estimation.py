"""Estimated RBC model plumbing.

A conservative occupancy-based display estimator may run when MEASURED 3D is
blocked (e.g. uncalibrated LSM). It never claims MEASURED authority.
A lab-validated biological formula is still Phase 5 and is not auto-registered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from morphostack.core.models import ResultAuthorityError, VoxelSize
from morphostack.core.rbc_models import (
    CalibrationAssessment,
    RbcAuthority,
    RbcEstimatedOutput,
    RbcProjectedMetrics,
)


class RbcEstimatorUnavailable(Exception):
    """Raised when no validated estimator is registered for production use."""

    code = "rbc_estimator_not_validated"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "RBC estimator is not validated for production use.")
        self.detail = {
            "code": self.code,
            "message": str(self),
            "guidance": (
                "Estimated RBC geometry remains unavailable until a lab-validated "
                "model is registered (Phase 5). Measured results are unaffected."
            ),
        }


@dataclass(frozen=True)
class RbcEstimateRequest:
    """Inputs an estimator may consume — measured footprint + calibration only."""

    projected_metrics: RbcProjectedMetrics | None
    calibration: CalibrationAssessment | None
    assumptions: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class RbcEstimator(Protocol):
    """Provider interface for estimated RBC geometry."""

    model_id: str
    model_version: str

    def estimate(self, request: RbcEstimateRequest) -> RbcEstimatedOutput: ...


# Production registry: intentionally empty until Phase 5.
_PRODUCTION_ESTIMATOR: RbcEstimator | None = None


def get_production_estimator() -> RbcEstimator | None:
    """Return the production estimator, or None if none is validated."""

    return _PRODUCTION_ESTIMATOR


def register_production_estimator(provider: RbcEstimator | None) -> None:
    """Register or clear the production estimator (Phase 5 / tests only)."""

    global _PRODUCTION_ESTIMATOR
    _PRODUCTION_ESTIMATOR = provider


def request_rbc_estimate(
    request: RbcEstimateRequest,
    *,
    provider: RbcEstimator | None = None,
) -> RbcEstimatedOutput:
    """Run an estimate through an explicit provider; never invent a model.

    ``provider`` defaults to the production registry (empty unless registered).
    """

    active = provider if provider is not None else get_production_estimator()
    if active is None:
        raise RbcEstimatorUnavailable()
    output = active.estimate(request)
    if not isinstance(output, RbcEstimatedOutput):
        raise ResultAuthorityError("RBC estimator returned a non-estimated output type")
    if output.authority is not RbcAuthority.ESTIMATED:
        raise ResultAuthorityError("RBC estimator returned non-estimated authority")
    return output


class OccupancyDisplayEstimator:
    """ESTIMATED mesh/volume from topology occupancy for visualization only.

    Used when calibration prevents MEASURED 3D (direct LSM without manual
    X/Y/Z, incomplete axes). Spacing is taken as-is and labeled ESTIMATED.
    This is not a lab-validated biconcave biological model.
    """

    model_id = "rbc_occupancy_display_estimate"
    model_version = "v1_display_only"

    def estimate_from_occupancy(
        self,
        occupancy: np.ndarray,
        voxel: VoxelSize,
        *,
        disclaimer_codes: tuple[str, ...] = (),
    ) -> RbcEstimatedOutput:
        arr = np.asarray(occupancy) != 0
        n = int(np.count_nonzero(arr))
        voxel_vol = float(n) * float(voxel.x_um) * float(voxel.y_um) * float(voxel.z_um)
        mesh_vol = None
        sa = None
        if n > 0:
            try:
                from morphostack.core.mesh import marching_cubes_measurement

                meas = marching_cubes_measurement(arr.astype(np.uint8), voxel)
                mesh_vol = float(meas.volume_um3)
                sa = float(meas.surface_area_um2)
            except Exception:
                mesh_vol = None
                sa = None
        assumptions = (
            "display_only_occupancy_mesh",
            "spacing_not_verified_as_measured",
            "not_lab_validated_biconcave_formula",
            *disclaimer_codes,
        )
        return RbcEstimatedOutput(
            authority=RbcAuthority.ESTIMATED,
            model_id=self.model_id,
            model_version=self.model_version,
            assumptions=assumptions,
            confidence_note=(
                "ESTIMATED visualization mesh from topology occupancy. "
                "Not MEASURED. Convert LSM or enter manual X/Y/Z for measured metrics."
            ),
            volume_um3=mesh_vol if mesh_vol is not None else voxel_vol,
            surface_area_um2=sa,
            geometry_role="estimated_display_only",
        )

    def estimate(self, request: RbcEstimateRequest) -> RbcEstimatedOutput:
        # Protocol path without occupancy: refuse inventing a volume.
        _ = request
        return RbcEstimatedOutput(
            authority=RbcAuthority.ESTIMATED,
            model_id=self.model_id,
            model_version=self.model_version,
            assumptions=("no_occupancy_in_request",),
            confidence_note=(
                "Estimator needs occupancy from a seeded RBC run; "
                "standalone estimate endpoint remains unavailable for biological models."
            ),
            volume_um3=None,
            surface_area_um2=None,
        )


def build_display_estimate_from_occupancy(
    occupancy: np.ndarray | None,
    voxel: VoxelSize,
    *,
    disclaimer_codes: tuple[str, ...] = (),
) -> RbcEstimatedOutput | None:
    """Helper for pipeline: ESTIMATED mesh metrics or None if no occupancy."""

    if occupancy is None or not np.any(occupancy):
        return None
    return OccupancyDisplayEstimator().estimate_from_occupancy(
        occupancy, voxel, disclaimer_codes=disclaimer_codes
    )
