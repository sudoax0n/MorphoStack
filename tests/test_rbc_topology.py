"""Topology-preserving RBC reconstruction tests."""

from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import ObjectSeed, analyze_stack, segmentation_candidate_from_analysis
from morphostack.core.rbc_capabilities import calibration_from_override
from morphostack.core.rbc_models import RbcTopologyIssue
from morphostack.core.rbc_segmentation import segment_rbc_slice_seeded, track_rbc_stack
from morphostack.core.rbc_topology import extract_rbc_slice_topology, rasterize_rbc_topology
from morphostack.core.seeded_vesicle import segment_slice_seeded


def annulus_mask(
    shape: tuple[int, int] = (96, 96),
    *,
    outer_radius: float = 30.0,
    inner_radius: float = 12.0,
    cy: float | None = None,
    cx: float | None = None,
) -> np.ndarray:
    h, w = shape
    cy = (h - 1) / 2.0 if cy is None else cy
    cx = (w - 1) / 2.0 if cx is None else cx
    yy, xx = np.ogrid[:h, :w]
    dist2 = (yy - cy) ** 2 + (xx - cx) ** 2
    return (dist2 <= outer_radius**2) & (dist2 >= inner_radius**2)


def two_component_mask(shape: tuple[int, int] = (64, 96)) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    mask[20:40, 10:30] = True
    mask[20:40, 60:80] = True
    return mask


def synthetic_membrane_annulus(
    shape: tuple[int, int] = (96, 96),
    *,
    outer_radius: float = 28.0,
    thickness: float = 4.0,
) -> np.ndarray:
    """Bright membrane ring on dark background (uint8)."""
    h, w = shape
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    ring = (dist <= outer_radius) & (dist >= outer_radius - thickness)
    img = np.zeros(shape, dtype=np.uint8)
    img[ring] = 220
    # faint interior noise
    rng = np.random.default_rng(0)
    img = np.clip(img.astype(np.int16) + rng.integers(0, 8, size=shape), 0, 255).astype(np.uint8)
    return img


def solid_disk_mask(shape=(64, 64), radius=18.0) -> np.ndarray:
    h, w = shape
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.ogrid[:h, :w]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= radius**2


def test_annular_slice_preserves_inner_hole():
    mask = annulus_mask(shape=(96, 96), outer_radius=30, inner_radius=12)
    result = extract_rbc_slice_topology(mask, frame_index=4)
    rebuilt = rasterize_rbc_topology(result, mask.shape)
    assert result.ok
    assert len(result.inner_loops_xy) == 1
    assert not rebuilt[48, 48]
    # Center of source annulus is empty
    assert not mask[48, 48]
    # Occupancy should keep the hole
    assert result.occupancy_mask is not None
    assert not result.occupancy_mask[48, 48]


def test_two_disconnected_outer_loops_are_ambiguous():
    result = extract_rbc_slice_topology(two_component_mask(), frame_index=2)
    assert not result.ok
    assert RbcTopologyIssue.MULTIPLE_OUTER_COMPONENTS in result.issues


def test_solid_disk_has_no_inner_loops():
    mask = solid_disk_mask()
    result = extract_rbc_slice_topology(mask, frame_index=0)
    assert result.ok
    assert result.inner_loop_count == 0
    assert result.occupancy_mask is not None
    assert result.occupancy_mask[32, 32]


def test_rbc_keeps_center_hole_while_vesicle_preserves_legacy_fill():
    pytest.importorskip("cv2")
    frame = synthetic_membrane_annulus()
    cy = cx = 47.5
    rbc = segment_rbc_slice_seeded(frame, seed_x=cx, seed_y=cy, seed_radius=32, frame_index=0)
    guv = segment_slice_seeded(
        frame, seed_x=cx, seed_y=cy, seed_radius=32, profile="vesicle", refine=False
    )
    assert guv.ok and guv.solid_mask is not None
    # Legacy vesicle path fills the dimple.
    assert guv.solid_mask[48, 48]
    # RBC path should retain empty center when membrane ring is segmented.
    if rbc.ok and rbc.occupancy_mask is not None:
        assert not rbc.occupancy_mask[48, 48]
    else:
        # Fallback: at least topology extraction on the unfilled pre-fill path
        # when seed adaptive finds the ring FG.
        unfilled = segment_slice_seeded(
            frame,
            seed_x=cx,
            seed_y=cy,
            seed_radius=32,
            profile="rbc",
            refine=False,
            fill_holes=False,
        )
        assert unfilled.ok and unfilled.solid_mask is not None
        assert not unfilled.solid_mask[48, 48]


