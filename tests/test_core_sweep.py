from __future__ import annotations

import io

import numpy as np
import pytest

from morphostack.core import (
    VoxelSize,
    threshold_sweep,
    threshold_sweep_rows,
    threshold_values,
    write_threshold_sweep_csv,
)


def test_threshold_values_includes_stop():
    assert threshold_values(50, 100, 25) == (50.0, 75.0, 100.0)


def test_threshold_values_rejects_invalid_range():
    with pytest.raises(ValueError, match="step"):
        threshold_values(50, 100, 0)

    with pytest.raises(ValueError, match="stop"):
        threshold_values(100, 50, 10)


def test_threshold_sweep_summarizes_each_threshold():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200

    results = threshold_sweep(
        stack,
        thresholds=(50, 250),
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
        voxel_source="override",
    )
    rows = threshold_sweep_rows(results)

    assert len(results) == 2
    assert rows[0]["threshold"] == 50.0
    assert rows[0]["valid_frame_count"] == 2
    assert rows[0]["area_um2_mean"] == 9.0
    assert rows[0]["warning_codes"] == ""
    assert rows[1]["threshold"] == 250.0
    assert rows[1]["valid_frame_count"] == 0
    assert rows[1]["warning_codes"] == "no_valid_contours"


def test_write_threshold_sweep_csv():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    results = threshold_sweep(
        stack,
        thresholds=(100,),
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )
    handle = io.StringIO()

    write_threshold_sweep_csv(results, handle)

    csv_text = handle.getvalue()
    assert csv_text.startswith("threshold,profile,frame_count,valid_frame_count")
    assert "100.0,vesicle,1,1,1.0" in csv_text
