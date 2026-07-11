from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.pipeline import RectROI, ZRange
from morphostack.core.preview import extract_preview_frame, render_segmentation_preview_png
from morphostack.core.segmentation import apply_rect_roi


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


def test_render_segmentation_preview_png_accepts_2d_frame():
    pytest.importorskip("PIL")
    frame = np.zeros((8, 8), dtype=np.uint8)
    frame[2:5, 1:4] = 200

    preview = render_segmentation_preview_png(frame, frame_index=0, threshold=100, prefer_opencv=False)
    assert preview.width == 8
    assert preview.height == 8
    assert preview.preview.area_px2 == 9.0
    assert preview.png_bytes.startswith(b"\x89PNG")


def test_extract_preview_frame_single_plane_no_roi():
    stack = np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5)
    frame, transform = extract_preview_frame(stack, 1)
    assert frame.shape == (4, 5)
    assert np.array_equal(frame, stack[1])
    assert transform.x_offset == 0
    assert transform.y_offset == 0
    assert transform.z_offset == 0


def test_extract_preview_frame_crops_roi_and_maps_offsets():
    stack = np.zeros((2, 10, 12), dtype=np.uint8)
    stack[1, 3:7, 4:9] = 200
    roi = RectROI(xmin=4, xmax=9, ymin=3, ymax=7)
    frame, transform = extract_preview_frame(stack, 1, roi=roi)
    assert frame.shape == (4, 5)
    assert np.all(frame == 200)
    assert transform.x_offset == 4
    assert transform.y_offset == 3


def test_extract_preview_frame_validates_z_range_and_global_index():
    stack = np.zeros((5, 4, 4), dtype=np.uint8)
    z_range = ZRange(zmin=1, zmax=4)
    frame, transform = extract_preview_frame(stack, 2, z_range=z_range)
    assert frame.shape == (4, 4)
    assert transform.z_offset == 1

    with pytest.raises(ValueError, match="outside selected Z-range"):
        extract_preview_frame(stack, 0, z_range=z_range)
    with pytest.raises(ValueError, match="frame_index"):
        extract_preview_frame(stack, 9)


def test_extract_preview_frame_never_calls_full_stack_roi(monkeypatch):
    stack = np.ones((8, 64, 64), dtype=np.uint8)

    def _boom(*_args, **_kwargs):
        raise AssertionError("preview path must not call full-stack apply_rect_roi")

    monkeypatch.setattr("morphostack.core.segmentation.apply_rect_roi", _boom)
    monkeypatch.setattr("morphostack.core.preview.apply_rect_roi", _boom, raising=False)

    frame, _transform = extract_preview_frame(
        stack,
        3,
        roi=RectROI(xmin=10, xmax=40, ymin=5, ymax=50),
        z_range=ZRange(zmin=1, zmax=7),
    )
    assert frame.shape == (45, 30)
    # Full-stack helper remains available for analyze; only preview extract is restricted.
    assert callable(apply_rect_roi)
