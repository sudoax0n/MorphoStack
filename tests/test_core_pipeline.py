from __future__ import annotations

import numpy as np
import pytest

from morphostack.core import RectROI, VoxelSize, analyze_frame, analyze_stack
from morphostack.core.pipeline import normalize_thresholds


def test_analyze_frame_returns_metrics_for_detected_component():
    image = np.zeros((8, 8), dtype=np.uint8)
    image[2:5, 1:4] = 200

    result = analyze_frame(
        image,
        frame_index=7,
        threshold=100,
        voxel_size=VoxelSize(0.5, 2.0, 1.0),
        prefer_opencv=False,
    )

    assert result.frame_index == 7
    assert result.contour is not None
    assert result.metrics is not None
    assert result.metrics.area_um2 == 9.0
    assert result.metrics.perimeter_um == 15.0


def test_analyze_frame_returns_empty_result_without_component():
    result = analyze_frame(
        np.zeros((4, 4)),
        frame_index=0,
        threshold=1,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
    )

    assert result.contour is None
    assert result.metrics is None


def test_analyze_stack_uses_scalar_threshold_for_all_frames():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200

    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    assert len(result.frames) == 2
    assert len(result.valid_frames) == 2
    assert [frame.threshold for frame in result.frames] == [100.0, 100.0]


def test_analyze_stack_accepts_per_frame_thresholds():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 50
    stack[1, 2:5, 1:4] = 200

    result = analyze_stack(
        stack,
        thresholds=[100, 100],
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    assert result.frames[0].metrics is None
    assert result.frames[1].metrics is not None


def test_analyze_stack_applies_roi_before_analysis():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 1:3, 1:3] = 200
    stack[0, 5:7, 5:7] = 200

    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        roi=RectROI(xmin=0, xmax=4, ymin=0, ymax=4),
        prefer_opencv=False,
    )

    assert result.frames[0].contour is not None
    assert result.frames[0].contour[:, 0].max() <= 3


def test_analyze_stack_rejects_non_stack_input():
    with pytest.raises(ValueError, match="grayscale stack"):
        analyze_stack(np.zeros((8, 8)), thresholds=1, voxel_size=VoxelSize(1.0, 1.0, 1.0))


def test_normalize_thresholds_rejects_wrong_length():
    with pytest.raises(ValueError, match="threshold sequence length"):
        normalize_thresholds([1, 2], frame_count=3)
