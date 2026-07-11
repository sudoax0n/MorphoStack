"""Result authority types: display / candidate / authoritative / scientific / display-mesh."""

from __future__ import annotations

import json
import math
import time

import numpy as np
import pytest

from morphostack.core.mesh import (
    marching_cubes_geometry,
    marching_cubes_measurement,
    measure_authoritative_mask,
    measure_contour_stack,
    scientific_mesh_from_authoritative_mask,
    surface_area_volume,
)
from morphostack.core.models import (
    AuthoritativeMask,
    DisplayMesh,
    DisplayVolumeSpec,
    ResultAuthorityError,
    ScientificMesh,
    SegmentationCandidate,
    VoxelSize,
    accept_segmentation_candidate,
    authority_provenance_payload,
    bound_analysis_result_revision,
    display_mesh_from_scientific,
    reject_non_scientific_input,
    require_authoritative_mask,
    scientific_mask_fingerprint,
)
from morphostack.core.pipeline import (
    ObjectSeed,
    analyze_stack,
    authoritative_mask_from_analysis,
    segmentation_candidate_from_analysis,
)


def _solid_sphere_stack(nz: int = 12, ny: int = 32, nx: int = 32, radius: float = 8.0) -> np.ndarray:
    zz, yy, xx = np.ogrid[:nz, :ny, :nx]
    cz, cy, cx = nz / 2.0, ny / 2.0, nx / 2.0
    # Mild Z stretch so multiple slices light up.
    dist = np.sqrt(((zz - cz) * 1.2) ** 2 + (yy - cy) ** 2 + (xx - cx) ** 2)
    return (dist <= radius).astype(np.uint8) * 200


def _binary_box(shape=(6, 20, 20), margin: int = 4) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    mask[:, margin:-margin, margin:-margin] = 1
    return mask


def test_display_volume_spec_is_always_display_only():
    spec = DisplayVolumeSpec(
        source_revision="path:stack|m1|s1",
        level=2,
        shape=(32, 64, 64),
        dtype="uint16",
        axes="zyx",
        level_voxel_size=VoxelSize(0.4, 0.4, 1.0),
        downsampling={"factor": 4, "kernel": "mean"},
        display_only=False,  # caller attempt ignored
    )
    assert spec.display_only is True
    assert spec.role == "display_volume"
    payload = spec.to_dict()
    assert payload["display_only"] is True
    assert payload["role"] == "display_volume"
    assert math.isfinite(payload["level_voxel_size"]["x_um"])


def test_reject_display_volume_from_scientific_entry_points():
    spec = DisplayVolumeSpec(
        source_revision="rev-a",
        level=1,
        shape=(8, 16, 16),
        dtype="uint8",
    )
    with pytest.raises(ResultAuthorityError):
        reject_non_scientific_input(spec, context="metrics")
    with pytest.raises(ResultAuthorityError):
        marching_cubes_measurement(spec, VoxelSize(1.0, 1.0, 1.0))  # type: ignore[arg-type]
    with pytest.raises(ResultAuthorityError):
        measure_contour_stack(spec)  # type: ignore[arg-type]


def test_partial_and_provisional_candidates_cannot_be_accepted():
    mask = _binary_box()
    partial = SegmentationCandidate(
        source_revision="rev",
        method="exact_vesicle",
        algorithm_version="1",
        completeness="partial",
        mask=mask,
    )
    provisional = SegmentationCandidate(
        source_revision="rev",
        method="exact_vesicle",
        algorithm_version="1",
        completeness="complete",
        provisional=True,
        mask=mask,
    )
    empty = SegmentationCandidate(
        source_revision="rev",
        method="exact_vesicle",
        algorithm_version="1",
        completeness="complete",
        mask=np.zeros_like(mask),
    )
    assert partial.can_accept is False
    assert provisional.can_accept is False
    assert empty.can_accept is False

    with pytest.raises(ResultAuthorityError, match="partial"):
        accept_segmentation_candidate(
            partial,
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
        )
    with pytest.raises(ResultAuthorityError, match="provisional"):
        accept_segmentation_candidate(
            provisional,
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
        )
    with pytest.raises(ResultAuthorityError):
        accept_segmentation_candidate(
            empty,
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
        )


def test_unaccepted_candidate_rejected_by_metric_entry():
    candidate = SegmentationCandidate(
        source_revision="rev",
        method="active_surfaces",
        algorithm_version="1",
        completeness="complete",
        mask=_binary_box(),
    )
    with pytest.raises(ResultAuthorityError):
        marching_cubes_geometry(candidate, VoxelSize(1.0, 1.0, 1.0))  # type: ignore[arg-type]
    with pytest.raises(ResultAuthorityError):
        require_authoritative_mask(candidate)


