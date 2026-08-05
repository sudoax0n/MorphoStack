"""RBC capability contracts and shared input gate."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from morphostack.core.io import load_image_stack
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import ObjectSeed, analyze_stack
from morphostack.core.rbc_capabilities import (
    calibration_from_override,
    evaluate_rbc_input,
    unverified_calibration_from_values,
)
from morphostack.core.rbc_models import (
    CalibrationAssessment,
    CalibrationAxis,
    RbcAuthority,
    RbcCapability,
    RbcInputRefused,
    RbcRefusalCode,
    RbcSignalSemantics,
)
from morphostack.core import io


def test_calibration_requires_all_three_verified_axes():
    assessment = CalibrationAssessment(
        x=CalibrationAxis(0.11, "metadata", True),
        y=CalibrationAxis(0.11, "metadata", True),
        z=CalibrationAxis(1.0, "placeholder", False),
        source_format="ome-tiff",
    )
    assert not assessment.all_axes_verified


def test_estimated_authority_is_not_measured():
    assert not RbcAuthority.ESTIMATED.is_measured
    assert RbcAuthority.MEASURED.is_measured


def test_signal_semantics_defaults_unknown():
    assessment = CalibrationAssessment(
        x=CalibrationAxis(0.1, "override", True),
        y=CalibrationAxis(0.1, "override", True),
        z=CalibrationAxis(0.3, "override", True),
        source_format="tiff",
    )
    assert assessment.signal_semantics is RbcSignalSemantics.UNKNOWN


def _seed() -> ObjectSeed:
    return ObjectSeed(x=2.0, y=2.0, frame_index=0, radius=3.0)


@pytest.mark.parametrize(
    ("suffix", "manual", "seeded", "allowed", "measured_allowed", "reason"),
    [
        # Uncalibrated LSM: analysis allowed, MEASURED blocked (ESTIMATED path).
        (".lsm", False, True, True, False, RbcRefusalCode.LSM_REQUIRES_CONVERSION_OR_MANUAL),
        (".lsm", True, True, True, True, None),
        (".ome.tif", False, False, False, False, RbcRefusalCode.SEED_REQUIRED),
        (".ome.tif", True, True, True, True, None),
        (".tif", False, True, True, False, RbcRefusalCode.UNVERIFIED_CONVERTED_METADATA),
        (".tif", True, True, True, True, None),
    ],
)
def test_rbc_input_gate(suffix, manual, seeded, allowed, measured_allowed, reason):
    if manual:
        calibration = calibration_from_override(0.1, 0.1, 0.3, source_format="test")
    else:
        calibration = unverified_calibration_from_values(
            1.0, 1.0, 1.0, source_format="test", source="default"
        )
    decision = evaluate_rbc_input(
        source_path=Path(f"cell{suffix}"),
        calibration=calibration,
        object_seed=_seed() if seeded else None,
    )
    assert decision.allowed is allowed
    assert decision.measured_allowed is measured_allowed
    assert reason is None or reason in decision.reasons


def test_partial_tiff_metadata_does_not_verify_missing_z(monkeypatch, tmp_path):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    partial = CalibrationAssessment(
        x=CalibrationAxis(0.5, "metadata", True),
        y=CalibrationAxis(0.5, "metadata", True),
        z=CalibrationAxis(1.0, "placeholder", False),
        source_format="tiff",
    )
    monkeypatch.setattr(io, "read_tiff_axes", lambda path, source_format=None: (raw, partial))
    stack = load_image_stack(tmp_path / "partial.tif")
    assert stack.calibration.x.verified
    assert stack.calibration.y.verified
    assert not stack.calibration.z.verified
    assert stack.calibration.z.source == "placeholder"
    assert not stack.calibration.all_axes_verified


def test_manual_override_verifies_all_axes(monkeypatch, tmp_path):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    monkeypatch.setattr(io, "read_tiff_axes", lambda path, source_format=None: (raw, None))
    stack = load_image_stack(
        tmp_path / "cell.lsm",
        voxel_override=VoxelSize(0.1, 0.1, 0.3),
    )
    assert stack.calibration.all_axes_verified
    assert {
        stack.calibration.x.source,
        stack.calibration.y.source,
        stack.calibration.z.source,
    } == {"override"}


def test_analyze_stack_rbc_requires_seed_and_calibration():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    with pytest.raises(RbcInputRefused) as excinfo:
        analyze_stack(
            stack,
            thresholds=100,
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
            profile="rbc",
            prefer_opencv=False,
        )
    assert RbcRefusalCode.SEED_REQUIRED in excinfo.value.decision.reasons


def test_analyze_stack_rbc_accepts_seed_with_verified_calibration():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    cal = calibration_from_override(1.0, 1.0, 1.0, source_format="tiff")
    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="rbc",
        prefer_opencv=False,
        object_seed=_seed(),
        source_path="cell.tif",
        calibration=cal,
    )
    assert result.profile == "rbc"
    assert result.frames[0].profile == "rbc"


def test_analyze_stack_uncalibrated_lsm_yields_estimated_mesh():
    n, size = 9, 32
    stack = np.zeros((n, size, size), dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    disk = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= 8**2
    for z in range(1, n - 1):
        stack[z][disk] = 210
    cal = unverified_calibration_from_values(1.0, 1.0, 1.0, source_format="lsm", source="default")
    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="rbc",
        prefer_opencv=False,
        object_seed=ObjectSeed(x=16.0, y=16.0, frame_index=4, radius=12.0),
        source_path="cell.lsm",
        calibration=cal,
        include_mesh=True,
    )
    assert result.rbc_result is not None
    assert result.rbc_result.authority is RbcAuthority.ESTIMATED
    assert result.rbc_result.volume_um3 is None
    assert result.rbc_result.projected_metrics is None
    assert result.rbc_result.estimated is not None
    assert result.rbc_result.estimated.authority is RbcAuthority.ESTIMATED
    assert "lsm_requires_conversion_or_manual_calibration" in result.rbc_issues
    assert result.mesh is not None  # display mesh present


def test_analyze_stack_vesicle_unaffected_without_seed():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="vesicle",
        prefer_opencv=False,
    )
    assert result.profile == "vesicle"
    assert RbcCapability.CALIBRATED_2D.value == "2D_OUTER_CONTOUR"
