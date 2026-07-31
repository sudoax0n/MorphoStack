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
    contour = selected_component_contour(mask, seed_x=45, seed_y=20, seed_radius=5.0)
    assert contour is not None
    cx = float(contour[:, 0].mean())
    # Nearest centroid is the small circle (x=60), not the large (x=20).
    assert cx > 40


def test_hollow_ring_seed_in_center_selects_ring_not_neighbor():
    """GUV-like rings: seed in dark interior must pick the enclosing membrane."""
    frame = np.zeros((80, 120), dtype=np.uint8)
    yy, xx = np.ogrid[:80, :120]
    # Left ring centered (30, 40)
    d1 = (xx - 30) ** 2 + (yy - 40) ** 2
    frame[(d1 >= 12**2) & (d1 <= 16**2)] = 200
    # Right ring centered (90, 40) — larger noise neighbor
    d2 = (xx - 90) ** 2 + (yy - 40) ** 2
    frame[(d2 >= 14**2) & (d2 <= 18**2)] = 200
    mask = frame >= 100
    contour = selected_component_contour(mask, seed_x=30, seed_y=40, seed_radius=14.0)
    assert contour is not None
    cx = float(contour[:, 0].mean())
    assert cx < 60  # left ring, not right


def test_merge_blob_rejected_when_ref_area_from_single_vesicle():
    """Area prior rejects a multi-object merge much larger than the seed object."""
    from morphostack.core.object_select import pick_component_from_mask

    frame = np.zeros((60, 100), dtype=np.uint8)
    frame[20:35, 20:35] = 200  # ~225 px object
    frame[20:50, 40:90] = 200  # huge merged block
    mask = frame >= 100
    # Seed near small object center
    comp = pick_component_from_mask(mask, seed_x=27, seed_y=27, seed_radius=8.0, ref_area=225.0)
    assert comp is not None
    assert comp["area"] < 400


def _two_vesicle_fused_neck_mask(
    height: int = 100,
    width: int = 140,
    c1: tuple[int, int] = (40, 50),
    c2: tuple[int, int] | None = None,
    r: int = 22,
    overlap_px: int = 6,
) -> np.ndarray:
    """Two solid disks that genuinely touch/overlap (natural neck, no painted bar).

    Centers are placed at ``2*r - overlap_px`` so the union is a single connected
    component with a narrow contact zone from circle-circle geometry alone.
    """
    mask = np.zeros((height, width), dtype=bool)
    yy, xx = np.ogrid[:height, :width]
    cx1, cy1 = c1
    if c2 is None:
        c2 = (cx1 + max(2, 2 * int(r) - int(overlap_px)), cy1)
    cx2, cy2 = c2
    mask[(xx - cx1) ** 2 + (yy - cy1) ** 2 <= r ** 2] = True
    mask[(xx - cx2) ** 2 + (yy - cy2) ** 2 <= r ** 2] = True
    return mask


def test_isolate_seeded_mask_splits_fused_neck():
    """DT watershed isolates the seeded vesicle from a thin connecting neck."""
    from morphostack.core.object_select import isolate_seeded_mask

    c1 = (40, 50)
    r = 22
    overlap = 6
    c2 = (c1[0] + 2 * r - overlap, c1[1])
    mask = _two_vesicle_fused_neck_mask(c1=c1, c2=c2, r=r, overlap_px=overlap)
    # Confirm synthetic input is a single connected component before split.
    from morphostack.core.pipeline import get_connected_components

    comps_before = get_connected_components(mask, min_area_px=16)
    assert len(comps_before) == 1

    left = isolate_seeded_mask(mask, seed_x=float(c1[0]), seed_y=float(c1[1]), seed_radius=float(r))
    right = isolate_seeded_mask(mask, seed_x=float(c2[0]), seed_y=float(c2[1]), seed_radius=float(r))

    assert np.any(left)
    assert np.any(right)
    # Seeded left vesicle: left center on FG, right center mostly off.
    assert left[c1[1], c1[0]]
    assert not left[c2[1], c2[0]]
    # Seeded right vesicle: opposite.
    assert right[c2[1], c2[0]]
    assert not right[c1[1], c1[0]]
    # Isolated area much smaller than fused blob.
    assert float(np.count_nonzero(left)) < 0.7 * float(np.count_nonzero(mask))
    assert float(np.count_nonzero(right)) < 0.7 * float(np.count_nonzero(mask))


