"""Estimated RBC model authority boundary (Phase 4 plumbing only)."""

from __future__ import annotations

import pytest

from morphostack.core.models import ResultAuthorityError, VoxelSize
from morphostack.core.rbc_capabilities import calibration_from_override
from morphostack.core.rbc_estimation import (
    RbcEstimateRequest,
    RbcEstimatorUnavailable,
    get_production_estimator,
    register_production_estimator,
    request_rbc_estimate,
)
from morphostack.core.rbc_models import (
    RbcAuthority,
    RbcEstimatedOutput,
    RbcProjectedMetrics,
)


class _FakeEstimator:
    model_id = "fake_sphere_v0"
    model_version = "0.0-test"

    def estimate(self, request: RbcEstimateRequest) -> RbcEstimatedOutput:
        _ = request
        return RbcEstimatedOutput(
            authority=RbcAuthority.ESTIMATED,
            model_id=self.model_id,
            model_version=self.model_version,
            assumptions=("test-only sphere from projected area",),
            confidence_note="Engineering fake; not for lab use.",
            volume_um3=100.0,
            surface_area_um2=50.0,
        )


class _BadAuthorityEstimator:
    model_id = "bad"
    model_version = "0"

    def estimate(self, request: RbcEstimateRequest) -> RbcEstimatedOutput:
        _ = request
        # Bypass __post_init__ guard by constructing via object.__new__ path is hard;
        # instead mutate after construction is frozen — raise via request_rbc_estimate
        # by returning a wrong authority through a hand-built instance.
        obj = object.__new__(RbcEstimatedOutput)
        object.__setattr__(obj, "authority", RbcAuthority.MEASURED)
        object.__setattr__(obj, "model_id", self.model_id)
        object.__setattr__(obj, "model_version", self.model_version)
        object.__setattr__(obj, "assumptions", ())
        object.__setattr__(obj, "confidence_note", "")
        object.__setattr__(obj, "volume_um3", 1.0)
        object.__setattr__(obj, "surface_area_um2", 1.0)
        object.__setattr__(obj, "geometry_role", "estimated_display_only")
        return obj  # type: ignore[return-value]


def test_production_estimator_is_none_by_default():
    assert get_production_estimator() is None
    with pytest.raises(RbcEstimatorUnavailable) as exc:
        request_rbc_estimate(
            RbcEstimateRequest(projected_metrics=None, calibration=None),
            provider=None,
        )
    assert exc.value.code == "rbc_estimator_not_validated"


def test_fake_estimator_returns_estimated_authority_only():
    out = request_rbc_estimate(
        RbcEstimateRequest(
            projected_metrics=RbcProjectedMetrics(
                area_um2=10.0,
                perimeter_um=12.0,
                perimeter_method="crofton_4",
                major_axis_um=4.0,
                minor_axis_um=3.0,
                aspect_ratio_L_over_W=4.0 / 3.0,
                static_elongation_index=0.1,
                circularity=0.9,
                solidity=0.95,
                equivalent_diameter_um=3.5,
            ),
            calibration=calibration_from_override(0.1, 0.1, 0.2, source_format="tiff"),
        ),
        provider=_FakeEstimator(),
    )
    assert out.authority is RbcAuthority.ESTIMATED
    assert out.volume_um3 == 100.0
    assert "test-only" in out.assumptions[0]


def test_estimator_cannot_claim_measured_authority():
    with pytest.raises(ResultAuthorityError):
        request_rbc_estimate(
            RbcEstimateRequest(projected_metrics=None, calibration=None),
            provider=_BadAuthorityEstimator(),
        )


def test_estimated_output_rejects_measured_construction():
    with pytest.raises(ValueError):
        RbcEstimatedOutput(
            authority=RbcAuthority.MEASURED,
            model_id="x",
            model_version="1",
            assumptions=(),
            confidence_note="",
        )


def test_register_production_estimator_is_explicit(monkeypatch):
    # Ensure we restore empty registry.
    register_production_estimator(_FakeEstimator())
    try:
        assert get_production_estimator() is not None
        out = request_rbc_estimate(
            RbcEstimateRequest(projected_metrics=None, calibration=None)
        )
        assert out.authority is RbcAuthority.ESTIMATED
    finally:
        register_production_estimator(None)
    assert get_production_estimator() is None
