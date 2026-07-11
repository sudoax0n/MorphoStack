"""Packet 13 — calibrated 3D seed mapping and 2D/3D tracking-key parity."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from morphostack.core.export import analysis_rows, analysis_summary
from morphostack.core.mesh import scientific_mesh_from_authoritative_mask
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import (
    ObjectSeed,
    analyze_stack,
    authoritative_mask_from_analysis,
    mesh_contours_from_analysis,
)
from morphostack.core.seed_mapping import (
    DisplayLevelGeometry,
    SeedMappingError,
    WorldPointUm,
    assert_seed_roundtrip,
    geometry_from_level_payload,
    object_seed_to_world,
    radius_um_to_px,
    source_to_world,
    validate_seed_revision,
    world_to_object_seed,
    world_to_source_voxel,
)
from morphostack.core.seeded_vesicle import EXACT_TRACKING_ALGORITHM_VERSION, EXACT_TRACKING_MODE
from morphostack.core.stack_cache import make_tracking_cache_key, tracking_key_revision
from morphostack.core.stack_cache import path_source_identity

_PACKET13_ARTIFACT_DIR = (
    Path(__file__).resolve().parents[1]
    / ".agent-runs"
    / "architecture-reset-20260711"
    / "packet-13-seed"
)


def _geometry(
    *,
    factors=(2, 2, 2),
    source_shape=(40, 128, 128),
    source_vs=None,
    level=1,
    revision="path:/data/stack.tif|m1|s100",
    calibration_known=True,
) -> DisplayLevelGeometry:
    src = source_vs or VoxelSize(0.5, 0.5, 2.0)
    fz, fy, fx = factors
    level_vs = VoxelSize(src.x_um * fx, src.y_um * fy, src.z_um * fz)
    # Coarse shape (floor division style)
    sz, sy, sx = source_shape
    shape = (max(1, sz // fz), max(1, sy // fy), max(1, sx // fx))
    return DisplayLevelGeometry(
        level=level,
        shape_zyx=shape,
        factors_zyx=(fz, fy, fx),
        level_voxel_size=level_vs,
        source_shape_zyx=source_shape,
        source_voxel_size=src,
        source_revision=revision,
        calibration_known=calibration_known,
    )


def test_world_level_source_roundtrip_within_one_xy_voxel_exact_z():
    from morphostack.core.seed_mapping import SourceVoxel

    g = _geometry(factors=(4, 4, 2))
    # Source integer center → world → seed must recover exact integers.
    src_x, src_y, src_z = 64.0, 40.0, 11.0
    world = source_to_world(SourceVoxel(src_x, src_y, src_z), g)
    seed = world_to_object_seed(world, geometry=g, radius_px=12.0, clamp_z=False)
    assert seed.x == src_x
    assert seed.y == src_y
    assert seed.frame_index == int(src_z)
    assert seed.radius == 12.0
    assert seed.seed_origin == "viewer_3d"
    assert seed.radius_unit == "px"
    assert seed.source_revision == g.source_revision
    assert_seed_roundtrip(world, seed, g)


def test_anisotropic_spacing_does_not_skew_source_xy_index():
    g = _geometry(factors=(1, 1, 1), source_vs=VoxelSize(1.0, 1.0, 4.0))
    # World z = 20 µm → source z = 5 at 4 µm/voxel
    world = WorldPointUm(x_um=30.0, y_um=40.0, z_um=20.0)
    continuous = world_to_source_voxel(world, g)
    assert continuous.x == pytest.approx(30.0)
    assert continuous.y == pytest.approx(40.0)
    assert continuous.z == pytest.approx(5.0)
    seed = world_to_object_seed(world, geometry=g, radius_px=8.0)
    assert seed.frame_index == 5
    assert seed.x == 30
    assert seed.y == 40


def test_downsample_factors_map_level_center_to_source():
    g = _geometry(factors=(2, 2, 2), source_shape=(20, 64, 64))
    # Level voxel (10, 12, 3) → source (20, 24, 6)
    from morphostack.core.seed_mapping import LevelVoxel, level_to_source_voxel, level_voxel_to_world

    level = LevelVoxel(x=10.0, y=12.0, z=3.0)
    source = level_to_source_voxel(level, g)
    assert source.x == pytest.approx(20.0)
    assert source.y == pytest.approx(24.0)
    assert source.z == pytest.approx(6.0)
    world = level_voxel_to_world(level, g)
    seed = world_to_object_seed(world, geometry=g, radius_px=5.0)
    assert seed.x == 20
    assert seed.y == 24
    assert seed.frame_index == 6


def test_out_of_bounds_xy_rejected():
    g = _geometry(source_shape=(10, 32, 32))
    world = WorldPointUm(x_um=1000.0, y_um=1.0, z_um=1.0)
    with pytest.raises(SeedMappingError) as ei:
        world_to_object_seed(world, geometry=g, radius_px=5.0, clamp_z=False)
    assert ei.value.code == "out_of_bounds"


def test_stale_revision_rejected():
    g = _geometry(revision="path:/old|m1|s1")
    world = WorldPointUm(x_um=5.0, y_um=5.0, z_um=2.0)
    with pytest.raises(SeedMappingError) as ei:
        world_to_object_seed(
            world,
            geometry=g,
            radius_px=5.0,
            expected_source_revision="path:/new|m2|s2",
        )
    assert ei.value.code == "stale_revision"

    validate_seed_revision(seed_revision=None, current_revision="path:/x")  # ok
    with pytest.raises(SeedMappingError):
        validate_seed_revision(seed_revision="a", current_revision="b")


def test_unknown_calibration_blocks_radius_um_conversion():
    g = _geometry(calibration_known=False)
    with pytest.raises(SeedMappingError) as ei:
        radius_um_to_px(5.0, g.source_voxel_size, calibration_known=False)
    assert ei.value.code == "unknown_calibration"
    # Pixel radius path still works
    seed = world_to_object_seed(
        WorldPointUm(5.0, 5.0, 2.0), geometry=g, radius_px=7.0
    )
    assert seed.radius_unit == "px"
    assert seed.radius == 7.0


def test_2d_and_3d_equivalent_seeds_share_tracking_key():
    g = _geometry(factors=(2, 2, 2), revision="session:abc123")
    # Emulate a 2D click at source (48, 50) frame 8 radius 14
    seed_2d = ObjectSeed(
        x=48.0,
        y=50.0,
        frame_index=8,
        radius=14.0,
        seed_origin="ui_2d",
        radius_unit="px",
        source_revision=g.source_revision,
    )
    world = object_seed_to_world(seed_2d, g)
    seed_3d = world_to_object_seed(world, geometry=g, radius_px=14.0, clamp_z=False)
    assert seed_3d.x == seed_2d.x
    assert seed_3d.y == seed_2d.y
    assert seed_3d.frame_index == seed_2d.frame_index
    assert seed_3d.radius == seed_2d.radius

    gray_shape = g.source_shape_zyx
    key_kwargs = dict(
        stack_identity=g.source_revision or "session:abc123",
        gray_shape=gray_shape,
        profile="vesicle",
        tracking_mode=EXACT_TRACKING_MODE,
        algorithm_version=EXACT_TRACKING_ALGORITHM_VERSION,
    )
    key_2d = make_tracking_cache_key(
        seed_x=seed_2d.x,
        seed_y=seed_2d.y,
        seed_frame=seed_2d.frame_index,
        seed_radius=seed_2d.radius,
        **key_kwargs,
    )
    key_3d = make_tracking_cache_key(
        seed_x=seed_3d.x,
        seed_y=seed_3d.y,
        seed_frame=seed_3d.frame_index,
        seed_radius=seed_3d.radius,
        **key_kwargs,
    )
    assert key_2d == key_3d
    assert tracking_key_revision(key_2d) == tracking_key_revision(key_3d)
    # Provenance differs but must not affect key identity fields
    assert seed_2d.seed_origin != seed_3d.seed_origin


def test_seed_mapping_pick_transform_under_100ms():
    g = _geometry()
    world = WorldPointUm(12.3, 44.1, 6.0)
    t0 = time.perf_counter()
    for _ in range(200):
        world_to_object_seed(world, geometry=g, radius_px=10.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    # Budget is per interaction; 200 maps should still be well under 100 ms total on CI.
    assert elapsed_ms < 100.0


def test_geometry_from_level_payload_and_api_helpers():
    level = {
        "level": 2,
        "shape": [5, 32, 32],
        "dtype": "uint8",
        "axes": "ZYX",
        "voxel_size": {"x_um": 2.0, "y_um": 2.0, "z_um": 4.0},
        "downsample_from_source": [2, 2, 2],
        "nbytes": 5120,
    }
    spec = {
        "role": "display_volume",
        "source_revision": "session:xyz",
        "level": 2,
        "shape": [5, 32, 32],
        "dtype": "uint8",
        "axes": "zyx",
        "level_voxel_size": {"x_um": 2.0, "y_um": 2.0, "z_um": 4.0},
        "downsampling": {"factors_zyx": [2, 2, 2], "display_only": True},
        "display_only": True,
    }
    g = geometry_from_level_payload(
        level=level,
        display_volume_spec=spec,
        source_shape_zyx=(10, 64, 64),
        source_voxel_size=VoxelSize(1.0, 1.0, 2.0),
    )
    assert g.level == 2
    assert g.factors_zyx == (2, 2, 2)
    assert g.source_revision == "session:xyz"

    from morphostack.api.app import ObjectSeedRequest, to_object_seed, validate_object_seed_against_stack

    req = ObjectSeedRequest(
        x=10,
        y=12,
        frame_index=3,
        radius=9,
        seed_origin="viewer_3d",
        source_revision="session:xyz",
        radius_unit="px",
    )
    seed = to_object_seed(req)
    assert seed is not None
    assert seed.seed_origin == "viewer_3d"
    validate_object_seed_against_stack(
        seed, gray_shape=(10, 64, 64), current_source_revision="session:xyz"
    )
    with pytest.raises(ValueError, match="refresh"):
        validate_object_seed_against_stack(
            seed, gray_shape=(10, 64, 64), current_source_revision="session:other"
        )
    with pytest.raises(ValueError, match="radius_unit"):
        to_object_seed(
            ObjectSeedRequest(x=1, y=1, frame_index=0, radius=1, radius_unit="um")
        )


# ---------------------------------------------------------------------------
# End-to-end 2D vs 3D equivalent-seed scientific parity (same synthetic stack)
# ---------------------------------------------------------------------------


def _ring_frame(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = 1.0
    return frame


def _synthetic_vesicle_stack(
    *,
    n_z: int = 8,
    h: int = 64,
    w: int = 64,
    cx: float = 32.0,
    cy: float = 32.0,
    r_in: float = 10.0,
    r_out: float = 14.0,
) -> np.ndarray:
    """Stable hollow-ring stack that seeded exact tracking accepts on all Z."""

    return np.stack(
        [(_ring_frame(h, w, cx, cy, r_in, r_out) * 200).astype(np.uint8) for _ in range(n_z)],
        axis=0,
    )


def _equivalent_2d_3d_seeds(
    *,
    x: float,
    y: float,
    frame: int,
    radius: float,
    geometry: DisplayLevelGeometry,
) -> tuple[ObjectSeed, ObjectSeed]:
    seed_2d = ObjectSeed(
        x=float(x),
        y=float(y),
        frame_index=int(frame),
        radius=float(radius),
        seed_origin="ui_2d",
        radius_unit="px",
        source_revision=geometry.source_revision,
    )
    world = object_seed_to_world(seed_2d, geometry)
    seed_3d = world_to_object_seed(
        world,
        geometry=geometry,
        radius_px=float(radius),
        clamp_z=False,
        expected_source_revision=geometry.source_revision,
    )
    assert seed_3d.seed_origin == "viewer_3d"
    assert seed_3d.x == seed_2d.x
    assert seed_3d.y == seed_2d.y
    assert seed_3d.frame_index == seed_2d.frame_index
    assert seed_3d.radius == seed_2d.radius
    return seed_2d, seed_3d


def _contour_fingerprint(contour: np.ndarray | None) -> list[list[float]] | None:
    if contour is None:
        return None
    arr = np.asarray(contour, dtype=np.float64)
    return [[float(x), float(y)] for x, y in arr.reshape(-1, 2)]


def _tracking_record_dict(rec) -> dict:
    return {
        "frame_index": int(rec.frame_index),
        "tracked": bool(rec.tracked),
        "centroid_x": None if rec.centroid_x is None else float(rec.centroid_x),
        "centroid_y": None if rec.centroid_y is None else float(rec.centroid_y),
        "area_px": int(rec.area_px),
        "touches_roi_boundary": bool(rec.touches_roi_boundary),
        "likely_neighbor_merge": bool(rec.likely_neighbor_merge),
        "loss_reason": rec.loss_reason,
        "merge_suspect": bool(rec.merge_suspect),
        "merge_rejected": bool(rec.merge_rejected),
        "touches_seed_disk": bool(rec.touches_seed_disk),
        "method": rec.method,
    }


def _frame_science_dict(frame) -> dict:
    metrics = frame.metrics
    return {
        "frame_index": int(frame.frame_index),
        "method": frame.preview.method if frame.preview is not None else None,
        "requested_threshold": frame.requested_threshold,
        "effective_threshold": frame.effective_threshold,
        "threshold_semantics": frame.threshold_semantics,
        "threshold": frame.threshold,
        "has_contour": frame.contour is not None,
        "contour": _contour_fingerprint(frame.contour),
        "metrics": None
        if metrics is None
        else {
            "area_px2": float(metrics.area_px2),
            "perimeter_px": float(metrics.perimeter_px),
            "area_um2": float(metrics.area_um2),
            "perimeter_um": float(metrics.perimeter_um),
            "circularity": float(metrics.circularity),
            "aspect_ratio": float(metrics.aspect_ratio),
            "elongation": float(metrics.elongation),
            "deformation_index": float(metrics.deformation_index),
            "extent": float(metrics.extent),
            "equivalent_diameter_um": float(metrics.equivalent_diameter_um),
            "solidity": float(metrics.solidity),
        },
    }


def _assert_analyses_bit_identical(a2d, a3d, *, stack: np.ndarray, revision: str) -> dict:
    """Compare completed exact science products for 2D vs 3D seeds."""

    assert len(a2d.frames) == len(a3d.frames)
    assert a2d.profile == a3d.profile
    assert a2d.voxel_size.to_dict() == a3d.voxel_size.to_dict()

    # Per-frame methods, thresholds, contours, metrics
    frames_2d = []
    frames_3d = []
    for f2, f3 in zip(a2d.frames, a3d.frames, strict=True):
        d2 = _frame_science_dict(f2)
        d3 = _frame_science_dict(f3)
        frames_2d.append(d2)
        frames_3d.append(d3)
        assert d2 == d3, f"frame science mismatch at Z={f2.frame_index}: {d2} vs {d3}"
        if f2.contour is not None and f3.contour is not None:
            np.testing.assert_array_equal(np.asarray(f2.contour), np.asarray(f3.contour))

    # Tracking diagnostics / QC / merge decisions / centers / methods
    assert (a2d.tracking is None) == (a3d.tracking is None)
    tracking_2d = []
    tracking_3d = []
    if a2d.tracking is not None and a3d.tracking is not None:
        assert a2d.tracking.seed_frame_area_px == a3d.tracking.seed_frame_area_px
        assert len(a2d.tracking.records) == len(a3d.tracking.records)
        for r2, r3 in zip(a2d.tracking.records, a3d.tracking.records, strict=True):
            d2 = _tracking_record_dict(r2)
            d3 = _tracking_record_dict(r3)
            tracking_2d.append(d2)
            tracking_3d.append(d3)
            assert d2 == d3, f"tracking record mismatch: {d2} vs {d3}"

    # Authoritative mask + revision fingerprint
    auth_2d = authoritative_mask_from_analysis(
        a2d,
        shape=tuple(int(v) for v in stack.shape),
        source_revision=revision,
        method="exact_vesicle",
        algorithm_version=EXACT_TRACKING_ALGORITHM_VERSION,
    )
    auth_3d = authoritative_mask_from_analysis(
        a3d,
        shape=tuple(int(v) for v in stack.shape),
        source_revision=revision,
        method="exact_vesicle",
        algorithm_version=EXACT_TRACKING_ALGORITHM_VERSION,
    )
    np.testing.assert_array_equal(auth_2d.mask, auth_3d.mask)
    assert auth_2d.scientific_fingerprint == auth_3d.scientific_fingerprint
    assert auth_2d.analysis_result_revision == auth_3d.analysis_result_revision
    assert auth_2d.source_revision == auth_3d.source_revision
    assert auth_2d.is_accepted and auth_3d.is_accepted

    # Contour→mask stack identity (mesh raster source)
    c2 = mesh_contours_from_analysis(a2d)
    c3 = mesh_contours_from_analysis(a3d)
    assert len(c2) == len(c3)
    for ca, cb in zip(c2, c3, strict=True):
        if ca is None and cb is None:
            continue
        assert ca is not None and cb is not None
        np.testing.assert_array_equal(np.asarray(ca), np.asarray(cb))

    # Scientific mesh measurements (analysis mesh + authoritative path)
    assert (a2d.mesh is None) == (a3d.mesh is None)
    mesh_payload = None
    if a2d.mesh is not None and a3d.mesh is not None:
        assert a2d.mesh.surface_area_um2 == a3d.mesh.surface_area_um2
        assert a2d.mesh.volume_um3 == a3d.mesh.volume_um3
        assert a2d.mesh.equivalent_sphere_diameter_um == a3d.mesh.equivalent_sphere_diameter_um
        assert a2d.mesh.sphericity == a3d.mesh.sphericity
        mesh_payload = {
            "surface_area_um2": float(a2d.mesh.surface_area_um2),
            "volume_um3": float(a2d.mesh.volume_um3),
            "equivalent_sphere_diameter_um": float(a2d.mesh.equivalent_sphere_diameter_um),
            "sphericity": float(a2d.mesh.sphericity),
        }

    sci_2d = scientific_mesh_from_authoritative_mask(auth_2d)
    sci_3d = scientific_mesh_from_authoritative_mask(auth_3d)
    if sci_2d is not None or sci_3d is not None:
        assert sci_2d is not None and sci_3d is not None
        assert sci_2d.surface_area_um2 == sci_3d.surface_area_um2
        assert sci_2d.volume_um3 == sci_3d.volume_um3
        assert sci_2d.complete is True and sci_3d.complete is True

    # Final metrics tables / summary
    rows_2d = analysis_rows(a2d)
    rows_3d = analysis_rows(a3d)
    assert rows_2d == rows_3d
    summary_2d = analysis_summary(a2d)
    summary_3d = analysis_summary(a3d)
    assert summary_2d == summary_3d

    # Slice volume cross-check
    if a2d.slice_volume is not None or a3d.slice_volume is not None:
        assert a2d.slice_volume is not None and a3d.slice_volume is not None
        assert a2d.slice_volume.volume_um3 == a3d.slice_volume.volume_um3
        assert a2d.slice_volume.partial_volume_um3 == a3d.slice_volume.partial_volume_um3

    return {
        "frame_count": len(a2d.frames),
        "valid_frame_count": len(a2d.valid_frames),
        "frames": frames_2d,
        "tracking": tracking_2d,
        "authoritative_mask": {
            "scientific_fingerprint": auth_2d.scientific_fingerprint,
            "analysis_result_revision": auth_2d.analysis_result_revision,
            "source_revision": auth_2d.source_revision,
            "nonzero_voxels": int(np.count_nonzero(auth_2d.mask)),
            "shape": list(auth_2d.mask.shape),
        },
        "mesh": mesh_payload,
        "scientific_mesh": None
        if sci_2d is None
        else {
            "surface_area_um2": float(sci_2d.surface_area_um2),
            "volume_um3": float(sci_2d.volume_um3),
            "complete": bool(sci_2d.complete),
        },
        "rows": rows_2d,
        "summary": summary_2d,
    }


def test_e2e_2d_vs_3d_equivalent_seed_completed_tracking_parity(tmp_path):
    """Same synthetic stack: 2D seed vs mapped 3D seed → bit-identical science."""

    pytest.importorskip("skimage")
    stack = _synthetic_vesicle_stack()
    voxel = VoxelSize(0.5, 0.5, 2.0)
    revision = "array:packet13-e2e-parity"
    # factors (1,1,1) level-0 geometry (display level can be coarse; mapping still exact)
    geometry = DisplayLevelGeometry(
        level=0,
        shape_zyx=tuple(int(v) for v in stack.shape),  # type: ignore[arg-type]
        factors_zyx=(1, 1, 1),
        level_voxel_size=voxel,
        source_shape_zyx=tuple(int(v) for v in stack.shape),  # type: ignore[arg-type]
        source_voxel_size=voxel,
        source_revision=revision,
        calibration_known=True,
    )
    seed_2d, seed_3d = _equivalent_2d_3d_seeds(
        x=32.0, y=32.0, frame=0, radius=14.0, geometry=geometry
    )
    assert seed_2d.seed_origin == "ui_2d"
    assert seed_3d.seed_origin == "viewer_3d"

    key_2d = make_tracking_cache_key(
        stack_identity=revision,
        seed_x=seed_2d.x,
        seed_y=seed_2d.y,
        seed_frame=seed_2d.frame_index,
        seed_radius=seed_2d.radius,
        gray_shape=tuple(int(v) for v in stack.shape),
        profile="vesicle",
        tracking_mode=EXACT_TRACKING_MODE,
        algorithm_version=EXACT_TRACKING_ALGORITHM_VERSION,
    )
    key_3d = make_tracking_cache_key(
        stack_identity=revision,
        seed_x=seed_3d.x,
        seed_y=seed_3d.y,
        seed_frame=seed_3d.frame_index,
        seed_radius=seed_3d.radius,
        gray_shape=tuple(int(v) for v in stack.shape),
        profile="vesicle",
        tracking_mode=EXACT_TRACKING_MODE,
        algorithm_version=EXACT_TRACKING_ALGORITHM_VERSION,
    )
    assert key_2d == key_3d
    assert tracking_key_revision(key_2d) == tracking_key_revision(key_3d)

    analysis_2d = analyze_stack(
        stack,
        thresholds=50,
        voxel_size=voxel,
        object_seed=seed_2d,
        profile="vesicle",
        include_mesh=True,
        prefer_opencv=True,
    )
    analysis_3d = analyze_stack(
        stack,
        thresholds=50,
        voxel_size=voxel,
        object_seed=seed_3d,
        profile="vesicle",
        include_mesh=True,
        prefer_opencv=True,
    )

    # Sanity: exact path actually tracked
    assert analysis_2d.tracking is not None
    assert all(r.tracked for r in analysis_2d.tracking.records)
    assert analysis_2d.mesh is not None
    assert analysis_2d.valid_frames

    parity = _assert_analyses_bit_identical(
        analysis_2d, analysis_3d, stack=stack, revision=revision
    )

    # Also exercise a coarse-level mapping path (factors 2) without changing seed ints
    coarse = DisplayLevelGeometry(
        level=1,
        shape_zyx=(
            max(1, stack.shape[0] // 2),
            max(1, stack.shape[1] // 2),
            max(1, stack.shape[2] // 2),
        ),
        factors_zyx=(2, 2, 2),
        level_voxel_size=VoxelSize(voxel.x_um * 2, voxel.y_um * 2, voxel.z_um * 2),
        source_shape_zyx=tuple(int(v) for v in stack.shape),  # type: ignore[arg-type]
        source_voxel_size=voxel,
        source_revision=revision,
        calibration_known=True,
    )
    seed_2d_b, seed_3d_b = _equivalent_2d_3d_seeds(
        x=32.0, y=32.0, frame=0, radius=14.0, geometry=coarse
    )
    assert (seed_2d_b.x, seed_2d_b.y, seed_2d_b.frame_index, seed_2d_b.radius) == (
        seed_3d_b.x,
        seed_3d_b.y,
        seed_3d_b.frame_index,
        seed_3d_b.radius,
    )

    artifact = {
        "packet": 13,
        "test": "test_e2e_2d_vs_3d_equivalent_seed_completed_tracking_parity",
        "stack_shape": list(stack.shape),
        "voxel_size": voxel.to_dict(),
        "source_revision": revision,
        "seed_2d": {
            "x": seed_2d.x,
            "y": seed_2d.y,
            "frame_index": seed_2d.frame_index,
            "radius": seed_2d.radius,
            "seed_origin": seed_2d.seed_origin,
        },
        "seed_3d": {
            "x": seed_3d.x,
            "y": seed_3d.y,
            "frame_index": seed_3d.frame_index,
            "radius": seed_3d.radius,
            "seed_origin": seed_3d.seed_origin,
        },
        "tracking_key_revision": tracking_key_revision(key_2d),
        "parity": "bit_identical",
        "science": {
            "frame_count": parity["frame_count"],
            "valid_frame_count": parity["valid_frame_count"],
            "authoritative_mask": parity["authoritative_mask"],
            "mesh": parity["mesh"],
            "scientific_mesh": parity["scientific_mesh"],
            "summary": parity["summary"],
            # Keep rows compact: drop long contour lists from disk artifact summary
            "row_count": len(parity["rows"]),
            "first_row_method": parity["rows"][0].get("method") if parity["rows"] else None,
            "tracked_frames": sum(1 for t in parity["tracking"] if t["tracked"]),
            "methods": sorted({t["method"] for t in parity["tracking"] if t.get("method")}),
            "effective_thresholds": [
                f.get("effective_threshold") for f in parity["frames"]
            ],
        },
    }
    _PACKET13_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out = _PACKET13_ARTIFACT_DIR / "e2e-2d-3d-parity.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    # Full dump with contours for forensic review (optional secondary file)
    full = _PACKET13_ARTIFACT_DIR / "e2e-2d-3d-parity-full.json"
    full.write_text(
        json.dumps({**artifact, "frames": parity["frames"], "tracking": parity["tracking"]}, indent=2),
        encoding="utf-8",
    )
    assert out.is_file()


def test_e2e_2d_vs_3d_seed_api_analyze_parity(tmp_path):
    """HTTP /analyze: 2D vs 3D provenance seeds return identical science JSON fields."""

    pytest.importorskip("tifffile")
    from fastapi.testclient import TestClient

    from morphostack.api import create_app

    tifffile = pytest.importorskip("tifffile")
    stack = _synthetic_vesicle_stack()
    path = tmp_path / "packet13_parity.tif"
    tifffile.imwrite(path, stack, photometric="minisblack")
    revision = path_source_identity(path)
    voxel = {"x_um": 0.5, "y_um": 0.5, "z_um": 2.0}
    geometry = DisplayLevelGeometry(
        level=0,
        shape_zyx=tuple(int(v) for v in stack.shape),  # type: ignore[arg-type]
        factors_zyx=(1, 1, 1),
        level_voxel_size=VoxelSize(0.5, 0.5, 2.0),
        source_shape_zyx=tuple(int(v) for v in stack.shape),  # type: ignore[arg-type]
        source_voxel_size=VoxelSize(0.5, 0.5, 2.0),
        source_revision=revision,
        calibration_known=True,
    )
    seed_2d, seed_3d = _equivalent_2d_3d_seeds(
        x=32.0, y=32.0, frame=0, radius=14.0, geometry=geometry
    )

    client = TestClient(create_app())
    base = {
        "path": str(path),
        "threshold": 50,
        "profile": "vesicle",
        "voxel": voxel,
        "include_mesh": True,
        "prefer_opencv": True,
    }

    def _seed_body(seed: ObjectSeed) -> dict:
        return {
            "x": seed.x,
            "y": seed.y,
            "frame_index": seed.frame_index,
            "radius": seed.radius,
            "type": "circle",
            "seed_origin": seed.seed_origin,
            "source_revision": seed.source_revision,
            "radius_unit": "px",
        }

    r2 = client.post("/analyze", json={**base, "object_seed": _seed_body(seed_2d)})
    r3 = client.post("/analyze", json={**base, "object_seed": _seed_body(seed_3d)})
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 200, r3.text
    p2 = r2.json()
    p3 = r3.json()

    # Science fields must match; seed provenance may differ in object_seed payload.
    for key in (
        "frame_count",
        "valid_frame_count",
        "profile",
        "voxel_size",
        "summary",
        "mesh",
        "slice_volume",
        "rows",
        "tracking",
        "warnings",
    ):
        assert p2[key] == p3[key], f"API field {key} differs"

    # Manifest science subset: drop provenance seed + wall-clock timestamp.
    m2 = dict(p2["manifest"])
    m3 = dict(p3["manifest"])
    for m in (m2, m3):
        m.pop("object_seed", None)
        m.pop("created_at_utc", None)
    # source_sha256 / paths / science must match same file
    assert m2 == m3

    assert p2["object_seed"]["x"] == p3["object_seed"]["x"]
    assert p2["object_seed"]["y"] == p3["object_seed"]["y"]
    assert p2["object_seed"]["frame_index"] == p3["object_seed"]["frame_index"]
    assert p2["object_seed"]["radius"] == p3["object_seed"]["radius"]
    assert p2["object_seed"].get("seed_origin") == "ui_2d"
    assert p3["object_seed"].get("seed_origin") == "viewer_3d"

    # Stale 3D revision is rejected
    bad = client.post(
        "/analyze",
        json={
            **base,
            "object_seed": {**_seed_body(seed_3d), "source_revision": "session:stale-other"},
        },
    )
    assert bad.status_code == 400
    assert "refresh" in bad.json()["detail"].lower() or "revision" in bad.json()["detail"].lower()

    api_artifact = {
        "packet": 13,
        "test": "test_e2e_2d_vs_3d_seed_api_analyze_parity",
        "path": str(path),
        "source_revision": revision,
        "status_2d": r2.status_code,
        "status_3d": r3.status_code,
        "frame_count": p2["frame_count"],
        "valid_frame_count": p2["valid_frame_count"],
        "mesh": p2["mesh"],
        "summary": p2["summary"],
        "tracking_methods": [t.get("method") for t in (p2.get("tracking") or [])],
        "tracking_centroids": [
            (t.get("centroid_x"), t.get("centroid_y"), t.get("tracked"))
            for t in (p2.get("tracking") or [])
        ],
        "row_methods": [row.get("method") for row in p2["rows"]],
        "effective_thresholds": [row.get("effective_threshold") for row in p2["rows"]],
        "seed_origins": {
            "2d": p2["object_seed"].get("seed_origin"),
            "3d": p3["object_seed"].get("seed_origin"),
        },
        "stale_revision_status": bad.status_code,
        "parity": "api_science_fields_identical",
    }
    _PACKET13_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out = _PACKET13_ARTIFACT_DIR / "e2e-2d-3d-api-parity.json"
    out.write_text(json.dumps(api_artifact, indent=2, sort_keys=True), encoding="utf-8")
    assert out.is_file()
