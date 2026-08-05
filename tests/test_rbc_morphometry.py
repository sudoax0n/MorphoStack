"""RBC morphometry, QC capability gates, and capability-scoped results."""

from __future__ import annotations

import math

import numpy as np
import pytest

from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import ObjectSeed, analyze_stack
from morphostack.core.rbc_capabilities import calibration_from_override, unverified_calibration_from_values
from morphostack.core.rbc_metrics import (
    measure_rbc_occupancy,
    measure_rbc_projected_mask,
    validate_rbc_scientific_mesh,
)
from morphostack.core.rbc_models import (
    CalibrationAssessment,
    CalibrationAxis,
    RbcCapability,
    RbcAuthority,
    RbcQcIssue,
    RbcStackCandidate,
    RbcSliceTopology,
    RbcTopologyIssue,
)
from morphostack.core.rbc_qc import evaluate_rbc_reconstruction
from morphostack.core.rbc_result import build_rbc_analysis_result


VOXEL = VoxelSize(0.1, 0.1, 0.2)


def rotated_ellipse_mask(
    major_um: float,
    minor_um: float,
    angle_deg: float,
    voxel: VoxelSize = VOXEL,
    shape: tuple[int, int] = (160, 160),
) -> np.ndarray:
    h, w = shape
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    x_um = (xx - cx) * float(voxel.x_um)
    y_um = (yy - cy) * float(voxel.y_um)
    th = math.radians(angle_deg)
    xr = x_um * math.cos(th) + y_um * math.sin(th)
    yr = -x_um * math.sin(th) + y_um * math.cos(th)
    a = major_um / 2.0
    b = minor_um / 2.0
    return (xr / a) ** 2 + (yr / b) ** 2 <= 1.0


def ellipse_mask(major_um: float, minor_um: float, voxel: VoxelSize = VOXEL) -> np.ndarray:
    return rotated_ellipse_mask(major_um, minor_um, 0.0, voxel=voxel)


@pytest.mark.parametrize("angle", [0, 17, 43, 79])
def test_moment_axes_are_rotation_invariant(angle):
    mask = rotated_ellipse_mask(major_um=8.0, minor_um=5.0, angle_deg=angle, voxel=VOXEL)
    result = measure_rbc_projected_mask(mask, VOXEL)
    assert result.major_axis_um == pytest.approx(8.0, rel=0.05)
    assert result.minor_axis_um == pytest.approx(5.0, rel=0.05)
    assert result.aspect_ratio_L_over_W == pytest.approx(1.6, rel=0.06)


def test_static_elongation_uses_named_formula():
    result = measure_rbc_projected_mask(ellipse_mask(8.0, 4.0), VOXEL)
    assert result.static_elongation_index == pytest.approx((8.0 - 4.0) / (8.0 + 4.0), rel=0.05)
    # Legacy name deformation_index must not be the primary field.
    assert hasattr(result, "static_elongation_index")
    assert not hasattr(result, "deformation_index")


def _empty_candidate(**kwargs) -> RbcStackCandidate:
    base = dict(
        seed_frame_index=0,
        slices=(),
        occupancy_mask=None,
        valid_slice_indices=(),
        internal_gap_indices=(),
        issues=(),
        withheld=True,
        ok=False,
    )
    base.update(kwargs)
    return RbcStackCandidate(**base)


