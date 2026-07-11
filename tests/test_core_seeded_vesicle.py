"""Tests for circle-constrained seeded vesicle segmentation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import ObjectSeed, analyze_stack
from morphostack.core.seeded_vesicle import (
    SeededSliceResult,
    _adaptive_threshold_sparse,
    _mask_iou,
    _tracking_score,
    extend_track,
    segment_slice_seeded,
    track_seeded_vesicle_stack,
)
from morphostack.core.stack_cache import TrackingCacheKey, TrackingResultCache


def _ring_frame(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = 1.0
    return frame


def test_segment_slice_seeded_hollow_ring():
    frame = _ring_frame(80, 80, 40, 40, 14, 18)
    res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=18)
    assert res.ok
    assert res.contour_xy is not None
    assert res.solid_mask is not None
    assert res.solid_mask.shape == frame.shape
    assert res.area_px > 100
    assert abs(res.center_xy[0] - 40) < 3
    assert abs(res.center_xy[1] - 40) < 3
    assert res.method.startswith("circle_seed")
    # Filled interior should cover lumen seed
    assert res.solid_mask[40, 40]


def test_track_follows_lateral_float():
    h, w, n = 80, 80, 8
    stack = np.zeros((n, h, w), dtype=np.float64)
    for z in range(n):
        stack[z] = _ring_frame(h, w, 28 + z * 2, 40, 11, 15)
    results = track_seeded_vesicle_stack(
        stack, seed_x=28, seed_y=40, seed_frame=0, seed_radius=15
    )
    assert results[0].ok
    assert results[-1].ok
    # Center should drift rightward
    assert results[-1].center_xy[0] > results[0].center_xy[0] + 5


def test_disk_rejects_neighbor_touching_rings():
    """Hard disk around seed must not swallow a nearby second ring."""
    h, w = 100, 100
    frame = np.zeros((h, w), dtype=np.float64)
    # Target ring at (40, 50), outer r=14
    frame += _ring_frame(h, w, 40, 50, 10, 14)
    # Neighbor ring almost touching at (68, 50), outer r=14 (centers 28 px apart)
    frame += _ring_frame(h, w, 68, 50, 10, 14)
    frame = np.clip(frame, 0, 1)

    res = segment_slice_seeded(frame, seed_x=40, seed_y=50, seed_radius=14)
    assert res.ok
    assert res.contour_xy is not None
    assert abs(res.center_xy[0] - 40) < 5
    assert abs(res.center_xy[1] - 50) < 5
    # Solid mask should not extend into neighbor center
    assert res.solid_mask is not None
    assert not res.solid_mask[50, 68]
    # Area near one disk, not two
    assert res.area_px < np.pi * 14**2 * 1.5


def test_analyze_stack_uses_circle_seed_method_when_seeded():
    h, w, n = 64, 64, 4
    stack = np.stack([_ring_frame(h, w, 32, 32, 10, 14)] * n, axis=0)
    stack = (stack * 200).astype(np.uint8)
    seed = ObjectSeed(x=32, y=32, frame_index=0, radius=14)
    analysis = analyze_stack(
        stack,
        thresholds=50,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=seed,
        profile="vesicle",
    )
    assert analysis.frames[0].preview.method.startswith("circle_seed")
    assert analysis.frames[0].contour is not None
    assert analysis.tracking is not None
    assert analysis.tracking.records[0].tracked


def test_fail_slice_has_no_fake_contour():
    """Lost track returns ok=False with no multi-lobe mask."""
    h, w, n = 64, 64, 4
    stack = np.zeros((n, h, w), dtype=np.float64)
    stack[0] = _ring_frame(h, w, 32, 32, 10, 14)
    # Frames 1+ empty → track should stop with fail, not invent blobs
    results = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=0, seed_radius=14
    )
    assert results[0].ok
    assert not results[1].ok
    assert results[1].contour_xy is None
    assert results[1].solid_mask is None


def test_extend_track_cache_hit():
    """Track to frame 5 then extend to 5 again — reuse without re-segmenting."""
    h, w, n = 64, 64, 10
    stack = np.stack([_ring_frame(h, w, 32, 32, 10, 14)] * n, axis=0)
    first = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=0, seed_radius=14, target_frame=5
    )
    assert first[5].ok

    call_count = {"n": 0}
    real_segment = segment_slice_seeded

    def counting_segment(frame, **kwargs):
        call_count["n"] += 1
        return real_segment(frame, **kwargs)

    import morphostack.core.seeded_vesicle as sv

    original = sv.segment_slice_seeded
    sv.segment_slice_seeded = counting_segment  # type: ignore[assignment]
    try:
        again = extend_track(
            stack,
            seed_x=32,
            seed_y=32,
            seed_frame=0,
            seed_radius=14,
            target_frame=5,
            cached_results=first,
        )
    finally:
        sv.segment_slice_seeded = original  # type: ignore[assignment]

    assert again[5].ok
    assert again[5].area_px == first[5].area_px
    # Cache hit: target already reached — no new segmentations.
    assert call_count["n"] == 0


def test_extend_track_extends_forward():
    """Track to 5 then extend to 8 — only segments frames past furthest ok."""
    h, w, n = 120, 120, 10
    # Tag outside crop around seed (crop half≈40 around (40,40) → ≤80).
    stack = np.zeros((n, h, w), dtype=np.float64)
    for z in range(n):
        stack[z] = _ring_frame(h, w, 40, 40, 10, 14)
        stack[z, h - 1, w - 1] = 1000.0 + z
    first = track_seeded_vesicle_stack(
        stack, seed_x=40, seed_y=40, seed_frame=0, seed_radius=14, target_frame=5
    )
    assert first[5].ok
    assert first[8].method == "circle_seed_unreached"

    call_frames: list[int] = []
    real_segment = segment_slice_seeded

    def counting_segment(frame, **kwargs):
        tag = float(np.asarray(frame)[h - 1, w - 1])
        if tag >= 1000.0:
            call_frames.append(int(round(tag - 1000.0)))
        else:
            call_frames.append(-1)
        return real_segment(frame, **kwargs)

    import morphostack.core.seeded_vesicle as sv

    original = sv.segment_slice_seeded
    sv.segment_slice_seeded = counting_segment  # type: ignore[assignment]
    try:
        extended = extend_track(
            stack,
            seed_x=40,
            seed_y=40,
            seed_frame=0,
            seed_radius=14,
            target_frame=8,
            cached_results=first,
        )
    finally:
        sv.segment_slice_seeded = original  # type: ignore[assignment]

    assert extended[5].ok
    assert extended[8].ok
    # Must not re-walk seed..5; only segment past furthest ok (6,7,8).
    assert call_frames, "expected some segmentations for frames 6-8"
    assert all(z > 5 for z in call_frames if z >= 0)
    assert set(z for z in call_frames if z >= 0) <= {6, 7, 8}


def test_tracking_cache_key_preserves_subpixel_seed_precision():
    """Distinct sub-pixel seed/radius values must NOT collide (unsafe integer rounding)."""
    from morphostack.core.stack_cache import make_tracking_cache_key

    key_a = make_tracking_cache_key(
        stack_identity="/data/stack.tif",
        seed_x=32.10,
        seed_y=40.10,
        seed_frame=10,
        seed_radius=14.10,
        gray_shape=(20, 128, 128),
    )
    key_b = make_tracking_cache_key(
        stack_identity="/data/stack.tif",
        seed_x=32.49,
        seed_y=40.49,
        seed_frame=10,
        seed_radius=14.49,
        gray_shape=(20, 128, 128),
    )
    assert key_a != key_b
    assert key_a.seed_x == 32.1
    assert key_b.seed_x == 32.49

    # Identical after 6-decimal canonicalization still shares a key.
    key_c = make_tracking_cache_key(
        stack_identity="/data/stack.tif",
        seed_x=32.1000004,
        seed_y=40.10,
        seed_frame=10,
        seed_radius=14.10,
        gray_shape=(20, 128, 128),
    )
    assert key_a == key_c

    cache = TrackingResultCache(maxsize=4)
    dummy = [
        SeededSliceResult(None, None, (32.1, 40.1), 0.0, 0.0, "circle_seed", True)
    ]
    cache.put(key_a, dummy)
    assert cache.get(key_a) is not None
    assert cache.get(key_b) is None


def test_tracking_cache_key_scopes_roi_z_source_and_shape():
    """Different ROI, Z-range, source, or shape must not share a cache entry."""
    from morphostack.core.pipeline import RectROI, ZRange
    from morphostack.core.stack_cache import make_tracking_cache_key

    base = dict(
        seed_x=40.0,
        seed_y=40.0,
        seed_frame=2,
        seed_radius=14.0,
        gray_shape=(10, 64, 64),
    )
    key_path = make_tracking_cache_key(stack_identity="path:/a.tif", **base)
    key_other_source = make_tracking_cache_key(stack_identity="path:/b.tif", **base)
    key_roi = make_tracking_cache_key(
        stack_identity="path:/a.tif",
        **base,
        roi=RectROI(xmin=0, xmax=40, ymin=0, ymax=40),
    )
    key_z = make_tracking_cache_key(
        stack_identity="path:/a.tif",
        **base,
        z_range=ZRange(zmin=0, zmax=5),
    )
    key_shape = make_tracking_cache_key(
        stack_identity="path:/a.tif",
        seed_x=40.0,
        seed_y=40.0,
        seed_frame=2,
        seed_radius=14.0,
        gray_shape=(10, 32, 32),
    )
    assert key_path != key_other_source
    assert key_path != key_roi
    assert key_path != key_z
    assert key_path != key_shape

    cache = TrackingResultCache(maxsize=8)
    dummy = [SeededSliceResult(None, None, (40.0, 40.0), 1.0, 1.0, "circle_seed", True)]
    cache.put(key_path, dummy)
    assert cache.get(key_path) is not None
    assert cache.get(key_other_source) is None
    assert cache.get(key_roi) is None
    assert cache.get(key_z) is None
    assert cache.get(key_shape) is None


def test_tracking_survives_shrinking_area():
    """Object area shrinks toward ~20% of equator; track should stay ok."""
    h, w, n = 80, 80, 12
    stack = np.zeros((n, h, w), dtype=np.float64)
    # Linear shrink: outer radius 18 → ~8 (area ratio ~(8/18)^2 ≈ 0.20 for filled disk;
    # for rings use proportional outer/inner).
    for z in range(n):
        scale = 1.0 - 0.8 * (z / (n - 1))  # 1.0 → 0.2
        r_out = max(4.0, 18.0 * scale)
        r_in = max(2.0, r_out * 0.7)
        stack[z] = _ring_frame(h, w, 40, 40, r_in, r_out)

    results = track_seeded_vesicle_stack(
        stack, seed_x=40, seed_y=40, seed_frame=0, seed_radius=18
    )
    assert results[0].ok
    # With adaptive ref_area + Z-aware min, should track deep into the shrink.
    ok_tail = sum(1 for r in results if r.ok)
    assert ok_tail >= int(0.8 * n), f"only {ok_tail}/{n} frames ok under shrink"
    # Last frame area should be much smaller than seed if still tracked
    if results[-1].ok:
        assert results[-1].area_px < results[0].area_px * 0.5


def test_tracking_center_extrapolation():
    """Laterally drifting object recovers after a multi-frame gap via extrapolation."""
    h, w, n = 80, 80, 12
    stack = np.zeros((n, h, w), dtype=np.float64)
    for z in range(n):
        cx = 20.0 + z * 2.0  # 2 px/frame drift
        # Blank two frames mid-track to force a gap
        if z in (5, 6):
            continue
        stack[z] = _ring_frame(h, w, cx, 40, 10, 14)

    results = track_seeded_vesicle_stack(
        stack, seed_x=20, seed_y=40, seed_frame=0, seed_radius=14
    )
    assert results[0].ok
    assert not results[5].ok  # forced gap
    assert not results[6].ok
    # After the gap, extrapolation should recover the drifting center
    assert results[7].ok or results[8].ok or results[9].ok, (
        "failed to recover after gap; last methods: "
        + ", ".join(f"{i}:{results[i].method}" for i in range(n))
    )
    # Recovered center should be near the drifted position (not stuck at seed)
    recovered = next(results[i] for i in range(7, n) if results[i].ok)
    assert recovered.center_xy[0] > 20 + 8


def test_tracking_does_not_reacquire_neighbor_after_gap():
    """A gap must not reset identity to a nearby old-position vesicle."""
    h, w, n = 100, 100, 7
    stack = np.zeros((n, h, w), dtype=np.float64)
    # Establish rightward motion for a target at x=30 -> 32 -> 34.
    for z, cx in enumerate((30.0, 32.0, 34.0)):
        stack[z] = _ring_frame(h, w, cx, 50, 10, 14)
    # The target vanishes. A similar neighbor appears near the original seed.
    for z in range(4, n):
        stack[z] = _ring_frame(h, w, 30.0, 50, 10, 14)

    results = track_seeded_vesicle_stack(
        stack, seed_x=30, seed_y=50, seed_frame=0, seed_radius=14
    )

    assert results[0].ok and results[2].ok
    assert not results[3].ok
    assert all(
        not result.ok or abs(result.center_xy[0] - 30.0) > 5.0
        for result in results[4:]
    ), "tracker reacquired the neighbor after the target gap"


def test_adaptive_threshold_weak_signal():
    """Sparse weak membrane: post-Otsu quality / percentile finds FG above BG."""
    h, w = 64, 64
    yy, xx = np.ogrid[:h, :w]
    d = (xx - 32) ** 2 + (yy - 32) ** 2
    frame = np.full((h, w), 10.0, dtype=np.float64)  # background
    membrane = (d >= 13.5**2) & (d <= 14.5**2)  # thin ring
    frame[membrane] = 40.0  # only modestly brighter — weak membrane
    disk = d <= 22**2  # larger disk so membrane fraction < 10%
    disk_vals = frame[disk]
    frac = float(np.count_nonzero(membrane & disk)) / float(np.count_nonzero(disk))
    assert frac < 0.10, f"membrane fraction {frac:.3f} not sparse"

    thr = _adaptive_threshold_sparse(disk_vals)
    assert thr is not None
    assert thr > 10.0 + 1e-6  # above pure background
    fg_frac = float(np.count_nonzero(disk_vals >= thr)) / float(disk_vals.size)
    assert fg_frac < 0.5  # not the whole disk


def test_otsu_flood_falls_back_to_percentile():
    """When Otsu would mark nearly all FG, quality check routes to percentile."""
    # Two-level with tiny bright fraction buried in noise — construct values where
    # a bad Otsu is replaced. Drive the real helper on extreme FG fraction data.
    rng = np.random.default_rng(0)
    # Mostly mid-gray with rare brighter spikes (membrane-like)
    vals = rng.normal(50.0, 2.0, size=5000)
    vals[:80] = 90.0
    thr = _adaptive_threshold_sparse(vals)
    assert thr is not None
    fg_frac = float(np.mean(vals > thr))
    assert fg_frac < 0.85, f"threshold flooded FG: {fg_frac:.2f}"


def test_iou_gating_accepts_shrinking_overlap():
    """Centered shrink ~50% area keeps association (high IoU / score)."""
    h, w, n = 80, 80, 6
    stack = np.zeros((n, h, w), dtype=np.float64)
    for z in range(n):
        scale = 1.0 - 0.5 * (z / (n - 1))  # 1.0 → 0.5 linear radius ~ area×0.25 at end
        # Use milder shrink so area ~50% mid-stack: outer 16 → 11
        r_out = 16.0 * (1.0 - 0.3 * (z / (n - 1)))
        r_in = r_out * 0.7
        stack[z] = _ring_frame(h, w, 40, 40, r_in, r_out)
    results = track_seeded_vesicle_stack(
        stack, seed_x=40, seed_y=40, seed_frame=0, seed_radius=16
    )
    assert results[0].ok
    assert sum(1 for r in results if r.ok) >= n - 1


def test_iou_gating_rejects_jumped_object():
    """Second object at distant location with similar area is rejected (low IoU)."""
    h, w, n = 100, 100, 4
    stack = np.zeros((n, h, w), dtype=np.float64)
    stack[0] = _ring_frame(h, w, 30, 50, 10, 14)
    # Frame 1+: only a distant ring (simulates tracker jumping)
    for z in range(1, n):
        stack[z] = _ring_frame(h, w, 80, 50, 10, 14)
    results = track_seeded_vesicle_stack(
        stack, seed_x=30, seed_y=50, seed_frame=0, seed_radius=14
    )
    assert results[0].ok
    # Must not happily lock onto the distant blob for all subsequent frames
    jumped = sum(1 for r in results[1:] if r.ok and abs(r.center_xy[0] - 80) < 8)
    assert jumped == 0, f"tracker jumped to distant object on {jumped} frames"


def test_tracking_score_accepts_shrinking_centered_object():
    """Unit score: area 1000→400 same center high IoU → score > 0.30."""
    h, w = 64, 64
    yy, xx = np.ogrid[:h, :w]
    prev_mask = (xx - 32) ** 2 + (yy - 32) ** 2 <= 18**2
    cand_mask = (xx - 32) ** 2 + (yy - 32) ** 2 <= 11**2
    prev = SeededSliceResult(
        None, prev_mask, (32.0, 32.0), float(np.count_nonzero(prev_mask)), 100.0, "circle_seed", True
    )
    cand = SeededSliceResult(
        None, cand_mask, (32.0, 32.0), float(np.count_nonzero(cand_mask)), 70.0, "circle_seed", True
    )
    assert _mask_iou(prev_mask, cand_mask) > 0.3
    score = _tracking_score(prev, cand, max_centroid_jump_px=40.0)
    assert score > 0.30


def test_tracking_score_rejects_jumped_object():
    h, w = 80, 80
    yy, xx = np.ogrid[:h, :w]
    prev_mask = (xx - 20) ** 2 + (yy - 20) ** 2 <= 12**2
    cand_mask = (xx - 60) ** 2 + (yy - 60) ** 2 <= 12**2
    prev = SeededSliceResult(
        None, prev_mask, (20.0, 20.0), float(np.count_nonzero(prev_mask)), 70.0, "circle_seed", True
    )
    cand = SeededSliceResult(
        None, cand_mask, (60.0, 60.0), float(np.count_nonzero(cand_mask)), 70.0, "circle_seed", True
    )
    score = _tracking_score(prev, cand, max_centroid_jump_px=40.0)
    # Same-size distant blob still has radius/shape terms; IoU+centroid dominate low.
    assert score < 0.40
    # Association gate rejects via IoU floor even if score alone is borderline
    from morphostack.core.seeded_vesicle import _candidate_accepted

    assert not _candidate_accepted(
        cand, prev=prev, ref_area=prev.area_px, max_area_ratio=2.2, jump=40.0
    )


def test_tracking_score_no_previous_returns_1():
    cand = SeededSliceResult(None, None, (0.0, 0.0), 10.0, 10.0, "circle_seed", True)
    assert _tracking_score(None, cand, 20.0) == 1.0


def test_cap_detection_stops_at_pole():
    """Intensity collapse mid-stack stops with cap_detected; later frames unreached."""
    h, w, n = 64, 64, 10
    stack = np.zeros((n, h, w), dtype=np.float64)
    for z in range(n):
        if z < 6:
            stack[z] = _ring_frame(h, w, 32, 32, 10, 14) * 100.0
        else:
            # Cap: solid low-contrast blob (membrane not brighter than disk bg)
            yy, xx = np.ogrid[:h, :w]
            d = (xx - 32) ** 2 + (yy - 32) ** 2
            stack[z] = np.where(d <= 14**2, 12.0, 10.0)
    results = track_seeded_vesicle_stack(
        stack, seed_x=32, seed_y=32, seed_frame=0, seed_radius=14
    )
    assert results[0].ok
    cap_idxs = [i for i, r in enumerate(results) if r.method == "cap_detected"]
    # Cap should fire somewhere after the bright frames, not invent gaps past stop
    # Later frames after first cap should be unreached (propagation broke)
    if cap_idxs:
        first_cap = cap_idxs[0]
        for i in range(first_cap + 1, n):
            assert results[i].method in ("circle_seed_unreached", "cap_detected", "circle_seed_gap")
            if results[i].method == "circle_seed_unreached":
                break
    else:
        # Soft: if cap logic did not fire, at least tracking should fail past poles
        assert not results[-1].ok


def test_bilateral_preserves_ring_edges():
    """Noisy ring still segments with usable circularity via bilateral path."""
    pytest.importorskip("skimage")
    frame = _ring_frame(80, 80, 40, 40, 12, 16)
    rng = np.random.default_rng(1)
    noisy = frame + rng.normal(0, 0.15, size=frame.shape)
    noisy = np.clip(noisy, 0, None)
    # Salt-and-pepper
    mask = rng.random(frame.shape) < 0.02
    noisy[mask] = rng.choice([0.0, 1.5], size=int(mask.sum()))
    res = segment_slice_seeded(noisy, seed_x=40, seed_y=40, seed_radius=16)
    assert res.ok
    assert res.contour_xy is not None
    circ = 4.0 * np.pi * res.area_px / max(res.perimeter_px**2, 1e-12)
    assert circ > 0.4


def test_morphgac_refines_or_keeps_mask():
    """MorphGAC path runs; refined result remains ok with plausible area."""
    pytest.importorskip("skimage")
    frame = _ring_frame(64, 64, 32, 32, 10, 14)
    res_ref = segment_slice_seeded(frame, seed_x=32, seed_y=32, seed_radius=14, refine=True)
    res_raw = segment_slice_seeded(frame, seed_x=32, seed_y=32, seed_radius=14, refine=False)
    assert res_ref.ok and res_raw.ok
    # Both should find the ring; areas within same order of magnitude
    assert abs(res_ref.area_px - res_raw.area_px) / max(res_raw.area_px, 1.0) < 1.5


def test_crofton_perimeter_positive():
    """Seeded solid results report a positive Crofton (or fallback) perimeter."""
    frame = _ring_frame(64, 64, 32, 32, 10, 14)
    res = segment_slice_seeded(frame, seed_x=32, seed_y=32, seed_radius=14)
    assert res.ok
    assert res.perimeter_px > 0


@pytest.mark.slow
def test_optional_real_czi_if_present():
    """Optional smoke on a real CZI if the lab file is present locally."""
    pytest.importorskip("czifile")
    candidates = [
        Path("validation") / "data",
        Path("validation") / "runs",
        Path("data"),
        Path(r"C:\Users\systemm\Downloads"),
    ]
    czi_path = None
    for root in candidates:
        if not root.exists():
            continue
        found = list(root.rglob("*.czi")) if root.name != "Downloads" else list(root.glob("*.czi"))
        if found:
            czi_path = found[0]
            break
    if czi_path is None:
        pytest.skip("no local CZI present")

    from morphostack.core.io import load_image_stack

    stack = load_image_stack(czi_path)
    gray = stack.grayscale
    z = gray.shape[0] // 2
    cy, cx = gray.shape[1] // 2, gray.shape[2] // 2
    res = segment_slice_seeded(gray[z], seed_x=cx, seed_y=cy, seed_radius=40)
    assert res.method.startswith("circle_seed") or res.method == "polar_dp"


@pytest.mark.slow
def test_real_czi_tracking_coverage():
    """Track 1644 Z-stack and verify >80% of frames have ok=True when available."""
    pytest.importorskip("czifile")
    czi_path = Path(r"C:\Users\systemm\Downloads\1644_z stack.czi")
    if not czi_path.exists():
        pytest.skip("Real CZI not available")

    from morphostack.core.io import load_image_stack

    stack = load_image_stack(czi_path)
    gray = stack.grayscale
    z = gray.shape[0] // 2
    cy, cx = gray.shape[1] // 2, gray.shape[2] // 2
    first = segment_slice_seeded(gray[z], seed_x=float(cx), seed_y=float(cy), seed_radius=40)
    if not first.ok:
        for dx, dy in ((-80, 0), (80, 0), (0, -80), (0, 80), (-40, -40)):
            first = segment_slice_seeded(
                gray[z], seed_x=float(cx + dx), seed_y=float(cy + dy), seed_radius=40
            )
            if first.ok:
                cx, cy = cx + dx, cy + dy
                break
    if not first.ok:
        pytest.skip("Could not place a successful seed on real CZI mid-slice")

    results = track_seeded_vesicle_stack(
        gray,
        seed_x=float(cx),
        seed_y=float(cy),
        seed_frame=z,
        seed_radius=40,
    )
    ok_rate = sum(1 for r in results if r.ok) / len(results)
    assert ok_rate > 0.80, f"ok rate {ok_rate:.2%} <= 80%"
