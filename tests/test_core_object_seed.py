"""Tests for object seed selection: selected_component_contour and analyze_stack with ObjectSeed."""
from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.contours import selected_component_contour, segmentation_preview
from morphostack.core.pipeline import ObjectSeed, analyze_stack
from morphostack.core.models import VoxelSize


def two_circle_frame(height: int = 40, width: int = 80) -> np.ndarray:
    """Frame with a large circle (left) and a small circle (right) above threshold."""
    frame = np.zeros((height, width), dtype=np.uint8)
    # Large circle at x=20, y=20, radius=10
    for y in range(height):
        for x in range(width):
            if (x - 20) ** 2 + (y - 20) ** 2 <= 10 ** 2:
                frame[y, x] = 200
    # Small circle at x=60, y=20, radius=5
    for y in range(height):
        for x in range(width):
            if (x - 60) ** 2 + (y - 20) ** 2 <= 5 ** 2:
                frame[y, x] = 200
    return frame


def two_circle_stack(n_frames: int = 3) -> np.ndarray:
    frame = two_circle_frame()
    return np.stack([frame] * n_frames, axis=0)


# ---------------------------------------------------------------------------
# selected_component_contour tests
# ---------------------------------------------------------------------------


def test_selected_component_contour_picks_large_when_seeded_left():
    frame = two_circle_frame()
    mask = frame >= 100
    contour = selected_component_contour(mask, seed_x=20, seed_y=20)
    assert contour is not None
    cx = float(contour[:, 0].mean())
    # The large circle is centred at x=20; should be left of 40.
    assert cx < 40


def test_selected_component_contour_picks_small_when_seeded_right():
    frame = two_circle_frame()
    mask = frame >= 100
    contour = selected_component_contour(mask, seed_x=60, seed_y=20)
    assert contour is not None
    cx = float(contour[:, 0].mean())
    # The small circle is centred at x=60; should be right of 40.
    assert cx > 40


def test_selected_component_contour_returns_none_for_empty_mask():
    mask = np.zeros((20, 20), dtype=bool)
    assert selected_component_contour(mask, seed_x=10, seed_y=10) is None


def test_selected_component_contour_background_seed_picks_nearest():
    """Seed in background: nearest centroid is selected."""
    frame = two_circle_frame()
    mask = frame >= 100
    # Seed at x=45, y=20 — background, equidistant-ish but closer to small circle (x=60).
    contour = selected_component_contour(mask, seed_x=45, seed_y=20)
    assert contour is not None
    cx = float(contour[:, 0].mean())
    # Nearest centroid is the small circle (x=60), not the large (x=20).
    assert cx > 40


# ---------------------------------------------------------------------------
# segmentation_preview with object_seed
# ---------------------------------------------------------------------------


def test_segmentation_preview_without_seed_picks_largest():
    frame = two_circle_frame()
    preview = segmentation_preview(frame, threshold=100, prefer_opencv=True, object_seed=None)
    assert preview.contour is not None
    cx = float(preview.contour[:, 0].mean())
    assert cx < 40  # largest (left) circle


def test_segmentation_preview_with_seed_picks_target():
    frame = two_circle_frame()
    preview = segmentation_preview(frame, threshold=100, prefer_opencv=True, object_seed=(60, 20))
    assert preview.contour is not None
    cx = float(preview.contour[:, 0].mean())
    assert cx > 40  # small (right) circle
    assert preview.method == "seed"


# ---------------------------------------------------------------------------
# analyze_stack with ObjectSeed
# ---------------------------------------------------------------------------


VOXEL = VoxelSize(x_um=1.0, y_um=1.0, z_um=1.0)


def test_analyze_stack_without_seed_uses_largest():
    stack = two_circle_stack(n_frames=3)
    analysis = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, prefer_opencv=True)
    for frame in analysis.frames:
        if frame.contour is not None:
            cx = float(frame.contour[:, 0].mean())
            assert cx < 40  # largest circle