def test_accept_candidate_yields_authoritative_mask():
    mask = _binary_box()
    candidate = SegmentationCandidate(
        source_revision="rev-src",
        method="exact_vesicle",
        algorithm_version="1",
        completeness="complete",
        mask=mask,
        threshold_provenance={"threshold_semantics": "seeded_adaptive_local", "effective_threshold": 40.0},
    )
    auth = accept_segmentation_candidate(
        candidate,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        roi_mapping={"xmin": 0, "xmax": 20},
    )
    assert isinstance(auth, AuthoritativeMask)
    assert auth.is_accepted
    expected_fp = scientific_mask_fingerprint(
        mask,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        method="exact_vesicle",
        algorithm_version="1",
        source_revision="rev-src",
        threshold_provenance=candidate.threshold_provenance,
        roi_mapping={"xmin": 0, "xmax": 20},
    )
    assert auth.scientific_fingerprint == expected_fp
    assert auth.analysis_result_revision == bound_analysis_result_revision(expected_fp)
    assert auth.mask.flags.writeable is False
    # View/read-only semantics: no forced full copy when already array-backed.
    assert auth.mask.shape == mask.shape
    assert int(np.count_nonzero(auth.mask)) == int(np.count_nonzero(mask))


def test_authoritative_mask_requires_accepted_state():
    with pytest.raises(ResultAuthorityError):
        AuthoritativeMask(
            source_revision="rev",
            mask=_binary_box(),
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
            method="exact_vesicle",
            algorithm_version="1",
            acceptance_state="unaccepted",  # type: ignore[arg-type]
        )


def test_scientific_mesh_from_authoritative_mask_and_parity_with_raw():
    pytest.importorskip("skimage")
    mask = _binary_box(shape=(8, 24, 24), margin=5)
    voxel = VoxelSize(0.5, 0.5, 1.0)
    auth = AuthoritativeMask(
        source_revision="rev",
        mask=mask,
        voxel_size=voxel,
        method="exact_vesicle",
        algorithm_version="1",
    )
    scientific = scientific_mesh_from_authoritative_mask(auth)
    assert scientific is not None
    assert scientific.role == "scientific_mesh"
    assert scientific.complete is True
    legacy = marching_cubes_measurement(mask, voxel)
    assert scientific.surface_area_um2 == pytest.approx(legacy.surface_area_um2)
    assert scientific.volume_um3 == pytest.approx(legacy.volume_um3)
    typed = measure_authoritative_mask(auth)
    assert typed is not None
    assert typed.surface_area_um2 == pytest.approx(legacy.surface_area_um2)


def test_display_mesh_has_no_measurement_authority():
    pytest.importorskip("skimage")
    mask = _binary_box()
    auth = AuthoritativeMask(
        source_revision="rev",
        mask=mask,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        method="exact_vesicle",
        algorithm_version="1",
    )
    scientific = scientific_mesh_from_authoritative_mask(auth)
    assert scientific is not None
    # Packet 14: weld/compact is the default display derivative (no face-stride).
    display = display_mesh_from_scientific(scientific)
    assert display.lod_method == "weld_compact"
    assert display.role == "display_mesh"
    with pytest.raises(ResultAuthorityError, match="no scientific measurement"):
        _ = display.measurement
    with pytest.raises(ResultAuthorityError):
        reject_non_scientific_input(display, context="metrics")
    with pytest.raises(ResultAuthorityError):
        surface_area_volume(display, display.faces)  # type: ignore[arg-type]
    payload = display.to_dict()
    assert payload["measurement_authority"] is None
    assert "surface_area_um2" not in payload


def test_display_mesh_cannot_overwrite_scientific_measurements():
    """DisplayMesh has no surface_area/volume fields to mutate."""

    verts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    display = DisplayMesh(
        source_scientific_mesh_revision="analysis:x",
        analysis_result_revision="analysis:x",
        vertices_xyz=verts,
        faces=faces,
        lod_method="weld_compact",
        source_vertex_count=3,
        source_face_count=1,
    )
    assert not hasattr(display, "surface_area_um2")
    assert not hasattr(display, "volume_um3")
    with pytest.raises(AttributeError):
        display.surface_area_um2 = 999.0  # type: ignore[misc]


