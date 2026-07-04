from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.preview import render_segmentation_preview_png


def test_render_segmentation_preview_png_returns_png():
    pytest.importorskip("PIL")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200

    preview = render_segmentation_preview_png(
        stack,
        frame_index=0,
        threshold=100,
        prefer_opencv=False,
    )

    assert preview.frame_index == 0
    assert preview.width == 8
    assert preview.height == 8
    assert preview.preview.area_px2 == 9.0
    assert preview.png_bytes.startswith(b"\x89PNG")


def test_render_segmentation_preview_png_rejects_bad_frame():
    pytest.importorskip("PIL")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)

    with pytest.raises(ValueError, match="frame_index"):
        render_segmentation_preview_png(stack, frame_index=4, threshold=100)