def test_analyze_stack_with_seed_uses_target_object():
    stack = two_circle_stack(n_frames=3)
    seed = ObjectSeed(x=60, y=20, frame_index=1)
    analysis = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, prefer_opencv=True, object_seed=seed)
    for frame in analysis.frames:
        if frame.contour is not None:
            cx = float(frame.contour[:, 0].mean())
            # All frames should track the small (right) circle.
            assert cx > 40


def test_analyze_stack_seed_area_is_smaller_than_largest():
    stack = two_circle_stack(n_frames=3)
    analysis_no_seed = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, prefer_opencv=True)
    seed = ObjectSeed(x=60, y=20, frame_index=1)
    analysis_seed = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, prefer_opencv=True, object_seed=seed)

    avg_area_no_seed = sum(
        f.metrics.area_um2 for f in analysis_no_seed.valid_frames
    ) / len(analysis_no_seed.valid_frames)
    avg_area_seed = sum(
        f.metrics.area_um2 for f in analysis_seed.valid_frames
    ) / len(analysis_seed.valid_frames)

    # Seeded on the small circle: area must be noticeably smaller.
    assert avg_area_seed < avg_area_no_seed * 0.5


def test_stack_view_transform_coords():
    from morphostack.core.pipeline import StackViewTransform, RectROI, ZRange, ObjectSeed
    import numpy as np

    transform = StackViewTransform.create(
        roi=RectROI(xmin=10, xmax=30, ymin=5, ymax=25),
        z_range=ZRange(zmin=2, zmax=5),
        raw_shape=(10, 40, 40)
    )

    # Test valid seed mapping
    seed = ObjectSeed(x=15, y=10, frame_index=3)
    lx, ly, lz = transform.to_local_seed(seed)
    assert lx == 5
    assert ly == 5
    assert lz == 1

    # Test seed outside ROI X
    with pytest.raises(ValueError, match="outside ROI bounds"):
        transform.to_local_seed(ObjectSeed(x=5, y=10, frame_index=3))

    # Test seed outside ROI Y
    with pytest.raises(ValueError, match="outside ROI bounds"):
        transform.to_local_seed(ObjectSeed(x=15, y=30, frame_index=3))

    # Test seed outside Z-range
    with pytest.raises(ValueError, match="outside Z-range"):
        transform.to_local_seed(ObjectSeed(x=15, y=10, frame_index=1))

    # Test seed outside stack limits
    with pytest.raises(ValueError, match="outside full image bounds"):
        transform.to_local_seed(ObjectSeed(x=45, y=10, frame_index=3))

    # Test global contour mapping
    local_contour = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=np.float64)
    global_contour = transform.to_global_contour(local_contour)
    assert np.allclose(global_contour, np.array([[10, 5], [20, 5], [20, 15], [10, 15]], dtype=np.float64))


def test_analyze_stack_seed_outside_roi_rejected():
    from morphostack.core.pipeline import RectROI
    stack = two_circle_stack(n_frames=3)
    seed = ObjectSeed(x=60, y=20, frame_index=1)
    
    # ROI covers left circle (xmin=0, xmax=40), but seed is at x=60 (right circle)
    with pytest.raises(ValueError, match="outside ROI bounds"):
        analyze_stack(
            stack,
            thresholds=100,
            voxel_size=VOXEL,
            roi=RectROI(xmin=0, xmax=40, ymin=0, ymax=40),
            object_seed=seed
        )


def test_analyze_stack_seed_outside_zrange_rejected():
    from morphostack.core.pipeline import ZRange
    stack = two_circle_stack(n_frames=3)
    seed = ObjectSeed(x=60, y=20, frame_index=2) # z = 2
    
    # Z-range is [0, 2), so frame index 2 is outside it
    with pytest.raises(ValueError, match="outside Z-range"):
        analyze_stack(
            stack,
            thresholds=100,
            voxel_size=VOXEL,
            z_range=ZRange(zmin=0, zmax=2),
            object_seed=seed
        )


