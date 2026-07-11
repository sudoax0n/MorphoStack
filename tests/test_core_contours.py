from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.contours import (
    contour_circularity,
    largest_component_boundary,
    largest_connected_component,
    largest_opencv_contour,
    segmentation_preview,
    smooth_contour_guarded,
    smooth_contour_spline,
)
from morphostack.core.metrics import polygon_area, polygon_perimeter


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
    assert contour[:, 0].min() >= 4
    assert contour[:, 0].max() <= 16


def test_segmentation_preview_uses_opencv_when_available():
    pytest.importorskip("cv2")
    image = np.zeros((8, 8), dtype=np.uint8)
    image[2:5, 1:4] = 200

    preview = segmentation_preview(image, threshold=100)

    assert preview.method == "opencv"
    assert preview.contour is not None
    # Area is positive after morph-close + spline smooth.
    assert preview.area_px2 > 0


def test_contour_from_solid_closing_reduces_jaggedness():
    """_contour_from_solid applies morph-close + spline so a noisy disk is smooth."""
    cv2 = pytest.importorskip("cv2")
    from morphostack.core.seeded_vesicle import _contour_from_solid

    # Build a clean filled disk then add salt-and-pepper noise on the boundary.
    h, w = 60, 60
    solid = np.zeros((h, w), dtype=bool)
    yy, xx = np.ogrid[:h, :w]
    solid[(xx - 30) ** 2 + (yy - 30) ** 2 <= 18 ** 2] = True
    # Erode a jagged boundary: toggle random border pixels
    rng = np.random.default_rng(42)
    ys, xs = np.where(solid)
    toggle = rng.choice(len(xs), size=40, replace=False)
    solid[ys[toggle], xs[toggle]] = False

    contour = _contour_from_solid(solid)
    assert contour is not None
    assert len(contour) >= 10
    circ = contour_circularity(contour)
    # Morphological closing + spline should yield a reasonably circular result
    assert circ >= 0.70, f"Expected circularity >= 0.70 after close+spline, got {circ:.3f}"


def test_smooth_contour_spline_reduces_jaggy_perimeter():
    """Noisy closed circle: spline lowers perimeter inflation while area stays close."""
    pytest.importorskip("scipy")
    rng = np.random.default_rng(0)
    r = 40.0
    n = 200
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    # 1–2 px radial noise creates jaggies that inflate perimeter.
    noise = rng.normal(0.0, 1.8, size=n)
    xy = np.column_stack(
        [
            50.0 + (r + noise) * np.cos(theta),
            50.0 + (r + noise) * np.sin(theta),
        ]
    )
    raw_peri = polygon_perimeter(xy, x_scale=1.0, y_scale=1.0)
    raw_area = polygon_area(xy)
    true_area = np.pi * r * r
    true_peri = 2.0 * np.pi * r

    smoothed = smooth_contour_spline(xy, sigma_px=1.5)
    assert smoothed is not None
    assert len(smoothed) >= 8
    # Closed-ish: first/last not required identical after periodic eval, but non-empty.
    sm_peri = polygon_perimeter(smoothed, x_scale=1.0, y_scale=1.0)
    sm_area = polygon_area(smoothed)
    assert sm_peri > 0
    assert sm_area > 0
    # Perimeter not inflated by jaggies relative to raw noisy contour.
    assert sm_peri < raw_peri, f"smoothed peri {sm_peri:.2f} should be < raw {raw_peri:.2f}"
    # Smoothed perimeter closer to true circle than raw jaggies.
    assert abs(sm_peri - true_peri) < abs(raw_peri - true_peri)
    # Area stays within a few percent of the true disk.
    assert abs(sm_area - true_area) / true_area < 0.08
    # Result is closed enough for metrics (circularity high).
    assert contour_circularity(smoothed) > contour_circularity(xy)


def test_smooth_contour_guarded_uses_spline_not_approx_poly():
    """guarded smooth returns a non-empty closed-ish polyline with improved circularity."""
    pytest.importorskip("scipy")
    rng = np.random.default_rng(1)
    r = 30.0
    n = 120
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    noise = rng.normal(0.0, 2.0, size=n)
    xy = np.column_stack(
        [
            40.0 + (r + noise) * np.cos(theta),
            40.0 + (r + noise) * np.sin(theta),
        ]
    )
    smoothed, circ = smooth_contour_guarded(xy, desired_circularity=0.99)
    assert len(smoothed) >= 8
    assert circ == contour_circularity(smoothed)
    assert circ > contour_circularity(xy)


def test_smooth_contour_spline_fails_soft_on_tiny_input():
    """Too few points: return original (no crash)."""
    tiny = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]], dtype=np.float64)
    out = smooth_contour_spline(tiny)
    assert len(out) == 3


def test_no_smooth_binary_mask_in_contours_module():
    """Mask-domain Gaussian pre-smooth must be gone (research: inward bias)."""
    import morphostack.core.contours as contours_mod

    assert not hasattr(contours_mod, "_smooth_binary_mask")
