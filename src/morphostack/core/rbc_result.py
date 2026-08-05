"""Assemble capability-scoped RBC analysis results."""

from __future__ import annotations

from morphostack.core.models import VoxelSize
from morphostack.core.rbc_metrics import (
    best_projected_slice_mask,
    measure_rbc_projected_mask,
    validate_rbc_scientific_mesh,
)
from morphostack.core.rbc_models import (
    CalibrationAssessment,
    RbcAnalysisResult,
    RbcAuthority,
    RbcCapability,
    RbcStackCandidate,
)
from morphostack.core.rbc_qc import evaluate_rbc_reconstruction


def build_rbc_analysis_result(
    *,
    calibration: CalibrationAssessment | None,
    candidate: RbcStackCandidate | None,
    voxel: VoxelSize,
    stack_z: int,
    z_min: int = 0,
    z_max: int | None = None,
) -> RbcAnalysisResult:
    """Run QC + morphometry and return capability-scoped fields only."""

    mesh_qc = None
    cross = None
    occupancy = candidate.occupancy_mask if candidate is not None else None

    # Mesh QC only attempted when occupancy looks complete enough to try.
    if occupancy is not None and candidate is not None and candidate.valid_slice_indices:
        try:
            mesh_qc, cross = validate_rbc_scientific_mesh(occupancy, voxel)
        except Exception:
            mesh_qc = None
            cross = None

    qc = evaluate_rbc_reconstruction(
        calibration=calibration,
        candidate=candidate,
        stack_z=stack_z,
        z_min=z_min,
        z_max=z_max,
        mesh_qc=mesh_qc,
    )

    projected = None
    if (
        qc.capability
        in (
            RbcCapability.CALIBRATED_2D,
            RbcCapability.VALIDATED_3D_OCCUPANCY,
            RbcCapability.VALIDATED_3D_SURFACE,
        )
        and occupancy is not None
    ):
        slice_mask = best_projected_slice_mask(occupancy)
        if slice_mask is not None:
            projected = measure_rbc_projected_mask(slice_mask, voxel)

    volume_um3 = None
    surface_area_um2 = None
    voxel_volume_um3 = None
    mesh_volume_um3 = None
    rel = None

    if qc.capability is RbcCapability.VALIDATED_3D_OCCUPANCY and cross is not None:
        volume_um3 = cross.voxel_volume_um3
        voxel_volume_um3 = cross.voxel_volume_um3
        mesh_volume_um3 = cross.mesh_volume_um3
        surface_area_um2 = cross.surface_area_um2
        rel = cross.relative_disagreement
        # Prefer mesh volume when both available and mesh QC passed.
        if mesh_qc is not None and mesh_qc.ok and mesh_volume_um3 is not None:
            volume_um3 = mesh_volume_um3

    authority = qc.authority
    if projected is None and qc.capability is RbcCapability.PIXEL_PREVIEW:
        authority = RbcAuthority.WITHHELD

    methods = {
        "projected": "rbc_projected_moments_v1",
        "occupancy": "rbc_occupancy_volume_v1",
        "topology": "rbc_topology_v1",
        "qc": "rbc_reconstruction_qc_v1",
    }

    return RbcAnalysisResult(
        capability=qc.capability,
        authority=authority,
        engineering_qc=qc.engineering_qc,
        projected_metrics=projected,
        volume_um3=volume_um3,
        surface_area_um2=surface_area_um2,
        voxel_volume_um3=voxel_volume_um3,
        mesh_volume_um3=mesh_volume_um3,
        volume_relative_disagreement=rel,
        dimple_thickness_um=None,
        rim_thickness_um=None,
        issues=tuple(i.value for i in qc.issues),
        method_versions=methods,
        mesh_qc=mesh_qc,
    )
