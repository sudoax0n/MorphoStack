"""Seeded analysis must report adaptive local thresholds, not the UI slider."""

from __future__ import annotations

import math

import numpy as np

from morphostack.core import VoxelSize, analyze_stack
from morphostack.core.export import analysis_manifest, analysis_run_warnings, analysis_rows
from morphostack.core.pipeline import ObjectSeed
from morphostack.core.seeded_vesicle import segment_slice_seeded


def _ring_stack(n: int = 3, h: int = 64, w: int = 64) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - 32) ** 2 + (yy - 32) ** 2
    ring = ((d >= 10**2) & (d <= 14**2)).astype(np.float64)
    return np.stack([ring * 200.0 for _ in range(n)], axis=0)


def test_segment_slice_records_effective_threshold():
    frame = _ring_stack(n=1)[0]
    res = segment_slice_seeded(frame, seed_x=32, seed_y=32, seed_radius=14, refine=False)
    assert res.ok
    assert res.effective_threshold is not None
    assert math.isfinite(res.effective_threshold)
    # Adaptive gate should sit between dark lumen and bright ring.
    assert 0.0 < res.effective_threshold < 200.0


def test_analyze_seeded_threshold_independent_of_ui_slider():
    stack = _ring_stack()
    seed = ObjectSeed(x=32, y=32, frame_index=0, radius=14.0)
    voxel = VoxelSize(1.0, 1.0, 1.0)

    a_low = analyze_stack(stack, thresholds=1.0, voxel_size=voxel, object_seed=seed, profile="vesicle")
    a_high = analyze_stack(stack, thresholds=10000.0, voxel_size=voxel, object_seed=seed, profile="vesicle")

    valid_low = [f for f in a_low.frames if f.contour is not None]
    valid_high = [f for f in a_high.frames if f.contour is not None]
    assert valid_low and valid_high

    # Contours/areas match despite wildly different UI thresholds (tiny MorphGAC noise ok).
    area_lo = float(valid_low[0].metrics.area_px2)
    area_hi = float(valid_high[0].metrics.area_px2)
    assert abs(area_lo - area_hi) / max(area_lo, area_hi, 1.0) < 0.02
    # Provenance stores the same effective adaptive gate, not the UI requests.
    assert valid_low[0].threshold is not None and math.isfinite(valid_low[0].threshold)
    assert valid_high[0].threshold is not None and math.isfinite(valid_high[0].threshold)
    assert abs(float(valid_low[0].threshold) - float(valid_high[0].threshold)) < 1e-9
    assert valid_low[0].requested_threshold == 1.0
    assert valid_high[0].requested_threshold == 10000.0
    assert valid_low[0].effective_threshold == valid_low[0].threshold
    assert valid_low[0].threshold_semantics == "seeded_adaptive_local"
    # High UI request must not appear as the reported legacy frame threshold.
    assert abs(float(valid_high[0].threshold) - 10000.0) > 1.0
    assert abs(float(valid_low[0].threshold) - 10000.0) > 1.0
    assert valid_low[0].preview.method.startswith("circle_seed")


def test_manifest_and_rows_expose_effective_and_requested():
    stack = _ring_stack()
    seed = ObjectSeed(x=32, y=32, frame_index=0, radius=14.0)
    analysis = analyze_stack(
        stack,
        thresholds=42.0,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=seed,
        profile="vesicle",
    )
    manifest = analysis_manifest(
        analysis,
        source_path="ring.tif",
        threshold=42.0,
        object_seed=seed,
    )
    assert manifest["requested_threshold"] == 42.0
    assert manifest["threshold_semantics"] == "seeded_adaptive_local"
    assert "threshold_field_notes" in manifest

    rows = analysis_rows(analysis)
    tracked_rows = [r for r in rows if r["has_contour"]]
    assert tracked_rows
    assert abs(float(tracked_rows[0]["threshold"]) - 42.0) > 1.0
    assert float(tracked_rows[0]["requested_threshold"]) == 42.0
    assert tracked_rows[0]["threshold_semantics"] == "seeded_adaptive_local"

    codes = {w["code"] for w in analysis_run_warnings(analysis)}
    assert "seeded_adaptive_threshold" in codes
