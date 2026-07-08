from __future__ import annotations

import numpy as np

from morphostack.core import VoxelSize, analyze_stack
from morphostack.core.export import analysis_run_warnings, object_tracking_warnings
from morphostack.core.pipeline import ObjectSeed, build_tracking_diagnostics, _track_object


def moving_dot_stack() -> np.ndarray:
    stack = np.zeros((4, 30, 30), dtype=np.uint8)
    positions = [(10, 10), (12, 12), (14, 14), (26, 26)]
    for idx, (x, y) in enumerate(positions):
        stack[idx, y - 2 : y + 3, x - 2 : x + 3] = 220
    return stack


def test_tracking_diagnostics_flags_lost_frames():
    voxel = VoxelSize(1.0, 1.0, 1.0)
    seed = ObjectSeed(x=10, y=10, frame_index=0, radius=4.0, max_tracking_dist_um=3.0)
    analysis = analyze_stack(moving_dot_stack(), thresholds=100, voxel_size=voxel, object_seed=seed)

    assert analysis.tracking is not None
    assert analysis.tracking.lost_frame_count >= 1
    warnings = object_tracking_warnings(analysis.tracking)
    codes = {warning["code"] for warning in warnings}
    assert "tracking_lost_some_frames" in codes or "tracking_lost_many_frames" in codes


def test_analysis_run_warnings_includes_tracking_and_default_voxel():
    voxel = VoxelSize(1.0, 1.0, 1.0)
    seed = ObjectSeed(x=10, y=10, frame_index=0, radius=4.0, max_tracking_dist_um=3.0)
    analysis = analyze_stack(moving_dot_stack(), thresholds=100, voxel_size=voxel, object_seed=seed)
    warnings = analysis_run_warnings(analysis, voxel_source="default")
    codes = {warning["code"] for warning in warnings}
    assert "default_voxel_size" in codes
    assert "tracking_lost_some_frames" in codes or "tracking_lost_many_frames" in codes


def test_roi_boundary_touch_detected_on_cropped_stack():
    stack = np.zeros((1, 20, 20), dtype=np.uint8)
    stack[0, 0:6, 0:6] = 255
    thresholds = (100.0,)
    seed = ObjectSeed(x=2, y=2, frame_index=0, radius=3.0)
    result = _track_object(stack, thresholds, seed, frame_offset=0, voxel_size=VoxelSize(1.0, 1.0, 1.0))
    diagnostics = build_tracking_diagnostics(result, frame_offset=0, image_shape=(20, 20))

    assert diagnostics.records[0].tracked is True
    assert diagnostics.records[0].touches_roi_boundary is True
    warnings = object_tracking_warnings(diagnostics)
    assert any(warning["code"] == "roi_boundary_touch" for warning in warnings)