from __future__ import annotations

from math import pi

import numpy as np
import pytest

from morphostack.core import VoxelSize
from morphostack.core.mesh import (
    contours_to_mask_stack,
    measure_contour_stack,
    measure_slice_integrated_volume,
    surface_area_volume,
)


def test_surface_area_volume_for_unit_tetrahedron():
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    faces = np.array(
        [
            [0, 2, 1],
            [0, 1, 3],
            [0, 3, 2],
            [1, 2, 3],
        ]
    )
    measurement = surface_area_volume(vertices, faces)
    expected_area = 1.5 + (3**0.5 / 2.0)
    assert measurement.surface_area_um2 == expected_area
    assert measurement.volume_um3 == 1.0 / 6.0
    assert measurement.equivalent_sphere_diameter_um == pytest.approx((1.0 / pi) ** (1.0 / 3.0))
    assert 0 < measurement.sphericity <= 1


def test_contours_to_mask_stack_rasterizes_contours():
    pytest.importorskip("cv2")
    contour = np.array([[1, 1], [4, 1], [4, 4], [1, 4]])

    mask = contours_to_mask_stack([contour, None], shape=(2, 6, 6))

    assert mask.shape == (2, 6, 6)
    assert mask[0].sum() > 0
    assert mask[1].sum() == 0


def test_measure_contour_stack_returns_mesh_measurement():
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    contours = [
        np.array([[1, 1], [4, 1], [4, 4], [1, 4]]),
        np.array([[1, 1], [4, 1], [4, 4], [1, 4]]),
        np.array([[1, 1], [4, 1], [4, 4], [1, 4]]),
    ]

    measurement = measure_contour_stack(contours, shape=(3, 6, 6), voxel=VoxelSize(1.0, 1.0, 1.0))

    assert measurement is not None
    assert measurement.surface_area_um2 > 0
    assert measurement.volume_um3 > 0
    assert measurement.equivalent_sphere_diameter_um > 0
    assert 0 < measurement.sphericity <= 1


def test_slice_integrated_volume_uses_physical_xy_area_and_trapezoids():
    contours = [
        _rectangle(width_px=2.0, height_px=2.0),
        _rectangle(width_px=4.0, height_px=2.0),
        _rectangle(width_px=6.0, height_px=2.0),
    ]

    measurement = measure_slice_integrated_volume(
        contours,
        voxel=VoxelSize(x_um=0.5, y_um=0.25, z_um=0.5),
    )

    assert measurement.slice_areas_um2 == pytest.approx((0.5, 1.0, 1.5))
    assert measurement.volume_um3 == pytest.approx(1.0)
    assert measurement.partial_volume_um3 == pytest.approx(1.0)
    assert measurement.is_complete is True
    assert measurement.has_internal_gaps is False
    assert measurement.contiguous_runs == ((0, 2),)
    assert measurement.integrated_interval_count == 2
    assert measurement.expected_interval_count == 2
    assert measurement.coverage_fraction == pytest.approx(1.0)
    assert measurement.z_step_um == pytest.approx(0.5)


def test_slice_integrated_volume_is_accurate_for_dense_synthetic_sphere():
    radius_um = 10.0
    z_step_um = 0.5
    z_positions_um = np.arange(-radius_um + z_step_um / 2.0, radius_um, z_step_um)
    contours = [
        _circle(np.sqrt(radius_um**2 - z_um**2))
        for z_um in z_positions_um
    ]

    measurement = measure_slice_integrated_volume(
        contours,
        voxel=VoxelSize(x_um=1.0, y_um=1.0, z_um=z_step_um),
    )

    exact_volume_um3 = (4.0 / 3.0) * pi * radius_um**3
    assert measurement.volume_um3 is not None
    assert measurement.volume_um3 == pytest.approx(exact_volume_um3, rel=0.0025)
    assert measurement.has_internal_gaps is False
    assert measurement.sampled_slice_count == len(contours)


def test_slice_integrated_volume_does_not_bridge_an_internal_missing_contour():
    contour = _rectangle(width_px=4.0, height_px=4.0)
    measurement = measure_slice_integrated_volume(
        [contour, contour, None, contour, contour],
        voxel=VoxelSize(x_um=0.5, y_um=0.5, z_um=0.5),
    )

    assert measurement.volume_um3 is None
    assert measurement.partial_volume_um3 == pytest.approx(4.0)
    assert measurement.is_complete is False
    assert measurement.has_internal_gaps is True
    assert measurement.internal_missing_slice_indices == (2,)
    assert measurement.internal_missing_ranges == ((2, 2),)
    assert measurement.contiguous_runs == ((0, 1), (3, 4))
    assert measurement.integrated_interval_count == 2
    assert measurement.expected_interval_count == 4
    assert measurement.coverage_fraction == pytest.approx(0.8)


def _rectangle(*, width_px: float, height_px: float) -> np.ndarray:
    return np.array(
        [
            [0.0, 0.0],
            [width_px, 0.0],
            [width_px, height_px],
            [0.0, height_px],
        ]
    )


def _circle(radius_px: float, *, point_count: int = 256) -> np.ndarray:
    angles = np.linspace(0.0, 2.0 * pi, num=point_count, endpoint=False)
    return np.column_stack((radius_px * np.cos(angles), radius_px * np.sin(angles)))
