from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from morphostack.core.mesh import (
    MeshGeometry,
    MeshMeasurement,
    write_mesh_file,
    write_mesh_glb,
    write_mesh_obj,
    write_mesh_stl,
)


def unit_tetrahedron_geometry() -> MeshGeometry:
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int64)
    measurement = MeshMeasurement(surface_area_um2=1.0, volume_um3=1.0)
    return MeshGeometry(vertices_xyz=vertices, faces=faces, measurement=measurement)


def test_write_mesh_obj_writes_vertex_and_face_lines(tmp_path: Path):
    destination = tmp_path / "mesh.obj"
    write_mesh_obj(unit_tetrahedron_geometry(), destination)
    text = destination.read_text(encoding="utf-8")
    assert text.startswith("# MorphoStack mesh export\n")
    assert "v 0 0 0" in text
    assert "f 1 3 2" in text


def test_write_mesh_stl_writes_solid_header(tmp_path: Path):
    destination = tmp_path / "mesh.stl"
    write_mesh_stl(unit_tetrahedron_geometry(), destination)
    text = destination.read_text(encoding="utf-8")
    assert text.startswith("solid morphostack\n")
    assert "facet normal" in text
    assert text.rstrip().endswith("endsolid morphostack")


def test_write_mesh_file_selects_format_by_suffix(tmp_path: Path):
    geometry = unit_tetrahedron_geometry()
    obj_path = tmp_path / "export.obj"
    assert write_mesh_file(geometry, obj_path) == "obj"
    assert obj_path.exists()
    assert obj_path.stat().st_size > 0

    glb_path = tmp_path / "mesh.glb"
    assert write_mesh_file(geometry, glb_path) == "glb"
    assert glb_path.exists()
    assert glb_path.stat().st_size > 32
    glb_bytes = glb_path.read_bytes()
    assert glb_bytes[:4] == b"glTF"


def test_write_mesh_glb_contains_vertex_and_index_chunks(tmp_path: Path):
    geometry = unit_tetrahedron_geometry()
    destination = tmp_path / "export.glb"
    write_mesh_glb(geometry, destination)
    data = destination.read_bytes()
    assert data[:4] == b"glTF"
    assert b"JSON" in data[:128]
    assert b"BIN" in data