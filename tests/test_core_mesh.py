from __future__ import annotations

from math import pi

import numpy as np
import pytest

from morphostack.core import VoxelSize
from morphostack.core.mesh import contours_to_mask_stack, measure_contour_stack, surface_area_volume


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