def test_tracking_by_overlap_and_fallback():
    # Construct a synthetic stack where an object moves slightly between frames.
    stack = np.zeros((3, 20, 20), dtype=np.uint8)
    
    # Frame 0: component at (10, 10), size 5x5 (area 25)
    stack[0, 8:13, 8:13] = 200
    
    # Frame 1: component at (11, 11), size 5x5 (area 25) - overlaps with Frame 0
    stack[1, 9:14, 9:14] = 200
    
    # Frame 2: component moves further to (15, 15) - no overlap with Frame 1 component,
    # but within max_dist_px (approx 5.6 pixels centroid distance)
    stack[2, 13:18, 13:18] = 200

    seed = ObjectSeed(x=10, y=10, frame_index=0)
    analysis = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, object_seed=seed)
    
    # Assert that all 3 frames successfully tracked the object
    assert analysis.frames[0].contour is not None
    assert analysis.frames[1].contour is not None
    assert analysis.frames[2].contour is not None
    
    # Confirm centroid coordinates in frame 2 are around (15, 15)
    c2 = analysis.frames[2].contour
    cx = float(c2[:, 0].mean())
    cy = float(c2[:, 1].mean())
    assert abs(cx - 15) <= 1.0
    assert abs(cy - 15) <= 1.0


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


def stack_tiff_bytes(n_frames: int = 3) -> bytes:
    tifffile = pytest.importorskip("tifffile")
    from io import BytesIO
    stack = two_circle_stack(n_frames)
    buf = BytesIO()
    tifffile.imwrite(buf, stack, photometric="minisblack")
    return buf.getvalue()


def write_two_circle_tiff(path) -> None:
    tifffile = pytest.importorskip("tifffile")
    tifffile.imwrite(str(path), two_circle_stack(), photometric="minisblack")


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from morphostack.api import create_app
    return TestClient(create_app())


