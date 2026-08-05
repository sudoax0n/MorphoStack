from __future__ import annotations

import numpy as np
import pytest

from morphostack.core import ObjectSeed, RectROI, VoxelSize, ZRange, analyze_frame, analyze_stack
from morphostack.core.pipeline import crop_stack_xy, normalize_thresholds, seed_isolation_roi


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
    assert result.profile == "vesicle"
    assert [frame.threshold for frame in result.frames] == [100.0, 100.0]
    assert [frame.profile for frame in result.frames] == ["vesicle", "vesicle"]


def test_analyze_stack_accepts_rbc_profile():
    from morphostack.core.pipeline import ObjectSeed
    from morphostack.core.rbc_capabilities import calibration_from_override

    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200

    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="rbc",
        prefer_opencv=False,
        object_seed=ObjectSeed(x=2.5, y=3.5, frame_index=0, radius=3.0),
        source_path="cell.tif",
        calibration=calibration_from_override(1.0, 1.0, 1.0, source_format="tiff"),
    )

    assert result.profile == "rbc"
    assert result.frames[0].profile == "rbc"
    assert result.frames[0].metrics is not None


def test_analyze_stack_rejects_unknown_profile():
    with pytest.raises(ValueError, match="analysis profile"):
        analyze_stack(
            np.zeros((1, 8, 8)),
            thresholds=1,
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
            profile="unknown",
        )


def test_analyze_stack_can_include_mesh_measurement():
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    stack = np.zeros((3, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200

    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
        include_mesh=True,
    )

    assert result.mesh is not None
    assert result.mesh.surface_area_um2 > 0
    assert result.mesh.volume_um3 > 0


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


def test_analyze_stack_applies_z_range_and_preserves_source_frame_indices():
    stack = np.zeros((4, 8, 8), dtype=np.uint8)
    stack[1:3, 2:5, 1:4] = 200

    result = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        z_range=ZRange(zmin=1, zmax=3),
        prefer_opencv=False,
    )

    assert [frame.frame_index for frame in result.frames] == [1, 2]
    assert len(result.valid_frames) == 2
    assert result.z_range == ZRange(1, 3)


def test_analyze_stack_rejects_non_stack_input():
    with pytest.raises(ValueError, match="grayscale stack"):
        analyze_stack(np.zeros((8, 8)), thresholds=1, voxel_size=VoxelSize(1.0, 1.0, 1.0))


def test_normalize_thresholds_rejects_wrong_length():
    with pytest.raises(ValueError, match="threshold sequence length"):
        normalize_thresholds([1, 2], frame_count=3)


def test_crop_stack_xy_reduces_dimensions():
    stack = np.arange(2 * 10 * 12, dtype=np.uint8).reshape(2, 10, 12)
    roi = RectROI(xmin=2, xmax=8, ymin=1, ymax=5)
    cropped = crop_stack_xy(stack, roi)
    assert cropped.shape == (2, 4, 6)
    assert np.array_equal(cropped, stack[:, 1:5, 2:8])


def test_seed_without_roi_isolates_one_blob_on_two_blob_stack():
    """Seed + no ROI crops around seed so only one object is measured."""
    stack = np.zeros((3, 40, 100), dtype=np.uint8)
    # Left blob and far-right blob
    for y in range(40):
        for x in range(100):
            if (x - 20) ** 2 + (y - 20) ** 2 <= 8 ** 2:
                stack[:, y, x] = 200
            if (x - 80) ** 2 + (y - 20) ** 2 <= 8 ** 2:
                stack[:, y, x] = 200

    seed = ObjectSeed(x=80, y=20, frame_index=1, radius=8.0)
    isolation = seed_isolation_roi(seed, width=100, height=40)
    # Neighbor at x=20 must fall outside isolation crop
    assert isolation.xmin > 30

    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=seed,
        prefer_opencv=False,
    )
    for frame in analysis.frames:
        assert frame.contour is not None
        cx = float(frame.contour[:, 0].mean())
        assert cx > 60
        assert float(frame.contour[:, 0].min()) > 40
