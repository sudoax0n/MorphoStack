"""Serialize RBC analysis results into the shared product envelope."""

from __future__ import annotations

from morphostack.core.pipeline import StackAnalysis
from morphostack.core.rbc_models import (
    CalibrationAssessment,
    RbcAnalysisResult,
    RbcEstimatedOutput,
    RbcResultEnvelope,
    envelope_from_analysis_result,
)


def rbc_envelope_from_stack_analysis(
    analysis: StackAnalysis,
    *,
    calibration: CalibrationAssessment | None = None,
    estimated: RbcEstimatedOutput | None = None,
) -> RbcResultEnvelope | None:
    """Extract the typed envelope from a stack analysis when profile is RBC."""

    if str(getattr(analysis, "profile", "")) != "rbc":
        return None
    result = getattr(analysis, "rbc_result", None)
    if result is None or not isinstance(result, RbcAnalysisResult):
        return None
    return envelope_from_analysis_result(
        result,
        calibration=calibration,
        estimated=estimated,
    )


def rbc_envelope_payload(
    analysis: StackAnalysis,
    *,
    calibration: CalibrationAssessment | None = None,
    estimated: RbcEstimatedOutput | None = None,
) -> dict[str, object] | None:
    """JSON-ready envelope or None for non-RBC runs."""

    env = rbc_envelope_from_stack_analysis(
        analysis, calibration=calibration, estimated=estimated
    )
    return env.to_dict() if env is not None else None
