from __future__ import annotations

import numpy as np

from morphostack.core.mesh import surface_area_volume


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