def test_api_preview_with_seed_returns_seed_method(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_two_circle_tiff(path)
    response = client.post("/preview", json={
        "path": str(path),
        "threshold": 100,
        "frame_index": 0,
        "object_seed": {"x": 60, "y": 20, "frame_index": 0},
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "seed"


def test_api_analyze_with_seed_smaller_area(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_two_circle_tiff(path)

    resp_no_seed = client.post("/analyze", json={
        "path": str(path),
        "threshold": 100,
    })
    resp_seed = client.post("/analyze", json={
        "path": str(path),
        "threshold": 100,
        "object_seed": {"x": 60, "y": 20, "frame_index": 1},
    })
    assert resp_no_seed.status_code == 200
    assert resp_seed.status_code == 200

    rows_no_seed = resp_no_seed.json()["rows"]
    rows_seed = resp_seed.json()["rows"]

    area_no_seed = sum(r["area_um2"] for r in rows_no_seed if r["has_contour"])
    area_seed = sum(r["area_um2"] for r in rows_seed if r["has_contour"])

    assert area_seed < area_no_seed * 0.5


def test_api_upload_mesh_preview_with_seed_selects_correct_object(client):
    tiff_data = stack_tiff_bytes(n_frames=3)
    # Seed 60, 20 is the small circle.
    response = client.post(
        "/upload/mesh-preview",
        data={
            "threshold": 100,
            "object_seed_x": 60,
            "object_seed_y": 20,
            "object_seed_frame": 1,
            "downsample": 1,
        },
        files={"file": ("stack.tif", tiff_data, "image/tiff")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["has_mesh"] is True
    # The small sphere should have a smaller volume than the full/default/largest sphere
    volume = payload["volume_um3"]
    
    # Run with large circle seed
    response_large = client.post(
        "/upload/mesh-preview",
        data={
            "threshold": 100,
            "object_seed_x": 20,
            "object_seed_y": 20,
            "object_seed_frame": 1,
            "downsample": 1,
        },
        files={"file": ("stack.tif", tiff_data, "image/tiff")},
    )
    assert response_large.status_code == 200
    volume_large = response_large.json()["volume_um3"]
    assert volume < volume_large * 0.5


def test_api_upload_analyze_with_seed_selects_correct_object(client):
    tiff_data = stack_tiff_bytes(n_frames=3)
    response = client.post(
        "/upload/analyze",
        data={
            "threshold": 100,
            "object_seed_x": 60,
            "object_seed_y": 20,
            "object_seed_frame": 1,
        },
        files={"file": ("stack.tif", tiff_data, "image/tiff")},
    )
    assert response.status_code == 200
    rows = response.json()["rows"]
    areas = [r["area_um2"] for r in rows if r["has_contour"]]
    assert len(areas) == 3
    # Centred at x=60, radius=5 => area approx pi*r^2 approx 78 px
    assert all(a < 120 for a in areas)


def test_api_upload_preview_with_seed_selects_correct_object(client):
    tiff_data = stack_tiff_bytes(n_frames=3)
    response = client.post(
        "/upload/preview",
        data={
            "threshold": 100,
            "frame_index": 0,
            "object_seed_x": 60,
            "object_seed_y": 20,
            "object_seed_frame": 0,
        },
        files={"file": ("stack.tif", tiff_data, "image/tiff")},
    )
    assert response.status_code == 200
    assert response.json()["method"] == "seed"


def test_api_mesh_preview_different_seeds_different_geometry(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_two_circle_tiff(path)
    
    resp_small = client.post("/mesh-preview", json={
        "path": str(path),
        "threshold": 100,
        "object_seed": {"x": 60, "y": 20, "frame_index": 1},
        "downsample": 1
    })
    resp_large = client.post("/mesh-preview", json={
        "path": str(path),
        "threshold": 100,
        "object_seed": {"x": 20, "y": 20, "frame_index": 1},
        "downsample": 1
    })
    assert resp_small.status_code == 200
    assert resp_large.status_code == 200
    vol_small = resp_small.json()["volume_um3"]
    vol_large = resp_large.json()["volume_um3"]
    assert vol_small < vol_large * 0.5


def test_custom_and_dynamic_tracking_distance():
    VOXEL = VoxelSize(x_um=1.0, y_um=1.0, z_um=1.0)
    # Construct a synthetic stack where an object moves slightly between frames.
    stack = np.zeros((3, 20, 20), dtype=np.uint8)
    # Frame 0: component at (10, 10), size 5x5
    stack[0, 8:13, 8:13] = 200
    # Frame 1: component at (11, 11), size 5x5 (overlaps Frame 0)
    stack[1, 9:14, 9:14] = 200
    # Frame 2: component moves further to (16, 16) - no overlap, distance is 7.07 pixels.
    stack[2, 14:19, 14:19] = 200

    # Test 1: with a small custom tracking distance max_tracking_dist_um = 3.0 um
    # The jump of 7.07 px should exceed 3.0 um, so frame 2 tracking is lost.
    seed_short = ObjectSeed(x=10, y=10, frame_index=0, radius=5.0, max_tracking_dist_um=3.0)
    analysis_short = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, object_seed=seed_short)
    assert analysis_short.frames[0].contour is not None
    assert analysis_short.frames[1].contour is not None
    assert analysis_short.frames[2].contour is None

    # Test 2: with default tracking distance, it is dynamic.
    # 3x radius = 15.0 px.
    # The jump of 7.07 px is < 15 px, so it should be tracked!
    seed_dynamic = ObjectSeed(x=10, y=10, frame_index=0, radius=5.0)
    analysis_dynamic = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, object_seed=seed_dynamic)
    assert analysis_dynamic.frames[0].contour is not None
    assert analysis_dynamic.frames[1].contour is not None
    assert analysis_dynamic.frames[2].contour is not None
