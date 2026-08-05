"""Estimated RBC model plumbing (no production biological formula in Phase 4).

Production startup must not register an estimator until Phase 5 validates one.
Tests may inject a deterministic fake provider via ``request_rbc_estimate``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from morphostack.core.models import ResultAuthorityError
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

    ``provider`` defaults to the production registry (empty in Phase 4).
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
