"""Physical-coordinate RBC morphometry (pure functions)."""

from __future__ import annotations

import math

import numpy as np

from morphostack.core.models import VoxelSize
from morphostack.core.rbc_models import (
    RbcMeshQc,
    RbcProjectedMetrics,
    RbcQcIssue,
    RbcVolumeCrossCheck,
)


def measure_rbc_projected_mask(
    mask: np.ndarray,
    voxel: VoxelSize,
) -> RbcProjectedMetrics:
    """Second-moment 2D metrics in physical XY coordinates.

    Major/minor axes are equivalent ellipse diameters ``4 * sqrt(λ)`` from the
    covariance of occupied pixel centers expressed in micrometres.
    """

    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise ValueError("measure_rbc_projected_mask expects a 2D mask")
    ys, xs = np.nonzero(binary)
    if ys.size < 3:
        return RbcProjectedMetrics(
            area_um2=0.0,
            perimeter_um=0.0,
            perimeter_method="crofton_4",
            major_axis_um=0.0,
            minor_axis_um=0.0,
            aspect_ratio_L_over_W=0.0,
            static_elongation_index=0.0,
            circularity=0.0,
            solidity=0.0,
            equivalent_diameter_um=0.0,
        )

    x_um = xs.astype(np.float64) * float(voxel.x_um)
    y_um = ys.astype(np.float64) * float(voxel.y_um)
    # Pixel area in µm² (anisotropic XY supported).
    pixel_area_um2 = float(voxel.x_um) * float(voxel.y_um)
    area_um2 = float(ys.size) * pixel_area_um2

    points = np.column_stack((x_um, y_um))
    centered = points - points.mean(axis=0, keepdims=True)
    cov = (centered.T @ centered) / float(len(centered))
    # Numerical floor for near-degenerate thin lines.
    cov = 0.5 * (cov + cov.T)
    eigenvalues = np.linalg.eigvalsh(cov)
    eigenvalues = np.clip(eigenvalues[::-1], 0.0, None)
    major_axis_um = float(4.0 * math.sqrt(max(eigenvalues[0], 0.0)))
    minor_axis_um = float(4.0 * math.sqrt(max(eigenvalues[1], 0.0)))
    if minor_axis_um <= 0.0:
        aspect = 0.0
        static_elongation = 0.0
    else:
        aspect = major_axis_um / minor_axis_um
        static_elongation = (major_axis_um - minor_axis_um) / (major_axis_um + minor_axis_um)

    perimeter_um, perimeter_method = _calibrated_perimeter_um(binary, voxel)
    circularity = 0.0
    if perimeter_um > 0.0 and area_um2 > 0.0:
        circularity = float((4.0 * math.pi * area_um2) / (perimeter_um**2))

    solidity = _solidity_um(binary, voxel, area_um2)
    eq_d = float(math.sqrt((4.0 * area_um2) / math.pi)) if area_um2 > 0.0 else 0.0

    return RbcProjectedMetrics(
        area_um2=area_um2,
        perimeter_um=perimeter_um,
        perimeter_method=perimeter_method,
        major_axis_um=major_axis_um,
        minor_axis_um=minor_axis_um,
        aspect_ratio_L_over_W=aspect,
        static_elongation_index=static_elongation,
        circularity=circularity,
        solidity=solidity,
        equivalent_diameter_um=eq_d,
    )


def _calibrated_perimeter_um(mask: np.ndarray, voxel: VoxelSize) -> tuple[float, str]:
    """Crofton perimeter scaled by mean lateral spacing when available."""

    try:
        from skimage.measure import perimeter_crofton

        peri_px = float(perimeter_crofton(np.asarray(mask, dtype=bool), directions=4))
        # Anisotropic: scale by geometric mean of XY so units are µm.
        scale = math.sqrt(float(voxel.x_um) * float(voxel.y_um))
        return peri_px * scale, "crofton_4"
    except Exception:
        pass
    # Fallback: boundary pixel count * mean spacing (coarse).
    try:
        from skimage.measure import find_contours

        contours = find_contours(np.asarray(mask, dtype=np.float64), 0.5)
        if not contours:
            return 0.0, "contour_polyline"
        best = max(contours, key=lambda c: c.shape[0])
        # find_contours returns (row, col) = (y, x)
        xy = np.column_stack([best[:, 1] * float(voxel.x_um), best[:, 0] * float(voxel.y_um)])
        deltas = np.roll(xy, -1, axis=0) - xy
        return float(np.sum(np.linalg.norm(deltas, axis=1))), "contour_polyline"
    except Exception:
        return 0.0, "unavailable"


