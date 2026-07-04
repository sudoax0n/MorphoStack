from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.metrics import contour_metrics, convex_hull
from morphostack.core.models import VoxelSize


def test_contour_metrics_use_anisotropic_pixel_spacing():
    rectangle = np.array(
        [
            [0, 0],
            [4, 0],
            [4, 2],
            [0, 2],
        ]
    )
    metrics = contour_metrics(rectangle, VoxelSize(x_um=0.5, y_um=2.0, z_um=1.0))
    assert metrics.area_px2 == 8.0
    assert metrics.perimeter_px == 12.0
    assert metrics.area_um2 == 8.0
    assert metrics.perimeter_um == 12.0
    assert metrics.bbox_width_um == 2.0
    assert metrics.bbox_height_um == 4.0
    assert metrics.aspect_ratio == 2.0
    assert metrics.equivalent_diameter_um == pytest.approx(3.191538243)
    assert metrics.solidity == 1.0


def test_contour_metrics_accept_cv2_contour_shape():
    triangle = np.array([[[0, 0]], [[2, 0]], [[0, 2]]])
    metrics = contour_metrics(triangle, VoxelSize(x_um=1.0, y_um=1.0, z_um=1.0))
    assert metrics.area_um2 == 2.0
    assert metrics.perimeter_um > 0


def test_contour_metrics_solidity_uses_physical_convex_hull_area():
    concave = np.array(
        [
            [0, 0],
            [4, 0],
            [4, 4],
            [2, 2],
            [0, 4],
        ]
    )
    metrics = contour_metrics(concave, VoxelSize(x_um=2.0, y_um=1.0, z_um=1.0))

    assert metrics.area_um2 == 24.0
    assert metrics.solidity == 0.75


def test_convex_hull_returns_outer_boundary():
    points = np.array([[0, 0], [1, 1], [2, 0], [2, 2], [0, 2]])

    hull = convex_hull(points)

    assert len(hull) == 4
    assert {tuple(point) for point in hull} == {(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)}
