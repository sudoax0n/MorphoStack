"""3D mesh measurement utilities."""

from __future__ import annotations

from dataclasses import dataclass
from math import pi

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