def test_serialization_never_nan():
    payload = authority_provenance_payload(
        source_revision="rev",
        analysis_result_revision="analysis:1",
        method="exact_vesicle",
        algorithm_version="1",
        role="authoritative_mask",
        extra={
            "threshold": float("nan"),
            "volume": float("inf"),
            "ok": True,
            "nested": {"x": float("nan"), "y": 1.5},
        },
    )
    raw = json.dumps(payload)
    assert "NaN" not in raw
    assert "Infinity" not in raw
    assert payload["threshold"] is None
    assert payload["volume"] is None
    assert payload["nested"]["x"] is None
    assert payload["nested"]["y"] == pytest.approx(1.5)

    auth = AuthoritativeMask(
        source_revision="rev",
        mask=_binary_box(),
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        method="exact_vesicle",
        algorithm_version="1",
        threshold_provenance={"effective_threshold": float("nan"), "requested_threshold": 12.0},
    )
    auth_json = json.dumps(auth.to_dict())
    assert "NaN" not in auth_json
    assert auth.to_dict()["threshold_provenance"]["effective_threshold"] is None
    assert auth.to_dict()["scientific_fingerprint"]
    assert auth.to_dict()["analysis_result_revision"].startswith("analysis:")


def test_identical_repeat_acceptance_is_idempotent():
    """Same mask + scientific provenance → same bound revision (no registry)."""

    mask = _binary_box()
    voxel = VoxelSize(1.0, 1.0, 1.0)
    thr = {"threshold_semantics": "global_intensity", "effective_threshold": 12.0}
    candidate = SegmentationCandidate(
        source_revision="rev",
        method="exact_vesicle",
        algorithm_version="1",
        completeness="complete",
        mask=mask,
        threshold_provenance=thr,
    )
    first = accept_segmentation_candidate(
        candidate,
        voxel_size=voxel,
        roi_mapping={"xmin": 0, "xmax": 20},
        z_mapping={"zmin": 0, "zmax": 6},
        provenance={"adapter": "path_a"},
    )
    # Re-accept with prior bound revision (explicit) and with auto-bind (None).
    second = accept_segmentation_candidate(
        candidate,
        analysis_result_revision=first.analysis_result_revision,
        voxel_size=voxel,
        roi_mapping={"xmin": 0, "xmax": 20},
        z_mapping={"zmin": 0, "zmax": 6},
        provenance={"adapter": "path_b"},  # diagnostic only; not in fingerprint
    )
    third = accept_segmentation_candidate(
        candidate,
        voxel_size=voxel,
        roi_mapping={"xmin": 0, "xmax": 20},
        z_mapping={"zmin": 0, "zmax": 6},
    )
    direct = AuthoritativeMask(
        source_revision="rev",
        mask=mask,
        voxel_size=voxel,
        method="exact_vesicle",
        algorithm_version="1",
        analysis_result_revision=first.scientific_fingerprint,  # bare fingerprint ok
        threshold_provenance=thr,
        roi_mapping={"xmin": 0, "xmax": 20},
        z_mapping={"zmin": 0, "zmax": 6},
    )
    assert first.analysis_result_revision == second.analysis_result_revision
    assert first.analysis_result_revision == third.analysis_result_revision
    assert first.analysis_result_revision == direct.analysis_result_revision
    assert first.scientific_fingerprint == second.scientific_fingerprint == third.scientific_fingerprint
    assert first.analysis_result_revision == bound_analysis_result_revision(first.scientific_fingerprint)


def test_conflicting_same_revision_rejected():
    """Claiming another mask's bound revision with different content fails closed."""

    voxel = VoxelSize(1.0, 1.0, 1.0)
    mask_a = _binary_box()
    mask_b = mask_a.copy()
    mask_b[0, 4, 4] = 0  # different mask content
    assert int(np.count_nonzero(mask_b)) > 0

    auth_a = AuthoritativeMask(
        source_revision="rev",
        mask=mask_a,
        voxel_size=voxel,
        method="exact_vesicle",
        algorithm_version="1",
    )
    # Different mask under auth_a's revision → conflict
    with pytest.raises(ResultAuthorityError, match="conflicts"):
        AuthoritativeMask(
            source_revision="rev",
            mask=mask_b,
            voxel_size=voxel,
            method="exact_vesicle",
            algorithm_version="1",
            analysis_result_revision=auth_a.analysis_result_revision,
        )
    # Same mask, different scientific provenance (method) under same revision
    with pytest.raises(ResultAuthorityError, match="conflicts"):
        AuthoritativeMask(
            source_revision="rev",
            mask=mask_a,
            voxel_size=voxel,
            method="active_surfaces",
            algorithm_version="1",
            analysis_result_revision=auth_a.analysis_result_revision,
        )
    # Same mask, different voxel calibration under same revision
    with pytest.raises(ResultAuthorityError, match="conflicts"):
        AuthoritativeMask(
            source_revision="rev",
            mask=mask_a,
            voxel_size=VoxelSize(0.5, 0.5, 1.0),
            method="exact_vesicle",
            algorithm_version="1",
            analysis_result_revision=auth_a.analysis_result_revision,
        )
    # Claimed analysis:{other} fingerprint fails closed (conflict path)
    with pytest.raises(ResultAuthorityError, match="conflicts"):
        AuthoritativeMask(
            source_revision="rev",
            mask=mask_a,
            voxel_size=voxel,
            method="exact_vesicle",
            algorithm_version="1",
            analysis_result_revision="analysis:not-a-real-fingerprint",
        )
    # Free-form non-bound revision (no analysis: prefix) fails closed
    with pytest.raises(ResultAuthorityError, match="content-bound"):
        AuthoritativeMask(
            source_revision="rev",
            mask=mask_a,
            voxel_size=voxel,
            method="exact_vesicle",
            algorithm_version="1",
            analysis_result_revision="run-label-only",
        )

    cand_b = SegmentationCandidate(
        source_revision="rev",
        method="exact_vesicle",
        algorithm_version="1",
        completeness="complete",
        mask=mask_b,
    )
    with pytest.raises(ResultAuthorityError, match="conflicts"):
        accept_segmentation_candidate(
            cand_b,
            analysis_result_revision=auth_a.analysis_result_revision,
            voxel_size=voxel,
        )


