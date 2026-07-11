"""3D mesh measurement utilities."""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from math import pi
from pathlib import Path

import numpy as np

from morphostack.core.models import VoxelSize
from morphostack.core.metrics import normalize_points, polygon_area


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
class SliceVolumeMeasurement:
    """Calibrated trapezoidal volume cross-check from sequential 2D contours.

    "volume_um3" is populated only when every slice between the first and
    last detected contour is available. This deliberately prevents a missing
    interior contour from being bridged as though it were measured.
    "partial_volume_um3" is diagnostic only: it includes integrations inside
    each uninterrupted run, but never across a gap.

    The measurement is a volume cross-check for the primary marching-cubes
    mesh measurement. It does not estimate membrane surface area; in
    particular, it must not be confused with "sum(perimeter * z_step)".
    """

    volume_um3: float | None
    partial_volume_um3: float
    slice_areas_um2: tuple[float | None, ...]
    valid_slice_indices: tuple[int, ...]
    invalid_contour_indices: tuple[int, ...]
    first_slice_index: int | None
    last_slice_index: int | None
    contiguous_runs: tuple[tuple[int, int], ...]
    internal_missing_slice_indices: tuple[int, ...]
    internal_missing_ranges: tuple[tuple[int, int], ...]
    integrated_interval_count: int
    expected_interval_count: int
    coverage_fraction: float
    has_internal_gaps: bool
    z_step_um: float
    has_observed_start_cap: bool
    has_observed_end_cap: bool
    touches_stack_start: bool
    touches_stack_end: bool
    touches_stack_boundary: bool

    @property
    def sampled_slice_count(self) -> int:
        """Number of valid, non-degenerate contour slices."""

        return len(self.valid_slice_indices)

    @property
    def is_complete(self) -> bool:
        """Whether "volume_um3" covers one uninterrupted sampled object."""

        return self.volume_um3 is not None


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


