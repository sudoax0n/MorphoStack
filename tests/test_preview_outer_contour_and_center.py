"""Preview display: single exterior contour, no inner red rim; tracked center payload."""

from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.contours import SegmentationPreview
from morphostack.core.preview import exterior_highlight_edge, overlay_preview
from morphostack.core.seeded_vesicle import segment_slice_seeded, track_seeded_vesicle_stack


def _thick_hollow_ring(h=80, w=80, cx=40, cy=40, r_in=14, r_out=22, value=200):
    yy, xx = np.ogrid[:h, :w]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.uint8)
    frame[(d2 >= r_in**2) & (d2 <= r_out**2)] = value
    return frame


def test_exterior_highlight_edge_no_inner_rim():
    """Hole-filled exterior edge must not paint the hollow-ring lumen rim."""
    frame = _thick_hollow_ring()
    hollow = frame >= 100
    # Unfilled hollow ring would have both rims after naive erosion; filled exterior only.
    edge = exterior_highlight_edge(hollow)
    assert np.any(edge)
    # Pixels near lumen interior (r=10) must not be edge of filled exterior.
    assert not edge[40, 40 + 10]
    # Outer rim region should include some edge pixels near r_out.
    assert np.any(edge[40, 40 + 18 : 40 + 24]) or np.any(edge[40 - 24 : 40 + 24, 40 + 20])


def test_overlay_with_contour_suppresses_red_highlight():
    """Seeded contour path: green exterior only — no red highlight paint."""
    pytest.importorskip("PIL")
    from PIL import Image

    frame = _thick_hollow_ring()
    res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=20, refine=False)
    assert res.ok and res.contour_xy is not None
    preview = SegmentationPreview(
        threshold=100.0,
        contour=res.contour_xy,
        area_px2=float(res.area_px),
        perimeter_px=float(res.perimeter_px),
        circularity=0.9,
        method=res.method,
    )
    image = overlay_preview(
        frame,
        threshold=100.0,
        preview=preview,
        object_seed=None,
        highlight_mask=res.solid_mask if res.solid_mask is not None else frame >= 100,
    )
    rgb = np.asarray(image)
    # Contour is drawn in green (~31, 230, 137). Red-only edge boost should be absent:
    # count pixels that are strongly red-dominant (R high, G,B suppressed) as in tint.
    red_dom = (rgb[..., 0] > 140) & (rgb[..., 1] < 100) & (rgb[..., 2] < 100)
    # Allow tiny numerical noise; seeded contour path suppresses highlight entirely.
    assert int(np.count_nonzero(red_dom)) < 8, "inner/outer red rim must not appear with contour"


def test_track_center_moves_with_drifting_target():
    """Multi-Z drift: reported center follows target, not fixed seed."""
    n, h, w = 8, 64, 64
    stack = np.zeros((n, h, w), dtype=np.uint8)
    seed_x, seed_y = 20.0, 32.0
    for z in range(n):
        cx = 20 + z * 3  # drift +21 px by last frame
        cy = 32
        yy, xx = np.ogrid[:h, :w]
        r_in, r_out = 8, 12
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        stack[z][(d2 >= r_in**2) & (d2 <= r_out**2)] = 200
    results = track_seeded_vesicle_stack(
        stack,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_frame=0,
        seed_radius=14,
    )
    assert results[0].ok
    last_ok = [r for r in results if r.ok]
    assert len(last_ok) >= 4
    final = last_ok[-1]
    # Center must have moved substantially toward the drifted object.
    assert final.center_xy[0] > seed_x + 8
    assert abs(final.center_xy[1] - seed_y) < 6


def test_preview_payload_tracked_center_exact_only(tmp_path):
    """API: exact accepted frames expose tracked_center; provisional/lost use null."""
    tifffile = pytest.importorskip("tifffile")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from morphostack.api.app import create_app

    n, h, w = 5, 48, 48
    stack = np.zeros((n, h, w), dtype=np.uint8)
    for z in range(n):
        cx, cy = 18 + z * 2, 24
        yy, xx = np.ogrid[:h, :w]
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        stack[z][(d2 >= 6**2) & (d2 <= 10**2)] = 200
    path = tmp_path / "drift.tif"
    tifffile.imwrite(path, stack)

    client = TestClient(create_app())
    seed = {"x": 18, "y": 24, "frame_index": 0, "radius": 12}
    # Exact frame near end of drift
    exact = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 4,
            "object_seed": seed,
            "fast_preview": False,
            "force_sync_exact": True,
        },
    )
    assert exact.status_code == 200
    body = exact.json()
    assert body["preview_quality"] == "exact"
    method = str(body.get("method") or "")
    accepted = (
        body.get("area_px2", 0) > 0
        and "fail" not in method
        and "lost" not in method
        and "gap" not in method
        and "reject" not in method
        and "unreached" not in method
    )
    if accepted:
        assert body["tracked_center_x"] is not None
        assert body["tracked_center_y"] is not None
        assert body["tracked_center_x"] > 18  # drifted
        assert abs(body["tracked_center_x"] - 18) > 2 or body["tracked_center_y"] != 24
    else:
        # Lost/reject: centers must be null (never original seed)
        assert body["tracked_center_x"] is None
        assert body["tracked_center_y"] is None

    fast = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 4,
            "object_seed": seed,
            "fast_preview": True,
        },
    )
    assert fast.status_code == 200
    fbody = fast.json()
    assert fbody["preview_quality"] == "provisional"
    assert fbody["tracked_center_x"] is None
    assert fbody["tracked_center_y"] is None
