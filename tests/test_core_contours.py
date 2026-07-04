from __future__ import annotations

import sys

import numpy as np
import pytest

from morphostack.core.contours import (
    contour_circularity,
    largest_component_boundary,
    largest_connected_component,
    largest_opencv_contour,
    segmentation_preview,
    smooth_contour_guarded,
)


def test_largest_connected_component_selects_biggest_region():
    mask = np.zeros((8, 8), dtype=bool)
    mask[1, 1] = True
    mask[3:6, 3:7] = True

    component = largest_connected_component(mask)

    assert component is not None
    assert component.sum() == 12
    assert component[4, 4]
    assert not component[1, 1]


def test_largest_component_boundary_returns_none_for_empty_mask():
    contour = largest_component_boundary(np.zeros((4, 4), dtype=bool))
    assert contour is None


def test_largest_component_boundary_returns_rectangular_contour():
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:5, 1:4] = True

    contour = largest_component_boundary(mask)

    np.testing.assert_array_equal(
        contour,
        np.array(
            [
                [1.0, 2.0],
                [4.0, 2.0],
                [4.0, 5.0],
                [1.0, 5.0],
            ]
        ),
    )


def test_segmentation_preview_reports_metrics_for_thresholded_component():
    image = np.zeros((8, 8), dtype=np.uint8)
    image[2:5, 1:4] = 200

    preview = segmentation_preview(image, threshold=100, prefer_opencv=False)

    assert preview.contour is not None
    assert preview.area_px2 == 9.0
    assert preview.perimeter_px == 12.0
    assert preview.circularity > 0
    assert preview.method == "fallback"


def test_segmentation_preview_can_force_fallback_method():
    image = np.zeros((8, 8), dtype=np.uint8)
    image[2:5, 1:4] = 200

    preview = segmentation_preview(image, threshold=100, prefer_opencv=False)

    assert preview.contour is not None
    assert preview.method == "fallback"


def test_segmentation_preview_reports_empty_result():
    preview = segmentation_preview(np.zeros((4, 4)), threshold=1)

    assert preview.contour is None
    assert preview.area_px2 == 0.0
    assert preview.perimeter_px == 0.0
    assert preview.circularity == 0.0


def test_largest_opencv_contour_extracts_real_boundary_when_available():
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((20, 20), dtype=bool)
    cv2.circle(mask.view(np.uint8), center=(10, 10), radius=5, color=1, thickness=-1)

    contour = largest_opencv_contour(mask)

    assert contour is not None
    assert len(contour) > 4
    assert contour[:, 0].min() >= 5
    assert contour[:, 0].max() <= 15


def test_segmentation_preview_uses_opencv_when_available():
    pytest.importorskip("cv2")
    image = np.zeros((8, 8), dtype=np.uint8)
    image[2:5, 1:4] = 200

    preview = segmentation_preview(image, threshold=100)

    assert preview.method == "opencv"
    assert preview.contour is not None
    assert preview.area_px2 == 4.0


def test_smooth_contour_guarded_falls_back_without_cv2(monkeypatch):
    contour = np.array(
        [
            [0, 0],
            [4, 0],
            [4, 1],
            [3, 1],
            [3, 2],
            [0, 2],
        ],
        dtype=float,
    )
    monkeypatch.setitem(sys.modules, "cv2", None)

    smoothed, circularity = smooth_contour_guarded(contour, desired_circularity=0.99)

    np.testing.assert_array_equal(smoothed, contour)
    assert circularity == contour_circularity(contour)
