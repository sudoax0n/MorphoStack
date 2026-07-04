from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.segmentation import apply_rect_roi, suggest_threshold, threshold_mask


def test_threshold_mask_is_inclusive():
    image = np.array([[0, 5], [10, 15]])
    mask = threshold_mask(image, 10)
    np.testing.assert_array_equal(mask, [[False, False], [True, True]])


def test_suggest_threshold_handles_constant_stack():
    threshold, method = suggest_threshold(np.full((2, 4, 4), 7, dtype=np.uint8))

    assert threshold == 7.0
    assert method == "constant"


def test_suggest_threshold_percentile_fallback():
    stack = np.array([0, 0, 10, 20], dtype=np.uint8)

    threshold, method = suggest_threshold(stack, method="percentile")

    assert threshold == 12.5
    assert method == "percentile"


def test_suggest_threshold_rejects_unknown_method():
    with pytest.raises(ValueError, match="threshold method"):
        suggest_threshold(np.zeros((1, 2, 2)), method="entropy")


def test_apply_rect_roi_masks_all_frames():
    stack = np.ones((2, 4, 4), dtype=np.uint8)
    cropped = apply_rect_roi(stack, xmin=1, xmax=3, ymin=1, ymax=3)
    assert cropped.sum() == 8
    assert cropped[:, 1:3, 1:3].sum() == 8


def test_apply_rect_roi_rejects_empty_bounds():
    stack = np.ones((1, 4, 4), dtype=np.uint8)
    with pytest.raises(ValueError):
        apply_rect_roi(stack, xmin=2, xmax=2, ymin=0, ymax=3)