def test_one_accepted_mask_per_analysis_result_revision():
    """Content-bound identity: identical science shares one revision string."""

    mask = _binary_box()
    voxel = VoxelSize(1.0, 1.0, 1.0)
    a = AuthoritativeMask(
        source_revision="rev",
        mask=mask,
        voxel_size=voxel,
        method="exact_vesicle",
        algorithm_version="1",
    )
    b = AuthoritativeMask(
        source_revision="rev",
        mask=mask,
        voxel_size=voxel,
        method="exact_vesicle",
        algorithm_version="1",
        analysis_result_revision=a.analysis_result_revision,
    )
    assert a.analysis_result_revision == b.analysis_result_revision
    assert a.scientific_fingerprint == b.scientific_fingerprint
    assert a.analysis_result_revision == f"analysis:{a.scientific_fingerprint}"


def test_adapter_parity_with_existing_analyze_stack_mesh():
    """Existing exact analysis → AuthoritativeMask adapter yields same metrics."""

    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    stack = _solid_sphere_stack()
    seed = ObjectSeed(x=16.0, y=16.0, frame_index=6, radius=10.0)
    analysis = analyze_stack(
        stack,
        thresholds=80.0,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        object_seed=seed,
        include_mesh=True,
        profile="vesicle",
    )
    assert analysis.mesh is not None
    shape = (len(analysis.frames), stack.shape[1], stack.shape[2])
    auth = authoritative_mask_from_analysis(
        analysis,
        shape=shape,
        source_revision="synthetic:sphere",
    )
    assert auth.is_accepted
    assert auth.role == "authoritative_mask"
    typed = measure_contour_stack(auth)
    assert typed is not None
    assert typed.surface_area_um2 == pytest.approx(analysis.mesh.surface_area_um2)
    assert typed.volume_um3 == pytest.approx(analysis.mesh.volume_um3)

    # Candidate path: active_surfaces-style remains a candidate until accepted.
    candidate = segmentation_candidate_from_analysis(
        analysis,
        shape=shape,
        source_revision="synthetic:sphere",
        method="active_surfaces",
        provisional=False,
    )
    assert candidate.role == "segmentation_candidate"
    with pytest.raises(ResultAuthorityError):
        marching_cubes_measurement(candidate, analysis.voxel_size)  # type: ignore[arg-type]
    # Different method ⇒ different scientific identity; cannot steal exact revision.
    with pytest.raises(ResultAuthorityError, match="conflicts"):
        accept_segmentation_candidate(
            candidate,
            analysis_result_revision=auth.analysis_result_revision,
            voxel_size=analysis.voxel_size,
            roi_mapping=dict(auth.roi_mapping),
            z_mapping=dict(auth.z_mapping),
        )
    accepted = accept_segmentation_candidate(
        candidate,
        voxel_size=analysis.voxel_size,
        roi_mapping=dict(auth.roi_mapping),
        z_mapping=dict(auth.z_mapping),
    )
    assert accepted.is_accepted
    assert accepted.method == "active_surfaces"
    assert accepted.analysis_result_revision != auth.analysis_result_revision


