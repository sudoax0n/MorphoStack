from __future__ import annotations

import numpy as np

from morphostack.core.images import as_color_stack, as_grayscale_stack, stretch_to_uint8


def test_grayscale_2d_becomes_single_frame_stack():
    image = np.arange(6).reshape(2, 3)
    stack = as_grayscale_stack(image)
    assert stack.shape == (1, 2, 3)


def test_rgb_stack_becomes_grayscale_stack():
    rgb = np.zeros((2, 3, 4, 3), dtype=np.uint8)
    rgb[..., 1] = 100
    stack = as_grayscale_stack(rgb)
    assert stack.shape == (2, 3, 4)
    assert np.all(stack == 58)


def test_grayscale_stack_becomes_color_stack():
    gray = np.arange(40, dtype=np.uint8).reshape(2, 4, 5)
    color = as_color_stack(gray)
    assert color.shape == (2, 4, 5, 3)
    np.testing.assert_array_equal(color[..., 0], gray)
    np.testing.assert_array_equal(color[..., 1], gray)
    np.testing.assert_array_equal(color[..., 2], gray)


def test_stretch_to_uint8_handles_constant_slices():
    stack = np.array(
        [
            [[5, 5], [5, 5]],
            [[0, 5], [10, 15]],
        ]
    )
    stretched = stretch_to_uint8(stack)
    assert stretched.dtype == np.uint8
    assert np.all(stretched[0] == 0)
    assert stretched[1, 0, 0] == 0
    assert stretched[1, 1, 1] == 255
