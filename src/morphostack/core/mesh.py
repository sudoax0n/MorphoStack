"""3D mesh measurement utilities."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from math import pi
from pathlib import Path

import numpy as np

from morphostack.core.models import VoxelSize
from morphostack.core.metrics import normalize_points


@dataclass(frozen=True)
class MeshMeasurement:
    surface_area_um2: float
    volume_um3: float

    @property
    def equivalent_sphere_diameter_um(self) -> float:
        if self.volume_um3 <= 0:
            return 0.0
        return float((6.0 * self.volume_um3 / pi) ** (1.0 / 3.0))

    @property
    def sphericity(self) -> float:
        if self.surface_area_um2 <= 0 or self.volume_um3 <= 0:
            return 0.0
        raw = (pi ** (1.0 / 3.0)) * ((6.0 * self.volume_um3) ** (2.0 / 3.0)) / self.surface_area_um2
        return float(min(raw, 1.0))


@dataclass(frozen=True)
class MeshGeometry:
    vertices_xyz: np.ndarray
    faces: np.ndarray
    measurement: MeshMeasurement


def surface_area_volume(vertices: np.ndarray, faces: np.ndarray) -> MeshMeasurement:
    """Calculate surface area and enclosed signed-volume magnitude from triangles."""

    verts = np.asarray(vertices, dtype=np.float64)
    face_idx = np.asarray(faces, dtype=np.int64)
    if verts.ndim != 2 or verts.shape[1] != 3:
        raise ValueError("vertices must have shape (n, 3)")
    if face_idx.ndim != 2 or face_idx.shape[1] != 3:
        raise ValueError("faces must have shape (n, 3)")

    triangles = verts[face_idx]
    vec1 = triangles[:, 1] - triangles[:, 0]
    vec2 = triangles[:, 2] - triangles[:, 0]
    cross = np.cross(vec1, vec2)
    surface_area = float(np.sum(np.linalg.norm(cross, axis=1)) / 2.0)
    volume = float(abs(np.sum(np.einsum("ij,ij->i", triangles[:, 0], cross)) / 6.0))
    return MeshMeasurement(surface_area_um2=surface_area, volume_um3=volume)


def marching_cubes_geometry(mask_stack: np.ndarray, voxel: VoxelSize, *, max_faces: int | None = None) -> MeshGeometry:
    """Run marching cubes on a (z, y, x) binary stack and return display geometry."""

    try:
        from skimage import measure
    except Exception as exc:  # pragma: no cover - dependency-specific branch
        raise RuntimeError("scikit-image is required for marching cubes") from exc

    mask = np.asarray(mask_stack)
    if mask.ndim != 3:
        raise ValueError("marching cubes expects a 3D stack shaped as (z, y, x)")
    verts, faces, _, _ = measure.marching_cubes(
        mask.astype(np.uint8),
        level=0.5,
        spacing=voxel.marching_cubes_spacing,
    )
    measurement = surface_area_volume(verts, faces)
    display_faces = faces
    if max_faces is not None and max_faces > 0 and len(display_faces) > max_faces:
        stride = int(np.ceil(len(display_faces) / max_faces))
        display_faces = display_faces[::stride]
    vertices_xyz = verts[:, [2, 1, 0]]
    return MeshGeometry(vertices_xyz=vertices_xyz, faces=display_faces, measurement=measurement)


def marching_cubes_measurement(mask_stack: np.ndarray, voxel: VoxelSize) -> MeshMeasurement:
    """Run marching cubes on a (z, y, x) binary stack and measure the mesh."""

    return marching_cubes_geometry(mask_stack, voxel).measurement


def contours_to_mask_stack(
    contours: list[np.ndarray | None] | tuple[np.ndarray | None, ...],
    *,
    shape: tuple[int, int, int],
) -> np.ndarray:
    """Rasterize per-frame contours into a binary stack shaped as (z, y, x)."""

    if len(shape) != 3:
        raise ValueError("shape must be (z, y, x)")
    if len(contours) != shape[0]:
        raise ValueError("number of contours must match z dimension")

    mask_stack = np.zeros(shape, dtype=np.uint8)
    for idx, contour in enumerate(contours):
        if contour is None:
            continue
        mask_stack[idx] = contour_to_mask(contour, shape=shape[1:])
    return mask_stack


def contour_to_mask(contour: np.ndarray, *, shape: tuple[int, int]) -> np.ndarray:
    """Rasterize one contour into a 2D uint8 mask."""

    try:
        import cv2
    except Exception as exc:  # pragma: no cover - dependency-specific branch
        raise RuntimeError("opencv-python is required to rasterize contours") from exc

    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    pts = np.rint(normalize_points(contour)).astype(np.int32).reshape((-1, 1, 2))
    if len(pts) >= 3:
        cv2.drawContours(mask, [pts], contourIdx=-1, color=1, thickness=-1)
    return mask


def measure_contour_stack(
    contours: list[np.ndarray | None] | tuple[np.ndarray | None, ...],
    *,
    shape: tuple[int, int, int],
    voxel: VoxelSize,
) -> MeshMeasurement | None:
    """Rasterize contours and measure their 3D marching-cubes mesh."""

    mask_stack = contours_to_mask_stack(contours, shape=shape)
    if np.count_nonzero(mask_stack) == 0:
        return None
    return marching_cubes_measurement(mask_stack, voxel)


def contour_stack_mesh_geometry(
    contours: list[np.ndarray | None] | tuple[np.ndarray | None, ...],
    *,
    shape: tuple[int, int, int],
    voxel: VoxelSize,
    downsample: int = 2,
    max_faces: int = 12000,
) -> MeshGeometry | None:
    """Rasterize contours and return a decimated mesh suitable for web display."""

    contours = _filter_outlier_contours(contours)
    mask_stack = contours_to_mask_stack(contours, shape=shape)
    if np.count_nonzero(mask_stack) == 0:
        return None

    mask_stack = align_mask_stack(mask_stack)
    factor = max(1, int(downsample))
    display_mask = mask_stack
    display_voxel = voxel
    if factor > 1 and min(mask_stack.shape) >= factor * 2:
        display_mask = _zoom_mask(mask_stack, 1.0 / factor)
        display_voxel = VoxelSize(
            x_um=voxel.x_um * factor,
            y_um=voxel.y_um * factor,
            z_um=voxel.z_um * factor,
        )

    return marching_cubes_geometry(display_mask, display_voxel, max_faces=max_faces)


def _zoom_mask(mask: np.ndarray, scale: float) -> np.ndarray:
    """Downsample a binary mask with interpolation to preserve connectivity."""
    try:
        from scipy.ndimage import zoom
        zoomed = zoom(mask.astype(np.float32), scale, order=1)
        return (zoomed > 0.5).astype(np.uint8)
    except Exception:
        # Fall back to stride slicing if scipy unavailable
        s = max(1, int(round(1.0 / scale)))
        return mask[::s, ::s, ::s]


def align_mask_stack(mask_stack: np.ndarray) -> np.ndarray:
    """Align binary mask slices by centroid, matching the old 3D HTML workflow."""

    try:
        import cv2
    except Exception:
        return mask_stack

    arr = np.asarray(mask_stack, dtype=np.uint8)
    reference = next((frame for frame in arr if np.count_nonzero(frame) > 0), None)
    if reference is None:
        return arr
    reference_center = mask_centroid(reference)
    aligned: list[np.ndarray] = []
    for frame in arr:
        if np.count_nonzero(frame) == 0:
            aligned.append(frame)
            continue
        center = mask_centroid(frame)
        dx = reference_center[0] - center[0]
        dy = reference_center[1] - center[1]
        translation = np.float32([[1, 0, dx], [0, 1, dy]])
        rows, cols = frame.shape
        aligned.append(cv2.warpAffine(frame, translation, (cols, rows)))
    return np.stack(aligned, axis=0).astype(np.uint8)


def mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    try:
        import cv2
    except Exception:
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return (0.0, 0.0)
        return (float(xs.mean()), float(ys.mean()))

    moments = cv2.moments(mask.astype(np.uint8))
    if moments["m00"] == 0:
        return (0.0, 0.0)
    return (float(moments["m10"] / moments["m00"]), float(moments["m01"] / moments["m00"]))


def write_mesh_obj(geometry: MeshGeometry, destination: str | Path) -> None:
    """Write mesh vertices and faces to Wavefront OBJ."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices = np.asarray(geometry.vertices_xyz, dtype=np.float64)
    faces = np.asarray(geometry.faces, dtype=np.int64)
    lines = ["# MorphoStack mesh export"]
    for vertex in vertices:
        lines.append(f"v {vertex[0]:.6g} {vertex[1]:.6g} {vertex[2]:.6g}")
    for face in faces:
        # OBJ indices are 1-based.
        lines.append(f"f {face[0] + 1} {face[1] + 1} {face[2] + 1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mesh_stl(geometry: MeshGeometry, destination: str | Path) -> None:
    """Write mesh triangles to ASCII STL."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices = np.asarray(geometry.vertices_xyz, dtype=np.float64)
    faces = np.asarray(geometry.faces, dtype=np.int64)
    lines = ["solid morphostack"]
    for face in faces:
        triangle = vertices[face]
        edge_a = triangle[1] - triangle[0]
        edge_b = triangle[2] - triangle[0]
        normal = np.cross(edge_a, edge_b)
        norm = float(np.linalg.norm(normal))
        if norm > 0:
            normal = normal / norm
        else:
            normal = np.array([0.0, 0.0, 0.0])
        lines.append(f"  facet normal {normal[0]:.6g} {normal[1]:.6g} {normal[2]:.6g}")
        lines.append("    outer loop")
        for vertex in triangle:
            lines.append(f"      vertex {vertex[0]:.6g} {vertex[1]:.6g} {vertex[2]:.6g}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid morphostack")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mesh_ply(geometry: MeshGeometry, destination: str | Path) -> None:
    """Write mesh vertices and faces to ASCII PLY."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices = np.asarray(geometry.vertices_xyz, dtype=np.float64)
    faces = np.asarray(geometry.faces, dtype=np.int64)
    header = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    body = [f"{vertex[0]:.6g} {vertex[1]:.6g} {vertex[2]:.6g}" for vertex in vertices]
    body.extend(f"3 {int(face[0])} {int(face[1])} {int(face[2])}" for face in faces)
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def write_mask_stack_tiff(
    contours: list[np.ndarray | None] | tuple[np.ndarray | None, ...],
    *,
    shape: tuple[int, int, int],
    destination: str | Path,
) -> None:
    """Write rasterized contour masks as an 8-bit TIFF stack shaped (z, y, x)."""

    try:
        import tifffile
    except Exception as exc:  # pragma: no cover - dependency-specific branch
        raise RuntimeError("tifffile is required for mask export") from exc

    mask_stack = contours_to_mask_stack(contours, shape=shape)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, (mask_stack * 255).astype(np.uint8), photometric="minisblack")