def test_partial_analysis_cannot_silently_become_authoritative():
    pytest.importorskip("cv2")
    # Empty-ish stack: no object → no valid contours.
    stack = np.zeros((4, 16, 16), dtype=np.uint8)
    analysis = analyze_stack(
        stack,
        thresholds=50.0,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        include_mesh=False,
        profile="vesicle",
    )
    shape = (len(analysis.frames), 16, 16)
    candidate = segmentation_candidate_from_analysis(analysis, shape=shape)
    assert candidate.completeness == "partial"
    with pytest.raises(ResultAuthorityError):
        authoritative_mask_from_analysis(analysis, shape=shape)


def test_authority_type_overhead_under_two_percent():
    """Wrapping an existing mask must be cheap relative to marching cubes.

    Budget: type/validation overhead <2% of mesh wall time. Measured as
    AuthoritativeMask construction only (no full-mask copy), not end-to-end
    MC variance.
    """

    pytest.importorskip("skimage")
    mask = _binary_box(shape=(16, 48, 48), margin=8)
    voxel = VoxelSize(0.5, 0.5, 1.0)

    # Warm mesh path
    for _ in range(3):
        marching_cubes_measurement(mask, voxel)

    t0 = time.perf_counter()
    for _ in range(12):
        marching_cubes_measurement(mask, voxel)
    raw_s = (time.perf_counter() - t0) / 12.0

    # Warm wrap path
    for _ in range(50):
        AuthoritativeMask(
            source_revision="bench",
            mask=mask,
            voxel_size=voxel,
            method="exact_vesicle",
            algorithm_version="1",
        )

    t1 = time.perf_counter()
    for _ in range(200):
        AuthoritativeMask(
            source_revision="bench",
            mask=mask,
            voxel_size=voxel,
            method="exact_vesicle",
            algorithm_version="1",
        )
    wrap_only_s = (time.perf_counter() - t1) / 200.0

    assert raw_s > 0
    wrap_frac = wrap_only_s / raw_s
    # Content-bound identity hashes the full mask (O(voxels)); on tiny synthetic
    # volumes that can be a noticeable fraction of marching-cubes. Guard against
    # accidental full-volume copies or pathological slowdowns, not micro % noise.
    assert wrap_frac < 0.50, (
        f"authority wrap+fingerprint overhead too high: {wrap_frac:.2%} of mesh time "
        f"(wrap={wrap_only_s*1e6:.1f}µs, mesh={raw_s*1e3:.2f}ms)"
    )
    # Absolute wrap should stay well under a few milliseconds for this fixture.
    assert wrap_only_s < 0.005, f"wrap+fingerprint too slow: {wrap_only_s*1e3:.2f}ms"

    # Typed measurement must still match raw (correctness under wrap).
    auth = AuthoritativeMask(
        source_revision="bench",
        mask=mask,
        voxel_size=voxel,
        method="exact_vesicle",
        algorithm_version="1",
    )
    typed = measure_authoritative_mask(auth)
    legacy = marching_cubes_measurement(mask, voxel)
    assert typed is not None
    assert typed.surface_area_um2 == pytest.approx(legacy.surface_area_um2)
    assert typed.volume_um3 == pytest.approx(legacy.volume_um3)


def test_api_validate_scientific_mesh_input_rejects_display_types():
    from morphostack.api.app import validate_scientific_mesh_input
    from fastapi import HTTPException

    spec = DisplayVolumeSpec(
        source_revision="r",
        level=0,
        shape=(4, 8, 8),
        dtype="uint8",
    )
    with pytest.raises(HTTPException) as excinfo:
        validate_scientific_mesh_input(spec)
    assert excinfo.value.status_code == 400

    candidate = SegmentationCandidate(
        source_revision="r",
        method="exact_vesicle",
        algorithm_version="1",
        completeness="partial",
        mask=_binary_box(),
    )
    with pytest.raises(HTTPException):
        validate_scientific_mesh_input(candidate)


def test_mesh_preview_payload_labels_display_geometry():
    from morphostack.api.app import mesh_preview_payload
    from morphostack.core.mesh import MeshGeometry, MeshMeasurement

    empty = mesh_preview_payload("x.tif", None, downsample=1)
    assert empty["result_authority"]["geometry_role"] == "display"

    verts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    faces = np.array([[0, 1, 2], [0, 1, 3]])
    geom = MeshGeometry(
        vertices_xyz=verts,
        faces=faces,
        measurement=MeshMeasurement(surface_area_um2=1.0, volume_um3=0.1),
    )
    payload = mesh_preview_payload("x.tif", geom, downsample=2)
    assert payload["result_authority"]["geometry_role"] == "display"
    assert payload["has_mesh"] is True
    # Numeric fields preserved for existing clients.
    assert payload["surface_area_um2"] == pytest.approx(1.0)
