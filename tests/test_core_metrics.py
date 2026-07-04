from __future__ import annotations

import numpy as np

from morphostack.core.metrics import contour_metrics
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


def test_contour_metrics_accept_cv2_contour_shape():
    triangle = np.array([[[0, 0]], [[2, 0]], [[0, 2]]])
    metrics = contour_metrics(triangle, VoxelSize(x_um=1.0, y_um=1.0, z_um=1.0))
    assert metrics.area_um2 == 2.0
    assert metrics.perimeter_um > 0