def _align4(length: int) -> int:
    return (length + 3) & ~3


def write_mesh_glb(geometry: MeshGeometry, destination: str | Path) -> None:
    """Write mesh geometry to binary glTF (.glb) for 3D viewers."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices = np.asarray(geometry.vertices_xyz, dtype=np.float32)
    faces = np.asarray(geometry.faces, dtype=np.uint32)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices must have shape (n, 3)")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("faces must have shape (n, 3)")

    vertex_bytes = vertices.tobytes()
    index_bytes = faces.reshape(-1).astype(np.uint32).tobytes()
    vertex_padded_len = _align4(len(vertex_bytes))
    index_offset = vertex_padded_len
    bin_body = vertex_bytes.ljust(vertex_padded_len, b"\x00") + index_bytes
    bin_padded_len = _align4(len(bin_body))
    bin_body = bin_body.ljust(bin_padded_len, b"\x00")

    mins = vertices.min(axis=0).tolist()
    maxs = vertices.max(axis=0).tolist()
    gltf = {
        "asset": {"version": "2.0", "generator": "MorphoStack"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": 4,
                    }
                ]
            }
        ],
        "buffers": [{"byteLength": len(bin_body)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(vertex_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": index_offset,
                "byteLength": len(index_bytes),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": int(len(vertices)),
                "type": "VEC3",
                "min": [float(v) for v in mins],
                "max": [float(v) for v in maxs],
            },
            {
                "bufferView": 1,
                "componentType": 5125,
                "count": int(faces.size),
                "type": "SCALAR",
            },
        ],
    }
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_padded_len = _align4(len(json_bytes))
    json_chunk = json_bytes.ljust(json_padded_len, b" ")

    total_length = 12 + 8 + json_padded_len + 8 + bin_padded_len
    header = struct.pack("<4sII", b"glTF", 2, total_length)
    json_header = struct.pack("<I4s", json_padded_len, b"JSON")
    bin_header = struct.pack("<I4s", bin_padded_len, b"BIN\x00")
    path.write_bytes(header + json_header + json_chunk + bin_header + bin_body)


def write_mesh_file(geometry: MeshGeometry, destination: str | Path) -> str:
    """Write mesh geometry using the destination file extension."""

    path = Path(destination)
    suffix = path.suffix.lower()
    if suffix == ".obj":
        write_mesh_obj(geometry, path)
        return "obj"
    if suffix == ".stl":
        write_mesh_stl(geometry, path)
        return "stl"
    if suffix == ".ply":
        write_mesh_ply(geometry, path)
        return "ply"
    if suffix == ".glb":
        write_mesh_glb(geometry, path)
        return "glb"
    raise ValueError("Mesh export supports .obj, .stl, .ply, and .glb destinations")


def _filter_outlier_contours(
    contours: list[np.ndarray | None] | tuple[np.ndarray | None, ...],
) -> tuple[np.ndarray | None, ...]:
    """Drop contours whose area is far below the median — removes junk/noise frames."""
    from morphostack.core.metrics import polygon_area

    areas = []
    for c in contours:
        if c is not None:
            areas.append(polygon_area(c))

    if not areas:
        return tuple(contours)

    median_area = float(np.median(areas))
    if median_area <= 0:
        return tuple(contours)

    min_area = median_area * 0.10
    return tuple(
        c if (c is not None and polygon_area(c) >= min_area) else None
        for c in contours
    )