def test_selected_component_contour_fused_neck_stays_on_seeded_side():
    """Preview seed path: contour encloses only the seeded vesicle, not both centers."""
    c1 = (40, 50)
    r = 22
    overlap = 6
    c2 = (c1[0] + 2 * r - overlap, c1[1])
    mask = _two_vesicle_fused_neck_mask(c1=c1, c2=c2, r=r, overlap_px=overlap)

    contour = selected_component_contour(
        mask,
        seed_x=c1[0],
        seed_y=c1[1],
        seed_radius=float(r),
    )
    assert contour is not None
    assert len(contour) >= 8
    cx = float(contour[:, 0].mean())
    # Contour centroid near left vesicle, not midpoint of both.
    mid_x = 0.5 * (c1[0] + c2[0])
    assert cx < mid_x - 10.0, f"centroid x={cx:.1f} should be on left of mid={mid_x:.1f}"
    # Contour must not wrap both vesicle centers: max x stays left of right center.
    assert float(contour[:, 0].max()) < c2[0] - 5.0


def test_segment_slice_seeded_isolates_fused_neck():
    """Analysis path: segment_slice_seeded keeps the seeded side of a fused neck."""
    from morphostack.core.seeded_vesicle import segment_slice_seeded

    c1 = (40, 50)
    r = 22
    overlap = 6
    c2 = (c1[0] + 2 * r - overlap, c1[1])
    # Bright solid disks with genuine circular contact (no painted bar).
    frame = np.zeros((100, 140), dtype=np.float64)
    mask = _two_vesicle_fused_neck_mask(c1=c1, c2=c2, r=r, overlap_px=overlap)
    frame[mask] = 200.0

    result = segment_slice_seeded(
        frame,
        seed_x=float(c1[0]),
        seed_y=float(c1[1]),
        seed_radius=float(r),
        refine=False,
    )
    assert result.ok, f"expected ok segmentation, got method={result.method}"
    assert result.contour_xy is not None
    cx = float(result.contour_xy[:, 0].mean())
    mid_x = 0.5 * (c1[0] + c2[0])
    assert cx < mid_x - 10.0, f"analysis centroid x={cx:.1f} should be left of mid={mid_x:.1f}"
    assert float(result.contour_xy[:, 0].max()) < c2[0] - 5.0


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
            # Contours are in full-image coordinates after auto isolation crop
            assert float(frame.contour[:, 0].min()) > 40


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
    # Seeded vesicle path should keep the object across mild lateral drift.
    stack = np.zeros((3, 48, 48), dtype=np.uint8)
    stack[0, 18:28, 18:28] = 200
    stack[1, 20:30, 20:30] = 200
    stack[2, 22:32, 22:32] = 200

    seed = ObjectSeed(x=23, y=23, frame_index=0, radius=12)
    analysis = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, object_seed=seed)

    assert analysis.frames[0].contour is not None
    assert analysis.frames[1].contour is not None
    assert analysis.frames[2].contour is not None
    method0 = str(analysis.frames[0].preview.method)
    assert method0.startswith("circle_seed") or method0.startswith("seeded")
    c0 = float(analysis.frames[0].contour[:, 0].mean())
    c2 = float(analysis.frames[2].contour[:, 0].mean())
    assert c2 >= c0 - 1.0


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
    method = str(payload["method"])
    assert (
        method in ("seed", "seeded_rw", "seeded_ws", "circle_seed", "circle_seed_rw", "exact_pending")
        or method.startswith("seeded")
        or method.startswith("circle_seed")
    )


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
    method = str(response.json()["method"])
    assert (
        method in ("seed", "seeded_rw", "seeded_ws", "circle_seed", "circle_seed_rw", "exact_pending")
        or method.startswith("seeded")
        or method.startswith("circle_seed")
    )


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
    # Large lateral jump between consecutive frames.
    stack = np.zeros((3, 64, 64), dtype=np.uint8)
    stack[0, 10:20, 10:20] = 200
    stack[1, 12:22, 12:22] = 200
    stack[2, 45:55, 45:55] = 200  # jumps ~30 px from frame 1

    seed_short = ObjectSeed(x=15, y=15, frame_index=0, radius=8.0, max_tracking_dist_um=5.0)
    analysis_short = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, object_seed=seed_short)
    assert analysis_short.frames[0].contour is not None
    # Far jump should lose track under tight max_tracking_dist_um
    assert analysis_short.frames[2].contour is None

    seed_dynamic = ObjectSeed(x=15, y=15, frame_index=0, radius=8.0)
    analysis_dynamic = analyze_stack(stack, thresholds=100, voxel_size=VOXEL, object_seed=seed_dynamic)
    assert analysis_dynamic.frames[0].contour is not None
    # Default jump gate is looser; may still lose huge jumps — only require seed frame OK
    method0 = str(analysis_dynamic.frames[0].preview.method)
    assert method0.startswith("circle_seed") or method0.startswith("seeded")
