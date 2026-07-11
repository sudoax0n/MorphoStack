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


def _bright_ring_stack(
    *,
    n: int = 3,
    h: int = 64,
    w: int = 64,
    cx: float = 32.0,
    cy: float = 32.0,
    r_in: float = 10.0,
    r_out: float = 14.0,
) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    ring = ((d >= r_in**2) & (d <= r_out**2)).astype(np.uint8) * 200
    return np.stack([ring for _ in range(n)], axis=0)


def test_seeded_path_flags_roi_boundary_touch():
    """Primary seeded-vesicle path must set touches_roi_boundary for export warnings."""
    # Ring pressed into the top-left corner of a small FOV / crop.
    stack = _bright_ring_stack(n=2, h=40, w=40, cx=12.0, cy=12.0, r_in=8.0, r_out=12.0)
    seed = ObjectSeed(x=12, y=12, frame_index=0, radius=12.0)
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=seed,
        profile="vesicle",
    )
    assert analysis.tracking is not None
    tracked = [r for r in analysis.tracking.records if r.tracked]
    assert tracked, "expected at least one tracked seeded frame"
    assert any(r.touches_roi_boundary for r in tracked)
    warnings = object_tracking_warnings(analysis.tracking)
    assert any(w["code"] == "roi_boundary_touch" for w in warnings)


def test_seeded_path_flags_neighbor_merge_on_area_jump():
    """Seeded tracking records likely_neighbor_merge when area explodes vs seed."""
    from morphostack.core.pipeline import FrameTrackingRecord, TrackingDiagnostics

    # Unit-level: diagnostics + export path (geometry-driven merge is covered by QC).
    diagnostics = TrackingDiagnostics(
        records=(
            FrameTrackingRecord(
                frame_index=0,
                tracked=True,
                centroid_x=10.0,
                centroid_y=10.0,
                area_px=100,
                likely_neighbor_merge=False,
            ),
            FrameTrackingRecord(
                frame_index=1,
                tracked=True,
                centroid_x=10.0,
                centroid_y=10.0,
                area_px=400,
                likely_neighbor_merge=True,
            ),
        ),
        seed_frame_area_px=100,
    )
    warnings = object_tracking_warnings(diagnostics)
    assert any(w["code"] == "likely_neighbor_merge" for w in warnings)
    assert warnings[-1]["frame_indices"] == [1]


def test_seeded_analyze_stack_sets_merge_flag_when_qc_suspect(monkeypatch):
    """analyze_stack seeded path must propagate SeededSliceResult.merge_suspect."""
    from morphostack.core import seeded_vesicle as sv
    from morphostack.core.seeded_vesicle import SeededSliceResult

    stack = _bright_ring_stack(n=2, h=48, w=48, cx=24.0, cy=24.0)

    def fake_track(*_args, **_kwargs):
        ok = SeededSliceResult(
            contour_xy=np.array([[20.0, 20.0], [28.0, 20.0], [28.0, 28.0], [20.0, 28.0]], dtype=float),
            solid_mask=np.zeros((48, 48), dtype=bool),
            center_xy=(24.0, 24.0),
            area_px=100.0,
            perimeter_px=40.0,
            method="circle_seed",
            ok=True,
            merge_suspect=False,
        )
        # Paint a solid disk for boundary helper.
        yy, xx = np.ogrid[:48, :48]
        mask = (xx - 24) ** 2 + (yy - 24) ** 2 <= 10**2
        ok = SeededSliceResult(
            ok.contour_xy,
            mask,
            ok.center_xy,
            ok.area_px,
            ok.perimeter_px,
            ok.method,
            True,
            merge_suspect=False,
            qc=None,
        )
        merged = SeededSliceResult(
            ok.contour_xy,
            mask,
            ok.center_xy,
            400.0,  # also trips area jump vs seed 100
            ok.perimeter_px,
            "circle_seed",
            True,
            merge_suspect=True,
            qc=None,
        )
        return [ok, merged]

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", fake_track)
    seed = ObjectSeed(x=24, y=24, frame_index=0, radius=12.0)
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=seed,
        profile="vesicle",
    )
    assert analysis.tracking is not None
    assert analysis.tracking.records[1].tracked is True
    assert analysis.tracking.records[1].likely_neighbor_merge is True
    assert analysis.tracking.records[1].merge_suspect is True
    assert analysis.tracking.records[1].merge_rejected is False
    warnings = object_tracking_warnings(analysis.tracking)
    assert any(w["code"] == "likely_neighbor_merge" for w in warnings)
    assert not any(w["code"] == "merge_suspect_rejected" for w in warnings)