def _solid_occupancy(n_z: int = 9, xy: int = 48, radius: int = 12) -> np.ndarray:
    occ = np.zeros((n_z, xy, xy), dtype=bool)
    yy, xx = np.ogrid[:xy, :xy]
    disk = (yy - xy // 2) ** 2 + (xx - xy // 2) ** 2 <= radius**2
    # Leave empty caps at z=0 and z=n-1 for complete coverage.
    for z in range(1, n_z - 1):
        occ[z] = disk
    return occ


def _candidate_from_occupancy(
    occ: np.ndarray,
    *,
    issues: tuple = (),
    withheld: bool = False,
    gaps: tuple = (),
) -> RbcStackCandidate:
    valid = tuple(int(z) for z in range(occ.shape[0]) if np.any(occ[z]))
    slices = []
    for z in range(occ.shape[0]):
        if z in valid:
            slices.append(
                RbcSliceTopology(
                    frame_index=z,
                    outer_loop_xy=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
                    inner_loops_xy=(),
                    occupancy_mask=occ[z],
                    issues=(),
                    ok=True,
                    area_px=float(np.count_nonzero(occ[z])),
                )
            )
        else:
            slices.append(
                RbcSliceTopology(
                    frame_index=z,
                    outer_loop_xy=None,
                    inner_loops_xy=(),
                    occupancy_mask=None,
                    issues=(RbcTopologyIssue.EMPTY,),
                    ok=False,
                )
            )
    return RbcStackCandidate(
        seed_frame_index=valid[len(valid) // 2] if valid else 0,
        slices=tuple(slices),
        occupancy_mask=occ,
        valid_slice_indices=valid,
        internal_gap_indices=gaps,
        issues=issues,
        withheld=withheld,
        ok=not withheld and bool(valid),
    )


def _cal(verified: bool = True) -> CalibrationAssessment:
    if verified:
        return calibration_from_override(0.1, 0.1, 0.2, source_format="tiff")
    return unverified_calibration_from_values(0.1, 0.1, 0.2, source_format="tiff")


@pytest.mark.parametrize(
    ("case", "expected_capability", "reason"),
    [
        ("complete", RbcCapability.VALIDATED_3D_OCCUPANCY, None),
        ("missing_z_axis", RbcCapability.PIXEL_PREVIEW, RbcQcIssue.CALIBRATION_UNVERIFIED),
        ("touches_first_slice", RbcCapability.CALIBRATED_2D, RbcQcIssue.INCOMPLETE_CAP),
        ("internal_gap", RbcCapability.CALIBRATED_2D, RbcQcIssue.INTERNAL_GAP),
        ("lateral_clip", RbcCapability.CALIBRATED_2D, RbcQcIssue.LATERAL_CLIPPING),
        ("merge", RbcCapability.CALIBRATED_2D, RbcQcIssue.UNRESOLVED_MERGE),
    ],
)
def test_qc_capability_table(case, expected_capability, reason):
    cal = _cal(verified=True)
    occ = _solid_occupancy()
    candidate = _candidate_from_occupancy(occ)
    mesh_qc = None

    if case == "complete":
        mesh_qc, _ = validate_rbc_scientific_mesh(occ, VOXEL)
    elif case == "missing_z_axis":
        cal = _cal(verified=False)
    elif case == "touches_first_slice":
        occ[0] = occ[1]
        candidate = _candidate_from_occupancy(occ)
    elif case == "internal_gap":
        candidate = _candidate_from_occupancy(occ, issues=(RbcTopologyIssue.INTERNAL_GAP,), gaps=(3,))
    elif case == "lateral_clip":
        candidate = _candidate_from_occupancy(occ, issues=(RbcTopologyIssue.LATERAL_CLIPPING,))
    elif case == "merge":
        candidate = _candidate_from_occupancy(
            occ, issues=(RbcTopologyIssue.UNRESOLVED_MERGE,), withheld=True
        )

    result = evaluate_rbc_reconstruction(
        calibration=cal,
        candidate=candidate,
        stack_z=occ.shape[0],
        mesh_qc=mesh_qc,
    )
    assert result.capability is expected_capability
    assert reason is None or reason in result.issues


def test_biconcave_phantom_volume_matches_voxel_truth():
    voxel = VoxelSize(0.08, 0.08, 0.16)
    # Approximate solid disk stack (engineering phantom, not analytic RBC).
    n, size, radius = 11, 64, 16
    occ = np.zeros((n, size, size), dtype=bool)
    yy, xx = np.ogrid[:size, :size]
    disk = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= radius**2
    for z in range(1, n - 1):
        # mild z taper
        scale = 1.0 - 0.05 * abs(z - n // 2)
        r = max(4, int(radius * scale))
        d = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= r**2
        occ[z] = d
    expected = float(np.count_nonzero(occ)) * voxel.x_um * voxel.y_um * voxel.z_um
    result = measure_rbc_occupancy(occ, voxel)
    assert result.voxel_volume_um3 == pytest.approx(expected, rel=1e-9)
    assert result.mesh_volume_um3 == pytest.approx(expected, rel=0.12)


def test_calibrated_2d_result_has_no_3d_metrics():
    occ = _solid_occupancy()
    occ[0] = occ[1]  # incomplete cap
    candidate = _candidate_from_occupancy(occ)
    result = build_rbc_analysis_result(
        calibration=_cal(True),
        candidate=candidate,
        voxel=VOXEL,
        stack_z=occ.shape[0],
    )
    assert result.capability is RbcCapability.CALIBRATED_2D
    assert result.projected_metrics is not None
    assert result.volume_um3 is None
    assert result.surface_area_um2 is None
    assert result.dimple_thickness_um is None


def test_validated_occupancy_result_reports_measured_volume():
    occ = _solid_occupancy(n_z=11, xy=56, radius=14)
    candidate = _candidate_from_occupancy(occ)
    result = build_rbc_analysis_result(
        calibration=_cal(True),
        candidate=candidate,
        voxel=VOXEL,
        stack_z=occ.shape[0],
    )
    assert result.authority is RbcAuthority.MEASURED
    assert result.capability is RbcCapability.VALIDATED_3D_OCCUPANCY
    assert result.volume_um3 is not None and result.volume_um3 > 0
    assert result.dimple_thickness_um is None
    assert result.rim_thickness_um is None


def test_validator_reports_every_required_phantom(tmp_path):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_rbc_phantoms.py"
    spec = importlib.util.spec_from_file_location("validate_rbc_phantoms", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.run_rbc_phantom_validation(output_dir=tmp_path)
    assert set(report.cases) == set(mod.REQUIRED_CASES)
    assert report.biological_validation is False


def test_pipeline_attaches_rbc_result():
    pytest.importorskip("cv2")
    n, size = 9, 64
    stack = np.zeros((n, size, size), dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    disk = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= 14**2
    for z in range(1, n - 1):
        stack[z][disk] = 210
    seed = ObjectSeed(x=32.0, y=32.0, frame_index=4, radius=20.0)
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VOXEL,
        profile="rbc",
        prefer_opencv=False,
        object_seed=seed,
        source_path="cell.tif",
        calibration=_cal(True),
        include_mesh=True,
    )
    assert analysis.rbc_result is not None
    assert analysis.rbc_result.capability in (
        RbcCapability.CALIBRATED_2D,
        RbcCapability.VALIDATED_3D_OCCUPANCY,
        RbcCapability.PIXEL_PREVIEW,
    )
    if analysis.rbc_result.capability is not RbcCapability.VALIDATED_3D_OCCUPANCY:
        assert analysis.mesh is None or analysis.rbc_result.volume_um3 is None
