"""Shared RBC input capability evaluation (pure, no I/O)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from morphostack.core.rbc_models import (
    REFUSAL_GUIDANCE,
    CalibrationAssessment,
    CalibrationAxis,
    RbcCapability,
    RbcInputDecision,
    RbcRefusalCode,
    RbcSignalSemantics,
)


def calibration_from_override(
    x_um: float,
    y_um: float,
    z_um: float,
    *,
    source_format: str,
    signal_semantics: RbcSignalSemantics = RbcSignalSemantics.UNKNOWN,
) -> CalibrationAssessment:
    """Build a fully verified assessment from explicit manual X/Y/Z values."""

    return CalibrationAssessment(
        x=CalibrationAxis(float(x_um), "override", True),
        y=CalibrationAxis(float(y_um), "override", True),
        z=CalibrationAxis(float(z_um), "override", True),
        source_format=source_format,
        signal_semantics=signal_semantics,
    )


def unverified_calibration_from_values(
    x_um: float | None,
    y_um: float | None,
    z_um: float | None,
    *,
    source_format: str,
    source: str = "unknown",
) -> CalibrationAssessment:
    """Synthesize an assessment when only effective spacing is known."""

    def axis(value: float | None) -> CalibrationAxis:
        return CalibrationAxis(value, source, False)

    return CalibrationAssessment(
        x=axis(x_um),
        y=axis(y_um),
        z=axis(z_um),
        source_format=source_format,
    )


def _source_is_direct_lsm(source_path: Path) -> bool:
    name = source_path.name.lower()
    return source_path.suffix.lower() == ".lsm" or name.endswith(".lsm")


def evaluate_rbc_input(
    *,
    source_path: Path | str,
    calibration: CalibrationAssessment,
    object_seed: Any | None,
) -> RbcInputDecision:
    """Evaluate whether RBC analysis may start.

    Pure function: no file I/O, no global session state. Callers pass the
    loaded stack path, per-axis calibration assessment, and optional seed.

    Hard block: missing seed.
    Soft block (measured only): uncalibrated LSM / incomplete axes — analysis
    may continue for ESTIMATED visualization after disclaimer.
    """

    path = Path(source_path)
    reasons: list[RbcRefusalCode] = []

    if object_seed is None:
        reasons.append(RbcRefusalCode.SEED_REQUIRED)

    if _source_is_direct_lsm(path) and not calibration.all_axes_from_override:
        reasons.append(RbcRefusalCode.LSM_REQUIRES_CONVERSION_OR_MANUAL)
    elif not calibration.all_axes_verified:
        # Converted or native TIFF/CZI with incomplete provenance.
        if path.suffix.lower() in {".tif", ".tiff"} or ".ome." in path.name.lower():
            reasons.append(RbcRefusalCode.UNVERIFIED_CONVERTED_METADATA)
        else:
            reasons.append(RbcRefusalCode.INCOMPLETE_AXIS_CALIBRATION)

    hard = any(code is RbcRefusalCode.SEED_REQUIRED for code in reasons)
    measured_allowed = not reasons or (
        not hard
        and RbcRefusalCode.LSM_REQUIRES_CONVERSION_OR_MANUAL not in reasons
        and RbcRefusalCode.INCOMPLETE_AXIS_CALIBRATION not in reasons
        and RbcRefusalCode.UNVERIFIED_CONVERTED_METADATA not in reasons
    )
    # Soft cal issues still allow segmentation when seed is present.
    allowed = not hard

    if reasons:
        guidance_parts = [REFUSAL_GUIDANCE[code] for code in reasons]
        return RbcInputDecision(
            allowed=allowed,
            measured_allowed=measured_allowed and allowed,
            reasons=tuple(reasons),
            capability=(
                RbcCapability.PIXEL_PREVIEW
                if not measured_allowed
                else RbcCapability.CALIBRATED_2D
            ),
            guidance=" ".join(guidance_parts),
        )

    return RbcInputDecision(
        allowed=True,
        measured_allowed=True,
        reasons=(),
        capability=RbcCapability.CALIBRATED_2D,
        guidance="",
    )
