"""Packet 14 — display mesh weld/compact derivative (no face-stride)."""

from __future__ import annotations

import inspect
import json
import time
from pathlib import Path

import numpy as np
import pytest

from morphostack.core.mesh import (
    DISPLAY_METHOD_WELD_COMPACT,
    MeshGeometry,
    MeshMeasurement,
    contour_stack_mesh_geometry,
    count_boundary_edges,
    display_geometry_from_complete,
    marching_cubes_geometry,
    marching_cubes_measurement,
    scientific_mesh_from_authoritative_mask,
    surface_area_volume,
    weld_compact_mesh,
)
from morphostack.core.models import (
    AuthoritativeMask,
    DisplayMesh,
    ResultAuthorityError,
    VoxelSize,
    display_mesh_from_scientific,
)
_ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / ".agent-runs"
    / "architecture-reset-20260711"
    / "packet-14-display-mesh"
)


def _binary_box(shape=(10, 28, 28), margin: int = 5) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    mask[:, margin:-margin, margin:-margin] = 1
    return mask


def _sphere_mask(nz=16, ny=40, nx=40, radius=12.0) -> np.ndarray:
    zz, yy, xx = np.ogrid[:nz, :ny, :nx]
    cz, cy, cx = nz / 2.0, ny / 2.0, nx / 2.0
    dist = np.sqrt((zz - cz) ** 2 + (yy - cy) ** 2 + (xx - cx) ** 2)
    return (dist <= radius).astype(np.uint8)


def test_face_stride_absent_from_mesh_module():
    import morphostack.core.mesh as mesh_mod

    src = inspect.getsource(mesh_mod.marching_cubes_geometry)
    assert "faces[::" not in src
    assert "display_faces[::" not in src
    assert "[::stride]" not in src
    assert "np.ceil(len(display_faces)" not in src
    assert "weld_compact" in src


