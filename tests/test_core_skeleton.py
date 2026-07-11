from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import analyze_stack
from morphostack.core.preview import render_segmentation_preview_png
from morphostack.core.skeleton import (
    calculate_vs_perimeter,
    generate_skeleton,
    measure_skeleton,
    prune_skeleton,
)
from morphostack.core.stack_cache import StackCache, cached_load_image_stack


def _ring_mask(size: int = 48, outer: int = 18, inner: int = 12) -> np.ndarray:
    """Filled annulus (ring) useful for closed-loop skeletonization."""
    yy, xx = np.ogrid[:size, :size]
    cy = cx = size // 2
    r2 = (yy - cy) ** 2 + (xx - cx) ** 2
    return (r2 <= outer**2) & (r2 >= inner**2)


def test_generate_and_prune_skeleton_on_ring():
    pytest.importorskip("skimage")
    pytest.importorskip("networkx")

    mask = _ring_mask()
    skel = generate_skeleton(mask)
    assert skel.dtype == bool
    assert np.any(skel)

    pruned = prune_skeleton(skel, prune_threshold_pix=15)
    assert pruned.dtype == bool
    assert pruned.shape == mask.shape
    # Pruning should not crash and should leave some skeleton for a clean ring.
    assert np.any(pruned)

    p_phys, p_naive = calculate_vs_perimeter(pruned, voxel_size_um=0.5)
    assert p_phys > 0
    assert p_naive > 0
    # Physical scale should track voxel size.
    p_px, _ = calculate_vs_perimeter(pruned, voxel_size_um=1.0)
    assert abs(p_phys - p_px * 0.5) < 1e-6


def test_measure_skeleton_empty_mask():
    pytest.importorskip("skimage")
    pytest.importorskip("networkx")

    empty = np.zeros((16, 16), dtype=bool)
    pruned, metrics = measure_skeleton(empty)
    assert not np.any(pruned)
    assert metrics.ok is False
    assert metrics.perimeter_px == 0.0


def test_analyze_stack_enable_skeleton_adds_fields():
    pytest.importorskip("skimage")
    pytest.importorskip("networkx")

    # Use a ring so VS perimeter succeeds on the selected component.
    ring = _ring_mask(size=40, outer=14, inner=9).astype(np.uint8) * 200
    stack = np.stack([ring, ring], axis=0)

    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        prefer_opencv=False,
        enable_skeleton=True,
        skeleton_prune_pix=15.0,
    )

    assert len(analysis.valid_frames) == 2
    for frame in analysis.frames:
        assert frame.skel_perimeter_px is not None
        assert frame.skel_perimeter_um is not None
        # Ring skeletons should yield a positive VS perimeter.
        assert frame.skel_ok is True
        assert frame.skel_perimeter_px > 0
        assert frame.skel_perimeter_um == pytest.approx(frame.skel_perimeter_px * 0.5)


def test_analyze_stack_skeleton_default_off():
    stack = np.zeros((1, 16, 16), dtype=np.uint8)
    stack[0, 4:12, 4:12] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )
    assert analysis.frames[0].skel_ok is False
    assert analysis.frames[0].skel_perimeter_px is None


def test_preview_enable_skeleton_returns_png():
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    pytest.importorskip("networkx")

    ring = _ring_mask(size=32, outer=12, inner=7).astype(np.uint8) * 200
    stack = ring[np.newaxis, ...]

    preview = render_segmentation_preview_png(
        stack,
        frame_index=0,
        threshold=100,
        prefer_opencv=False,
        enable_skeleton=True,
        skeleton_prune_pix=10.0,
        voxel_x_um=1.0,
    )
    assert preview.png_bytes.startswith(b"\x89PNG")
    assert preview.skel_ok is True
    assert preview.skel_perimeter_px is not None and preview.skel_perimeter_px > 0


def test_stack_cache_reuses_loaded_stack(tmp_path, monkeypatch):
    tifffile = pytest.importorskip("tifffile")
    path = tmp_path / "cache_stack.tif"
    data = np.zeros((2, 8, 8), dtype=np.uint8)
    data[:, 2:5, 2:5] = 180
    tifffile.imwrite(path, data, photometric="minisblack")

    cache = StackCache(max_entries=2)
    calls = {"n": 0}
    import morphostack.core.stack_cache as stack_cache_mod
    import morphostack.core.io as io_mod

    real_load = io_mod.load_image_stack

    def counting_load(path_arg, *, voxel_override=None):
        calls["n"] += 1
        return real_load(path_arg, voxel_override=voxel_override)

    monkeypatch.setattr(stack_cache_mod, "load_image_stack", counting_load)

    s1 = cached_load_image_stack(path, cache=cache)
    s2 = cached_load_image_stack(path, cache=cache)
    assert calls["n"] == 1
    assert s1 is s2
    assert s1.grayscale.shape == (2, 8, 8)

    # Different voxel override is a separate cache entry.
    from morphostack.core.models import VoxelSize

    s3 = cached_load_image_stack(path, voxel_override=VoxelSize(0.2, 0.2, 0.5), cache=cache)
    assert calls["n"] == 2
    assert s3.voxel_source == "override"