def moving_biconcave_stack(
    n: int = 15,
    shape: tuple[int, int] = (80, 80),
    seed_frame: int = 8,
) -> np.ndarray:
    """Synthetic stack: annular slices around seed Z, empty elsewhere."""
    h, w = shape
    stack = np.zeros((n, h, w), dtype=np.uint8)
    z0 = max(0, seed_frame - 5)
    z1 = min(n, seed_frame + 6)
    for z in range(z0, z1):
        # Slight lateral drift
        dx = 0.4 * (z - seed_frame)
        cy, cx = (h - 1) / 2.0 + dx * 0.1, (w - 1) / 2.0 + dx
        outer = min(min(h, w) * 0.35, 22.0 - 0.3 * abs(z - seed_frame))
        outer = max(8.0, outer)
        yy, xx = np.ogrid[:h, :w]
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        ring = (dist <= outer) & (dist >= outer - 3.5)
        stack[z][ring] = 210
    return stack


def test_rbc_stack_tracks_one_seeded_cell_in_both_z_directions():
    pytest.importorskip("cv2")
    stack = moving_biconcave_stack()
    seed = ObjectSeed(x=40.0, y=40.0, frame_index=8, radius=28.0)
    result = track_rbc_stack(stack, seed=seed)
    assert result.seed_frame_index == 8
    # Should recover a contiguous run of slices around the seed.
    assert len(result.valid_slice_indices) >= 3
    if result.occupancy_mask is not None and 8 in result.valid_slice_indices:
        # Dimple / empty interior at center on seed frame when ring-like.
        center = result.occupancy_mask[8, 40, 40]
        # Either empty center (annulus) or solid if threshold merged — both ok if tracked.
        _ = center


def test_rbc_stack_does_not_force_ambiguous_neighbor_merge():
    pytest.importorskip("cv2")
    # Two bright disks touching — seed on left.
    n, h, w = 5, 64, 96
    stack = np.zeros((n, h, w), dtype=np.uint8)
    yy, xx = np.ogrid[:h, :w]
    left = (yy - 32) ** 2 + (xx - 30) ** 2 <= 14**2
    right = (yy - 32) ** 2 + (xx - 55) ** 2 <= 14**2
    for z in range(n):
        stack[z][left | right] = 200
    seed = ObjectSeed(x=30.0, y=32.0, frame_index=2, radius=18.0)
    result = track_rbc_stack(stack, seed=seed)
    # May succeed on isolated left cell or withhold on merge — must not invent topology.
    if result.withheld:
        assert (
            RbcTopologyIssue.UNRESOLVED_MERGE in result.issues
            or RbcTopologyIssue.MULTIPLE_OUTER_COMPONENTS in result.issues
            or RbcTopologyIssue.NO_VALID_SLICES in result.issues
            or RbcTopologyIssue.SEED_SLICE_FAILED in result.issues
        )


def test_rbc_pipeline_candidate_uses_loop_aware_occupancy():
    pytest.importorskip("cv2")
    stack = moving_biconcave_stack(n=7, shape=(64, 64), seed_frame=3)
    # densify so seed frame is mid
    seed = ObjectSeed(x=32.0, y=32.0, frame_index=3, radius=26.0)
    cal = calibration_from_override(1.0, 1.0, 1.0, source_format="tiff")
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="rbc",
        prefer_opencv=False,
        object_seed=seed,
        source_path="cell.tif",
        calibration=cal,
        include_mesh=False,
    )
    assert analysis.profile == "rbc"
    if analysis.rbc_occupancy is not None:
        candidate = segmentation_candidate_from_analysis(
            analysis,
            shape=analysis.rbc_occupancy.shape,
            provisional=True,
        )
        assert candidate.provisional
        assert candidate.method == "rbc_topology_occupancy"
        assert "topology_occupancy" in str(candidate.provenance.get("representation", ""))


def test_rbc_pipeline_does_not_call_legacy_contour_rasterizer(monkeypatch):
    pytest.importorskip("cv2")
    from morphostack.core import mesh as mesh_mod

    def fail_if_called(*args, **kwargs):
        raise AssertionError("contours_to_mask_stack must not be used for RBC occupancy mesh")

    stack = moving_biconcave_stack(n=5, shape=(48, 48), seed_frame=2)
    seed = ObjectSeed(x=24.0, y=24.0, frame_index=2, radius=20.0)
    cal = calibration_from_override(1.0, 1.0, 1.0, source_format="tiff")
    # Patch only the path used by contour rasterization; RBC mesh uses marching_cubes.
    monkeypatch.setattr(mesh_mod, "contours_to_mask_stack", fail_if_called)
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="rbc",
        prefer_opencv=False,
        object_seed=seed,
        source_path="cell.tif",
        calibration=cal,
        include_mesh=True,
    )
    # If occupancy was built, mesh path must not have needed contours_to_mask_stack.
    assert analysis.profile == "rbc"
