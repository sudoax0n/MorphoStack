from __future__ import annotations

from io import StringIO

import numpy as np

from morphostack.core import VoxelSize, analyze_stack
from morphostack.core.export import analysis_rows, write_analysis_csv


def test_analysis_rows_include_empty_and_valid_frames():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[1, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    rows = analysis_rows(analysis)

    assert rows[0]["has_contour"] is False
    assert rows[0]["area_um2"] == 0.0
    assert rows[0]["aspect_ratio"] == 0.0
    assert rows[1]["has_contour"] is True
    assert rows[1]["area_um2"] == 9.0
    assert rows[1]["aspect_ratio"] == 1.0
    assert rows[1]["solidity"] == 1.0


def test_write_analysis_csv_writes_header_and_rows():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )
    buffer = StringIO()

    write_analysis_csv(analysis, buffer)

    csv_text = buffer.getvalue()
    assert "frame_index,threshold,method,has_contour" in csv_text
    assert "bbox_width_um,bbox_height_um,aspect_ratio,equivalent_diameter_um,solidity" in csv_text
    assert "mesh_surface_area_um2,mesh_volume_um3" in csv_text
    assert "0,100.0,fallback,True" in csv_text