def test_merge_reject_produces_distinct_warning_not_just_track_loss(monkeypatch):
    """circle_seed_merge_reject must surface merge_suspect_rejected with frame index."""
    from morphostack.core import seeded_vesicle as sv
    from morphostack.core.pipeline import tracking_diagnostics_payload
    from morphostack.core.seeded_vesicle import SeededSliceResult

    stack = _bright_ring_stack(n=3, h=40, w=40, cx=20.0, cy=20.0)

    def fake_track(*_args, **_kwargs):
        yy, xx = np.ogrid[:40, :40]
        mask = (xx - 20) ** 2 + (yy - 20) ** 2 <= 8**2
        ok = SeededSliceResult(
            contour_xy=np.array([[16.0, 16.0], [24.0, 16.0], [24.0, 24.0], [16.0, 24.0]], dtype=float),
            solid_mask=mask,
            center_xy=(20.0, 20.0),
            area_px=80.0,
            perimeter_px=30.0,
            method="circle_seed",
            ok=True,
            merge_suspect=False,
        )
        rejected = SeededSliceResult(
            None,
            None,
            (20.0, 20.0),
            0.0,
            0.0,
            "circle_seed_merge_reject",
            False,
            merge_suspect=True,
            qc=None,
        )
        gap = SeededSliceResult(
            None, None, (20.0, 20.0), 0.0, 0.0, "circle_seed_gap", False, merge_suspect=False
        )
        return [ok, rejected, gap]

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", fake_track)
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=ObjectSeed(x=20, y=20, frame_index=0, radius=10.0),
        profile="vesicle",
    )
    assert analysis.tracking is not None
    rec_rej = analysis.tracking.records[1]
    rec_gap = analysis.tracking.records[2]
    assert rec_rej.tracked is False
    assert rec_rej.merge_rejected is True
    assert rec_rej.loss_reason == "merge_rejected"
    assert rec_gap.tracked is False
    assert rec_gap.merge_rejected is False
    assert rec_gap.loss_reason == "gap"

    warnings = object_tracking_warnings(analysis.tracking)
    codes = {w["code"] for w in warnings}
    assert "merge_suspect_rejected" in codes
    merge_w = next(w for w in warnings if w["code"] == "merge_suspect_rejected")
    assert 1 in merge_w["frame_indices"]
    assert 2 not in merge_w["frame_indices"]
    # Ordinary gap still contributes to tracking-loss aggregate.
    assert "tracking_lost_some_frames" in codes or "tracking_lost_many_frames" in codes
    # Wording is suspicion/safety, not confirmed biology.
    assert "suspected" in merge_w["message"].lower() or "safety" in merge_w["message"].lower()

    payload = tracking_diagnostics_payload(analysis.tracking)
    assert payload is not None
    assert payload[1]["merge_rejected"] is True
    assert payload[1]["loss_reason"] == "merge_rejected"
    assert payload[2]["merge_rejected"] is False
    # Backwards-compatible keys still present.
    assert "tracked" in payload[0]
    assert "likely_neighbor_merge" in payload[0]
    assert "touches_roi_boundary" in payload[0]


def test_blank_gap_is_tracking_loss_not_merge_rejected():
    """Ordinary untracked gap must not raise merge_suspect_rejected."""
    from morphostack.core.pipeline import FrameTrackingRecord, TrackingDiagnostics

    diagnostics = TrackingDiagnostics(
        records=(
            FrameTrackingRecord(
                frame_index=0,
                tracked=True,
                centroid_x=10.0,
                centroid_y=10.0,
                area_px=100,
            ),
            FrameTrackingRecord(
                frame_index=1,
                tracked=False,
                loss_reason="gap",
                merge_rejected=False,
                method="circle_seed_gap",
            ),
            FrameTrackingRecord(
                frame_index=2,
                tracked=False,
                loss_reason="signal_loss",
                merge_rejected=False,
                method="circle_seed_fail",
            ),
        ),
        seed_frame_area_px=100,
    )
    warnings = object_tracking_warnings(diagnostics)
    codes = {w["code"] for w in warnings}
    assert "tracking_lost_some_frames" in codes or "tracking_lost_many_frames" in codes
    assert "merge_suspect_rejected" not in codes
    assert "likely_neighbor_merge" not in codes


def test_seed_disk_clip_warning_is_distinct_from_roi_boundary():
    """Seed-disk clipping is a separate diagnostic from ROI/FOV edge contact."""
    from morphostack.core.pipeline import FrameTrackingRecord, TrackingDiagnostics

    diagnostics = TrackingDiagnostics(
        records=(
            FrameTrackingRecord(
                frame_index=0,
                tracked=True,
                centroid_x=20.0,
                centroid_y=20.0,
                area_px=100,
                touches_roi_boundary=False,
                touches_seed_disk=True,
            ),
            FrameTrackingRecord(
                frame_index=1,
                tracked=True,
                centroid_x=2.0,
                centroid_y=2.0,
                area_px=100,
                touches_roi_boundary=True,
                touches_seed_disk=False,
            ),
        ),
        seed_frame_area_px=100,
    )
    warnings = object_tracking_warnings(diagnostics)
    by_code = {w["code"]: w for w in warnings}
    assert "seed_disk_clip" in by_code
    assert "roi_boundary_touch" in by_code
    assert by_code["seed_disk_clip"]["frame_indices"] == [0]
    assert by_code["roi_boundary_touch"]["frame_indices"] == [1]
    assert "search disk" in by_code["seed_disk_clip"]["message"].lower() or "seed" in by_code[
        "seed_disk_clip"
    ]["message"].lower()


def test_tracking_payload_backwards_compatible_keys():
    """Payload always includes legacy fields even when new reason fields are set."""
    from morphostack.core.pipeline import FrameTrackingRecord, TrackingDiagnostics, tracking_diagnostics_payload

    diagnostics = TrackingDiagnostics(
        records=(
            FrameTrackingRecord(
                frame_index=3,
                tracked=False,
                loss_reason="merge_rejected",
                merge_rejected=True,
                merge_suspect=True,
                method="circle_seed_merge_reject",
            ),
        ),
        seed_frame_area_px=0,
    )
    payload = tracking_diagnostics_payload(diagnostics)
    assert payload is not None
    row = payload[0]
    for key in (
        "frame_index",
        "tracked",
        "centroid_x",
        "centroid_y",
        "area_px",
        "touches_roi_boundary",
        "likely_neighbor_merge",
        "loss_reason",
        "merge_suspect",
        "merge_rejected",
        "touches_seed_disk",
        "method",
    ):
        assert key in row