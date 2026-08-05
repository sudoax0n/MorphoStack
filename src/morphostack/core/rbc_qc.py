"""Central RBC reconstruction capability evaluator (fail-closed)."""

from __future__ import annotations

from morphostack.core.rbc_models import (
    CalibrationAssessment,
    EngineeringQcStatus,
    RbcAuthority,
    RbcCapability,
    RbcMeshQc,
    RbcQcIssue,
    RbcQcResult,
    RbcStackCandidate,
    RbcTopologyIssue,
)


def evaluate_rbc_reconstruction(
    *,
    calibration: CalibrationAssessment | None,
    candidate: RbcStackCandidate | None,
    stack_z: int,
    z_min: int = 0,
    z_max: int | None = None,
    mesh_qc: RbcMeshQc | None = None,
) -> RbcQcResult:
    """Assign the highest defensible RBC capability and withholding reasons.

    Capability ladder (highest first that is still allowed):
    - VALIDATED_3D_OCCUPANCY — complete calibrated occupancy + engineering mesh QC
    - CALIBRATED_2D — verified axes + at least one valid projected slice
    - PIXEL_PREVIEW — inspection only
    """

    issues: list[RbcQcIssue] = []
    notes: list[str] = []
    z_hi = int(stack_z - 1) if z_max is None else int(z_max) - 1
    z_lo = int(z_min)

    if calibration is None or not calibration.all_axes_verified:
        issues.append(RbcQcIssue.CALIBRATION_UNVERIFIED)

    if candidate is None or candidate.occupancy_mask is None or not candidate.valid_slice_indices:
        issues.append(RbcQcIssue.NO_OCCUPANCY)

    if candidate is not None:
        topo_issues = set(candidate.issues)
        if RbcTopologyIssue.SEED_SLICE_FAILED in topo_issues:
            issues.append(RbcQcIssue.SEED_SLICE_FAILED)
        if RbcTopologyIssue.INTERNAL_GAP in topo_issues or candidate.internal_gap_indices:
            issues.append(RbcQcIssue.INTERNAL_GAP)
        if RbcTopologyIssue.LATERAL_CLIPPING in topo_issues:
            issues.append(RbcQcIssue.LATERAL_CLIPPING)
        if RbcTopologyIssue.UNRESOLVED_MERGE in topo_issues or candidate.withheld:
            # withheld may also be empty; merge is explicit when present
            if RbcTopologyIssue.UNRESOLVED_MERGE in topo_issues:
                issues.append(RbcQcIssue.UNRESOLVED_MERGE)
        if any(
            t in topo_issues
            for t in (
                RbcTopologyIssue.MULTIPLE_OUTER_COMPONENTS,
                RbcTopologyIssue.UNSUPPORTED_NESTING,
                RbcTopologyIssue.RASTER_MISMATCH,
            )
        ):
            issues.append(RbcQcIssue.TOPOLOGY_FAILED)

        valid = list(candidate.valid_slice_indices)
        if valid:
            if min(valid) <= z_lo or max(valid) >= z_hi:
                issues.append(RbcQcIssue.INCOMPLETE_CAP)
                notes.append(
                    f"valid Z range [{min(valid)}, {max(valid)}] touches stack bounds "
                    f"[{z_lo}, {z_hi}]"
                )
        # Per-slice lateral clipping
        if any(RbcTopologyIssue.LATERAL_CLIPPING in s.issues for s in candidate.slices if s.ok):
            if RbcQcIssue.LATERAL_CLIPPING not in issues:
                issues.append(RbcQcIssue.LATERAL_CLIPPING)

    if mesh_qc is not None and not mesh_qc.ok:
        for iss in mesh_qc.issues:
            if iss not in issues:
                issues.append(iss)
        if RbcQcIssue.MESH_INVALID not in issues and RbcQcIssue.VOLUME_DISAGREEMENT not in issues:
            issues.append(RbcQcIssue.MESH_INVALID)

    # Deduplicate preserving order
    ordered = tuple(dict.fromkeys(issues))

    # Capability assignment
    has_cal = calibration is not None and calibration.all_axes_verified
    has_slices = (
        candidate is not None
        and bool(candidate.valid_slice_indices)
        and candidate.occupancy_mask is not None
    )

    hard_block_2d = {
        RbcQcIssue.CALIBRATION_UNVERIFIED,
        RbcQcIssue.NO_OCCUPANCY,
        RbcQcIssue.SEED_SLICE_FAILED,
    }
    block_3d = {
        RbcQcIssue.CALIBRATION_UNVERIFIED,
        RbcQcIssue.NO_OCCUPANCY,
        RbcQcIssue.SEED_SLICE_FAILED,
        RbcQcIssue.INCOMPLETE_CAP,
        RbcQcIssue.INTERNAL_GAP,
        RbcQcIssue.LATERAL_CLIPPING,
        RbcQcIssue.UNRESOLVED_MERGE,
        RbcQcIssue.TOPOLOGY_FAILED,
        RbcQcIssue.MESH_INVALID,
        RbcQcIssue.VOLUME_DISAGREEMENT,
    }

    if not has_cal or not has_slices or any(i in hard_block_2d for i in ordered):
        capability = RbcCapability.PIXEL_PREVIEW
        authority = RbcAuthority.WITHHELD
        eng = EngineeringQcStatus.FAIL if ordered else EngineeringQcStatus.INCONCLUSIVE
    elif any(i in block_3d for i in ordered):
        capability = RbcCapability.CALIBRATED_2D
        authority = RbcAuthority.MEASURED
        eng = EngineeringQcStatus.FAIL if ordered else EngineeringQcStatus.PASS
        # Soft 3D blocks still yield measured 2D
        if ordered and all(i in block_3d - hard_block_2d for i in ordered):
            eng = EngineeringQcStatus.PASS
    else:
        # Mesh QC required for validated 3D occupancy when mesh_qc provided.
        if mesh_qc is not None and not mesh_qc.ok:
            capability = RbcCapability.CALIBRATED_2D
            authority = RbcAuthority.MEASURED
            eng = EngineeringQcStatus.FAIL
        else:
            capability = RbcCapability.VALIDATED_3D_OCCUPANCY
            authority = RbcAuthority.MEASURED
            eng = EngineeringQcStatus.PASS

    return RbcQcResult(
        capability=capability,
        authority=authority,
        engineering_qc=eng,
        issues=ordered,
        notes=tuple(notes),
    )
