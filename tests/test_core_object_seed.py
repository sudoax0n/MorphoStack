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