def _solidity_um(mask: np.ndarray, voxel: VoxelSize, area_um2: float) -> float:
    try:
        from skimage.morphology import convex_hull_image

        hull = convex_hull_image(np.asarray(mask, dtype=bool))
        hull_area = float(np.count_nonzero(hull)) * float(voxel.x_um) * float(voxel.y_um)
        if hull_area <= 0.0:
            return 0.0
        return float(area_um2 / hull_area)
    except Exception:
        return 0.0


def measure_rbc_occupancy(
    mask: np.ndarray,
    voxel: VoxelSize,
    *,
    compute_mesh: bool = True,
) -> RbcVolumeCrossCheck:
    """Voxel volume plus optional marching-cubes cross-check (not authority)."""

    arr = np.asarray(mask)
    if arr.ndim != 3:
        raise ValueError("measure_rbc_occupancy expects a (z, y, x) mask")
    binary = arr != 0
    n = int(np.count_nonzero(binary))
    voxel_volume = float(n) * float(voxel.x_um) * float(voxel.y_um) * float(voxel.z_um)
    mesh_volume = None
    surface_area = None
    rel = None
    if compute_mesh and n > 0:
        try:
            from morphostack.core.mesh import marching_cubes_measurement

            meas = marching_cubes_measurement(binary.astype(np.uint8), voxel)
            mesh_volume = float(meas.volume_um3)
            surface_area = float(meas.surface_area_um2)
            if voxel_volume > 0.0 and mesh_volume is not None:
                rel = abs(mesh_volume - voxel_volume) / voxel_volume
        except Exception:
            mesh_volume = None
            surface_area = None
            rel = None
    return RbcVolumeCrossCheck(
        voxel_volume_um3=voxel_volume,
        mesh_volume_um3=mesh_volume,
        surface_area_um2=surface_area,
        relative_disagreement=rel,
    )


def validate_rbc_scientific_mesh(
    mask: np.ndarray,
    voxel: VoxelSize,
    *,
    max_volume_disagreement: float = 0.15,
) -> tuple[RbcMeshQc, RbcVolumeCrossCheck]:
    """Engineering mesh QC against occupancy (fail-closed on disagreement).

    Non-watertight marching-cubes meshes are common on voxel phantoms; volume
    agreement + finite positive volume is the primary engineering gate here.
    """

    cross = measure_rbc_occupancy(mask, voxel, compute_mesh=True)
    issues: list[RbcQcIssue] = []
    boundary = 0
    watertight = False
    finite = False
    positive = False
    components = 0
    try:
        from morphostack.core.mesh import count_boundary_edges, marching_cubes_geometry

        geom = marching_cubes_geometry(
            np.asarray(mask) != 0,
            voxel,
            max_faces=None,
            display_derivative=False,
        )
        verts = np.asarray(geom.vertices_xyz, dtype=np.float64)
        faces = np.asarray(geom.faces, dtype=np.int64)
        boundary = int(count_boundary_edges(faces)) if faces.size else 0
        watertight = boundary == 0
        finite = bool(np.all(np.isfinite(verts))) if verts.size else False
        positive = float(geom.measurement.volume_um3) > 0.0
        try:
            from skimage.measure import label

            components = int(label(np.asarray(mask) != 0, connectivity=1).max())
        except Exception:
            components = 1 if np.any(mask) else 0
    except Exception:
        issues.append(RbcQcIssue.MESH_INVALID)

    if not finite or not positive or cross.mesh_volume_um3 is None:
        issues.append(RbcQcIssue.MESH_INVALID)
    if (
        cross.relative_disagreement is not None
        and cross.relative_disagreement > max_volume_disagreement
    ):
        issues.append(RbcQcIssue.VOLUME_DISAGREEMENT)

    ok = (
        finite
        and positive
        and cross.mesh_volume_um3 is not None
        and (
            cross.relative_disagreement is None
            or cross.relative_disagreement <= max_volume_disagreement
        )
    )
    if ok:
        issues = [i for i in issues if i not in (RbcQcIssue.MESH_INVALID,)]

    return (
        RbcMeshQc(
            ok=ok,
            boundary_edge_count=boundary,
            watertight=watertight,
            finite_vertices=finite,
            positive_volume=positive,
            component_count=components,
            issues=tuple(dict.fromkeys(issues)),
        ),
        cross,
    )


def best_projected_slice_mask(occupancy: np.ndarray) -> np.ndarray | None:
    """Return the largest-area Z slice of a 3D occupancy stack."""

    arr = np.asarray(occupancy, dtype=bool)
    if arr.ndim != 3 or arr.shape[0] == 0:
        return None
    areas = arr.reshape(arr.shape[0], -1).sum(axis=1)
    if int(areas.max()) <= 0:
        return None
    z = int(np.argmax(areas))
    return arr[z]