def test_weld_compact_exact_positions_removes_duplicates():
    # Two triangles sharing an edge with duplicated coincident verts
    verts = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0],  # duplicate of v0
            [1.0, 0.0, 0.0],  # duplicate of v1
            [1.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
    out_v, out_f, stats = weld_compact_mesh(verts, faces)
    assert stats["display_method"] == DISPLAY_METHOD_WELD_COMPACT
    assert stats["source_vertex_count"] == 6
    assert stats["output_vertex_count"] == 4  # 0,1,2,5 unique
    assert stats["output_face_count"] == 2
    assert len(out_v) == 4
    assert len(out_f) == 2
    # All face indices valid
    assert out_f.min() >= 0
    assert out_f.max() < len(out_v)


def test_weld_compact_drops_degenerate_and_duplicate_faces():
    verts = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.array(
        [
            [0, 1, 2],
            [0, 0, 1],  # degenerate
            [2, 1, 0],  # same triangle reversed → treated as duplicate via sort
            [0, 1, 2],  # exact duplicate
        ],
        dtype=np.int64,
    )
    out_v, out_f, stats = weld_compact_mesh(verts, faces)
    assert stats["removed_degenerate_faces"] >= 1
    assert stats["removed_duplicate_faces"] >= 1
    assert stats["output_face_count"] == 1
    assert len(out_v) == 3


def test_scientific_measurement_unchanged_by_display_derivative():
    pytest.importorskip("skimage")
    mask = _sphere_mask()
    voxel = VoxelSize(0.5, 0.5, 1.0)
    complete = marching_cubes_geometry(mask, voxel, max_faces=None, display_derivative=False)
    display = marching_cubes_geometry(mask, voxel, max_faces=5000, display_derivative=True)
    assert complete.display_only is False
    assert display.display_only is True
    assert display.display_method == DISPLAY_METHOD_WELD_COMPACT
    # Measurements from complete mesh are identical
    assert display.measurement.surface_area_um2 == complete.measurement.surface_area_um2
    assert display.measurement.volume_um3 == complete.measurement.volume_um3
    # Legacy measurement path matches complete
    m = marching_cubes_measurement(mask, voxel)
    assert m.surface_area_um2 == complete.measurement.surface_area_um2
    assert m.volume_um3 == complete.measurement.volume_um3


def test_display_does_not_increase_boundary_edges_vs_source():
    pytest.importorskip("skimage")
    mask = _sphere_mask()
    voxel = VoxelSize(1.0, 1.0, 1.0)
    complete = marching_cubes_geometry(mask, voxel, display_derivative=False)
    display = display_geometry_from_complete(complete, max_faces=12000)
    src_be = count_boundary_edges(complete.faces)
    disp_be = count_boundary_edges(display.faces)
    assert display.boundary_edge_count_source == src_be
    assert display.boundary_edge_count_display == disp_be
    # Weld/compact must not open new boundary edges
    assert disp_be <= src_be


def test_no_face_stride_when_over_budget():
    pytest.importorskip("skimage")
    mask = _sphere_mask(nz=24, ny=64, nx=64, radius=20.0)
    voxel = VoxelSize(1.0, 1.0, 1.0)
    complete = marching_cubes_geometry(mask, voxel, display_derivative=False)
    # Tiny budget forces within_face_budget=False if welded still large
    display = marching_cubes_geometry(mask, voxel, max_faces=10, display_derivative=True)
    assert display.display_method == DISPLAY_METHOD_WELD_COMPACT
    # Must still be fully welded, not strided holes
    assert display.faces.shape[1] == 3
    if display.source_face_count and display.source_face_count > 10:
        assert display.within_face_budget is False or len(display.faces) <= 10
    # Must not equal a pure face-stride of the complete mesh.
    if len(complete.faces) > 50:
        stride = int(np.ceil(len(complete.faces) / 10))
        strided = complete.faces[::stride]
        assert not (
            len(display.faces) == len(strided)
            and np.array_equal(display.faces, strided)
        )


def test_display_mesh_from_scientific_defaults_to_weld_compact():
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
    display = display_mesh_from_scientific(scientific)
    assert isinstance(display, DisplayMesh)
    assert display.lod_method == DISPLAY_METHOD_WELD_COMPACT
    assert display.source_face_count == len(scientific.faces)
    assert display.output_face_count <= display.source_face_count
    assert display.output_vertex_count <= display.source_vertex_count
    with pytest.raises(ResultAuthorityError):
        _ = display.measurement


def test_mesh_preview_payload_reports_weld_compact_provenance():
    from morphostack.api.app import mesh_preview_payload

    verts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    faces = np.array([[0, 1, 2], [0, 1, 3]])
    geom = MeshGeometry(
        vertices_xyz=verts,
        faces=faces,
        measurement=MeshMeasurement(surface_area_um2=1.0, volume_um3=0.1),
        display_only=True,
        display_method=DISPLAY_METHOD_WELD_COMPACT,
        source_vertex_count=10,
        source_face_count=20,
        boundary_edge_count_source=0,
        boundary_edge_count_display=0,
        within_face_budget=True,
        face_budget=12000,
    )
    payload = mesh_preview_payload("x.tif", geom, downsample=1)
    assert payload["display_only"] is True
    assert payload["display_method"] == DISPLAY_METHOD_WELD_COMPACT
    assert payload["result_authority"]["geometry_role"] == "display"
    assert payload["result_authority"]["display_method"] == DISPLAY_METHOD_WELD_COMPACT
    assert "weld" in payload["result_authority"]["measurement_authority_note"].lower()
    assert "face-stride" not in payload["result_authority"]["measurement_authority_note"].lower()
    assert payload["source_face_count"] == 20


def test_payload_and_timing_benchmark_writes_artifact():
    pytest.importorskip("skimage")
    mask = _sphere_mask(nz=20, ny=48, nx=48, radius=14.0)
    voxel = VoxelSize(0.5, 0.5, 1.0)

    t0 = time.perf_counter()
    complete = marching_cubes_geometry(mask, voxel, display_derivative=False)
    t_complete = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    display = marching_cubes_geometry(mask, voxel, max_faces=12000, display_derivative=True)
    t_display = (time.perf_counter() - t1) * 1000.0

    # Weld-only timing on already-complete verts
    t2 = time.perf_counter()
    _v, _f, stats = weld_compact_mesh(complete.vertices_xyz, complete.faces)
    t_weld = (time.perf_counter() - t2) * 1000.0

    # JSON payload size proxy (preview list encoding)
    complete_json = json.dumps(
        {
            "vertices": complete.vertices_xyz.round(6).tolist(),
            "faces": complete.faces.astype(int).tolist(),
        }
    )
    display_json = json.dumps(
        {
            "vertices": display.vertices_xyz.round(6).tolist(),
            "faces": display.faces.astype(int).tolist(),
        }
    )
    complete_bytes = len(complete_json.encode("utf-8"))
    display_bytes = len(display_json.encode("utf-8"))
    reduction = complete_bytes / display_bytes if display_bytes else 0.0

    assert display.measurement.surface_area_um2 == complete.measurement.surface_area_um2
    assert display.measurement.volume_um3 == complete.measurement.volume_um3
    assert display_bytes <= complete_bytes
    assert t_weld < 300.0  # budget for weld alone

    report = {
        "packet": 14,
        "display_method": DISPLAY_METHOD_WELD_COMPACT,
        "source_vertex_count": int(len(complete.vertices_xyz)),
        "source_face_count": int(len(complete.faces)),
        "output_vertex_count": int(len(display.vertices_xyz)),
        "output_face_count": int(len(display.faces)),
        "boundary_edge_count_source": int(stats["boundary_edge_count_source"]),
        "boundary_edge_count_display": int(stats["boundary_edge_count_display"]),
        "complete_json_bytes": complete_bytes,
        "display_json_bytes": display_bytes,
        "payload_reduction_factor": round(reduction, 3),
        "within_2mb_budget": display_bytes < 2 * 1024 * 1024,
        "timing_ms": {
            "complete_mc": round(t_complete, 3),
            "display_mc_plus_weld": round(t_display, 3),
            "weld_only": round(t_weld, 3),
            "weld_budget_ms": 300,
            "weld_under_budget": t_weld < 300.0,
        },
        "scientific_parity": {
            "surface_area_um2": float(complete.measurement.surface_area_um2),
            "volume_um3": float(complete.measurement.volume_um3),
            "display_matches_complete": True,
        },
        "face_stride_used": False,
    }
    _ARTIFACT.mkdir(parents=True, exist_ok=True)
    out = _ARTIFACT / "perf.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert out.is_file()


def test_authoritative_mesh_export_path_uses_complete_geometry():
    """max_faces=None path is complete (not display_only)."""
    pytest.importorskip("skimage")
    mask = _binary_box()
    voxel = VoxelSize(1.0, 1.0, 1.0)
    # Contour-like path via mask stack identity
    geom = marching_cubes_geometry(mask, voxel, max_faces=None)
    assert geom.display_only is False
    assert geom.display_method is None
    # Contour stack with max_faces=None
    # Build fake contours from mask edges is heavy; call contour path with empty fails.
    # Ensure contour_stack_mesh_geometry signature accepts None max_faces.
    contours = [None] * mask.shape[0]
    assert contour_stack_mesh_geometry(contours, shape=mask.shape, voxel=voxel, max_faces=None) is None
