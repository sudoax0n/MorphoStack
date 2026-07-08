import numpy as np
import pytest

from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import analyze_stack
from morphostack.core.export import analysis_rows, analysis_summary


def test_excluded_frames_skip_mesh_and_summary_metrics():
    stack = np.zeros((3, 20, 20), dtype=np.uint8)
    for z in range(3):
        stack[z, 6:14, 6:14] = 220

    analysis_all = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        include_mesh=True,
        prefer_opencv=False,
    )
    analysis_excluded = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        include_mesh=True,
        prefer_opencv=False,
        excluded_frames=[1],
    )

    assert len(analysis_all.valid_frames) == 3
    assert len(analysis_excluded.valid_frames) == 2
    assert analysis_excluded.excluded_frames == frozenset({1})
    assert analysis_excluded.mesh is not None
    assert analysis_all.mesh is not None
    assert analysis_excluded.mesh.volume_um3 < analysis_all.mesh.volume_um3

    rows = analysis_rows(analysis_excluded)
    assert rows[1]["excluded"] is True
    assert rows[1]["has_contour"] is False
    assert rows[0]["excluded"] is False

    summary = analysis_summary(analysis_excluded)
    assert summary["valid_frame_count"] == 2


def test_excluded_frame_out_of_range_raises():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 2:5] = 200
    with pytest.raises(ValueError, match="excluded frame"):
        analyze_stack(
            stack,
            thresholds=100,
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
            excluded_frames=[99],
        )