def measure_slice_integrated_volume(
    contours: Sequence[np.ndarray | None],
    *,
    voxel: VoxelSize,
) -> SliceVolumeMeasurement:
    """Integrate calibrated filled-contour areas through Z with trapezoids.

    Each contour's polygon area is calculated after applying the independent
    XY calibration in "voxel"; adjacent areas are then integrated using the
    uniform Z step "voxel.z_um". Leading and trailing empty slices are
    treated as outside the object. A missing, degenerate, or malformed contour
    between the first and last valid slices is an internal gap: this function
    does not interpolate or bridge it, and returns "volume_um3=None".

    "partial_volume_um3" is retained only for diagnostics. It contains the
    sum of trapezoids within contiguous measured runs and must not be used as a
    complete-object volume when "has_internal_gaps" is true.
    """

    areas: list[float | None] = []
    valid_indices: list[int] = []
    invalid_indices: list[int] = []

    for index, contour in enumerate(contours):
        area_um2 = _contour_area_um2(contour, voxel=voxel)
        areas.append(area_um2)
        if area_um2 is None:
            if contour is not None:
                invalid_indices.append(index)
            continue
        valid_indices.append(index)

    runs = _contiguous_index_ranges(valid_indices)
    has_observed_start_cap = False
    has_observed_end_cap = False
    touches_stack_start = False
    touches_stack_end = False
    if valid_indices:
        first_slice_index = valid_indices[0]
        last_slice_index = valid_indices[-1]
        interior_interval_count = last_slice_index - first_slice_index
        has_observed_start_cap = first_slice_index > 0 and contours[first_slice_index - 1] is None
        has_observed_end_cap = last_slice_index < len(contours) - 1 and contours[last_slice_index + 1] is None
        touches_stack_start = first_slice_index == 0
        touches_stack_end = last_slice_index == len(contours) - 1
        expected_interval_count = (
            interior_interval_count + int(has_observed_start_cap) + int(has_observed_end_cap)
        )
        internal_missing_indices = tuple(
            index for index in range(first_slice_index, last_slice_index + 1) if areas[index] is None
        )
        coverage_fraction = len(valid_indices) / (interior_interval_count + 1)
    else:
        first_slice_index = None
        last_slice_index = None
        expected_interval_count = 0
        internal_missing_indices = ()
        coverage_fraction = 0.0

    partial_volume_um3 = 0.0
    integrated_interval_count = 0
    if has_observed_start_cap:
        first_area = areas[valid_indices[0]]
        if first_area is not None:
            partial_volume_um3 += 0.5 * first_area * voxel.z_um
            integrated_interval_count += 1
    for start, end in runs:
        for index in range(start, end):
            lower_area = areas[index]
            upper_area = areas[index + 1]
            if lower_area is None or upper_area is None:  # Defensive; runs contain valid slices only.
                continue
            partial_volume_um3 += 0.5 * (lower_area + upper_area) * voxel.z_um
            integrated_interval_count += 1
    if has_observed_end_cap:
        last_area = areas[valid_indices[-1]]
        if last_area is not None:
            partial_volume_um3 += 0.5 * last_area * voxel.z_um
            integrated_interval_count += 1

    has_internal_gaps = bool(internal_missing_indices)
    volume_um3: float | None = None
    if expected_interval_count > 0 and not has_internal_gaps:
        volume_um3 = float(partial_volume_um3)

    return SliceVolumeMeasurement(
        volume_um3=volume_um3,
        partial_volume_um3=float(partial_volume_um3),
        slice_areas_um2=tuple(areas),
        valid_slice_indices=tuple(valid_indices),
        invalid_contour_indices=tuple(invalid_indices),
        first_slice_index=first_slice_index,
        last_slice_index=last_slice_index,
        contiguous_runs=runs,
        internal_missing_slice_indices=internal_missing_indices,
        internal_missing_ranges=_contiguous_index_ranges(internal_missing_indices),
        integrated_interval_count=integrated_interval_count,
        expected_interval_count=expected_interval_count,
        coverage_fraction=float(coverage_fraction),
        has_internal_gaps=has_internal_gaps,
        z_step_um=voxel.z_um,
        has_observed_start_cap=has_observed_start_cap,
        has_observed_end_cap=has_observed_end_cap,
        touches_stack_start=touches_stack_start,
        touches_stack_end=touches_stack_end,
        touches_stack_boundary=touches_stack_start or touches_stack_end,
    )


def _contour_area_um2(contour: np.ndarray | None, *, voxel: VoxelSize) -> float | None:
    """Return the calibrated area of a non-degenerate polygonal contour."""

    if contour is None:
        return None
    try:
        points = normalize_points(contour)
    except (TypeError, ValueError):
        return None
    if len(points) < 3 or not np.all(np.isfinite(points)):
        return None

    scaled_points = points * np.array([voxel.x_um, voxel.y_um], dtype=np.float64)
    area_um2 = polygon_area(scaled_points)
    if not np.isfinite(area_um2) or area_um2 <= 0:
        return None
    return float(area_um2)


def _contiguous_index_ranges(indices: Sequence[int]) -> tuple[tuple[int, int], ...]:
    """Return inclusive start/end runs for sorted, unique slice indices."""

    if not indices:
        return ()

    ranges: list[tuple[int, int]] = []
    start = indices[0]
    previous = start
    for index in indices[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append((start, previous))
        start = index
        previous = index
    ranges.append((start, previous))
    return tuple(ranges)


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
    downsample: int = 1,
    max_faces: int = 12000,
    align_slices: bool = False,
) -> MeshGeometry | None:
    """Rasterize contours into a calibrated mesh suitable for web display.

    ``align_slices`` remains available for visual comparison only. It is off by
    default so preview geometry and reported measurements retain the physical
    XY positions and calibrated Z spacing of the acquired stack.
    """

    contours = _filter_outlier_contours(contours)
    mask_stack = contours_to_mask_stack(contours, shape=shape)
    if np.count_nonzero(mask_stack) == 0:
        return None

    if align_slices:
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
