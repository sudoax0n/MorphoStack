"""VolumeSource + PlaneCache (packet 10) — display plane path, science unchanged."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from morphostack.core.io import load_image_stack, open_volume_source as io_open_volume_source
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import RectROI, ZRange
from morphostack.core.preview import extract_preview_frame, extract_preview_frame_from_volume
from morphostack.core.stack_cache import path_source_identity
from morphostack.core.volume_source import (
    ArrayVolumeSource,
    PlaneCache,
    StackRevision,
    TiffVolumeSource,
    VolumeSourceRegistry,
    default_plane_cache,
    format_support_matrix,
    open_volume_source,
    stack_revision_from_path,
    volume_source_from_array,
)


def _write_zyx_tiff(path: Path, arr: np.ndarray, *, z_um: float = 0.5) -> None:
    tifffile = pytest.importorskip("tifffile")
    tifffile.imwrite(
        path,
        arr,
        imagej=True,
        metadata={"axes": "ZYX", "spacing": float(z_um), "unit": "um"},
        resolution=(1.0 / 0.25, 1.0 / 0.25),  # 0.25 µm/px if interpreted as px/unit
    )


def _synthetic_stack(nz: int = 7, ny: int = 16, nx: int = 16) -> np.ndarray:
    zz, yy, xx = np.ogrid[:nz, :ny, :nx]
    # Unique per-plane content for parity checks.
    return (zz * 1000 + yy * 10 + xx).astype(np.uint16)


def test_format_support_matrix_lists_tiff_and_czi():
    matrix = format_support_matrix()
    formats = {row["format"] for row in matrix}
    assert any("TIFF" in f for f in formats)
    assert any("CZI" in f for f in formats)


def test_stack_revision_matches_path_source_identity(tmp_path: Path):
    path = tmp_path / "rev.tif"
    _write_zyx_tiff(path, _synthetic_stack(3, 8, 8))
    rev = stack_revision_from_path(path)
    assert rev.kind == "path"
    assert rev.identity == path_source_identity(path)
    assert rev.identity.startswith("path:")


def test_tiff_metadata_and_plane_parity_without_full_load_class(tmp_path: Path):
    """Native TIFF plane matches load_image_stack plane (value/shape/dtype)."""

    path = tmp_path / "stack.tif"
    arr = _synthetic_stack(6, 12, 10)
    _write_zyx_tiff(path, arr)

    ref = load_image_stack(path)
    with TiffVolumeSource(path, use_cache=False) as src:
        meta = src.metadata()
        assert meta.axes == "ZYX"
        assert meta.shape == ref.grayscale.shape
        assert meta.plane_access_mode in {"native_plane", "full_materialize_fallback"}
        assert meta.voxel_source in {"metadata", "default", "override"}
        # Do not treat default 1×1×1 as silently biological — source is explicit.
        assert meta.voxel_source != "unknown"

        for z in (0, 2, 5):
            plane = src.read_plane(z)
            assert plane.shape == ref.grayscale[z].shape
            assert plane.dtype == ref.grayscale[z].dtype
            np.testing.assert_array_equal(plane, ref.grayscale[z])

        block = src.read_block(1, 4, 2, 8, 1, 7)
        np.testing.assert_array_equal(block, ref.grayscale[1:4, 2:8, 1:7])

        roi = src.materialize_roi(z0=0, z1=2, y0=0, y1=5, x0=0, x1=5)
        np.testing.assert_array_equal(roi, ref.grayscale[0:2, 0:5, 0:5])


def test_open_volume_source_registry_reuses_handle(tmp_path: Path):
    path = tmp_path / "reuse.tif"
    _write_zyx_tiff(path, _synthetic_stack(4, 8, 8))
    registry = VolumeSourceRegistry(max_entries=2)
    a = registry.get_or_open(path)
    b = registry.get_or_open(path)
    assert a is b
    assert len(registry) == 1
    a.read_plane(1)
    registry.clear()
    assert len(registry) == 0


def test_registry_evicts_and_closes(tmp_path: Path):
    paths = []
    for i in range(4):
        p = tmp_path / f"e{i}.tif"
        _write_zyx_tiff(p, _synthetic_stack(3, 6, 6))
        paths.append(p)
    registry = VolumeSourceRegistry(max_entries=2)
    sources = [registry.get_or_open(p) for p in paths]
    assert len(registry) == 2
    # Oldest should be closed
    with pytest.raises(RuntimeError, match="closed"):
        sources[0].read_plane(0)


def test_plane_cache_budget_and_revision_invalidation():
    cache = PlaneCache(max_planes=3, max_bytes=10_000)
    rev = "path:test|m1|s1"
    plane = np.zeros((32, 32), dtype=np.uint8)
    for z in range(5):
        cache.put(rev, z, plane)
    assert len(cache) <= 3
    assert cache.nbytes <= 10_000 + plane.nbytes  # budget + one in-flight allowance

    cache.put(rev, 0, plane)
    assert cache.get(rev, 0) is not None
    cache.invalidate_revision(rev)
    assert cache.get(rev, 0) is None
    assert len(cache) == 0


def test_plane_cache_hit_is_fast(tmp_path: Path):
    path = tmp_path / "warm.tif"
    _write_zyx_tiff(path, _synthetic_stack(8, 64, 64))
    cache = PlaneCache(max_planes=5, max_bytes=32 * 1024 * 1024)
    src = TiffVolumeSource(path, plane_cache=cache, use_cache=True)
    try:
        src.read_plane(3)  # cold
        t0 = time.perf_counter()
        for _ in range(50):
            src.read_plane(3)
        warm_s = (time.perf_counter() - t0) / 50.0
        # Server-side warm neighbor budget <50 ms (far under on synthetic).
        assert warm_s < 0.050, f"warm plane hit too slow: {warm_s*1e3:.2f}ms"
    finally:
        src.close()


def test_concurrent_plane_reads_do_not_corrupt(tmp_path: Path):
    path = tmp_path / "conc.tif"
    arr = _synthetic_stack(10, 24, 24)
    _write_zyx_tiff(path, arr)
    src = TiffVolumeSource(path, use_cache=True)
    errors: list[BaseException] = []
    results: list[tuple[int, np.ndarray]] = []
    lock = threading.Lock()

    def worker(z: int) -> None:
        try:
            plane = src.read_plane(z)
            with lock:
                results.append((z, plane.copy()))
        except BaseException as exc:  # noqa: BLE001 — collect for assert
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(z % 10,)) for z in range(40)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    src.close()
    assert not errors, f"concurrent errors: {errors[:3]}"
    for z, plane in results:
        np.testing.assert_array_equal(plane, arr[z])


def test_materialize_roi_matches_array_slice():
    gray = _synthetic_stack(5, 20, 18)
    src = volume_source_from_array(
        gray,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        voxel_source="override",
        use_cache=False,
    )
    try:
        out = src.materialize_roi(z0=1, z1=4, y0=2, y1=10, x0=3, x1=12)
        np.testing.assert_array_equal(out, gray[1:4, 2:10, 3:12])
    finally:
        src.close()


def test_preview_frame_volume_parity_with_array(tmp_path: Path):
    path = tmp_path / "prev.tif"
    arr = _synthetic_stack(5, 20, 20)
    _write_zyx_tiff(path, arr)
    ref = load_image_stack(path)
    roi = RectROI(xmin=2, xmax=15, ymin=3, ymax=16)
    z_range = ZRange(zmin=0, zmax=5)

    frame_a, tr_a = extract_preview_frame(
        ref.grayscale, 2, roi=roi, z_range=z_range
    )
    with open_volume_source(path, register=False) as src:
        frame_b, tr_b = extract_preview_frame_from_volume(
            src, 2, roi=roi, z_range=z_range
        )
    np.testing.assert_array_equal(frame_a, frame_b)
    assert tr_a.x_offset == tr_b.x_offset
    assert tr_a.y_offset == tr_b.y_offset


def test_io_open_volume_source_adapter(tmp_path: Path):
    path = tmp_path / "io.tif"
    _write_zyx_tiff(path, _synthetic_stack(3, 8, 8))
    src = io_open_volume_source(path, register=False)
    try:
        assert src.metadata().shape[0] == 3
        src.read_plane(0)
    finally:
        src.close()


def test_array_volume_source_session_style():
    gray = _synthetic_stack(4, 10, 10)
    rev = StackRevision(identity="session:abc", kind="session")
    src = ArrayVolumeSource(
        gray,
        revision=rev,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        voxel_source="default",
        use_cache=False,
    )
    assert src.revision.identity == "session:abc"
    assert src.metadata().plane_access_mode == "array_backed"
    np.testing.assert_array_equal(src.read_plane(1), gray[1])
    src.close()


def test_closed_source_rejects_reads(tmp_path: Path):
    path = tmp_path / "closed.tif"
    _write_zyx_tiff(path, _synthetic_stack(3, 6, 6))
    src = open_volume_source(path, register=False)
    src.close()
    with pytest.raises(RuntimeError, match="closed"):
        src.read_plane(0)


def test_czi_interface_fallback_if_fixture_missing():
    """CZI path: interface documents full_materialize_fallback when no small fixture."""

    row = next(r for r in format_support_matrix() if r["format"] == "CZI")
    assert "full_materialize_fallback" in row["plane"]


def test_science_path_unchanged_by_volume_source_import(tmp_path: Path):
    """Opening VolumeSource must not alter load_image_stack / analyze outputs."""

    from morphostack.core.pipeline import ObjectSeed, analyze_stack

    path = tmp_path / "sci.tif"
    # Bright sphere-ish
    nz, n = 8, 24
    zz, yy, xx = np.ogrid[:nz, :n, :n]
    dist = np.sqrt((zz - nz / 2) ** 2 + (yy - n / 2) ** 2 + (xx - n / 2) ** 2)
    arr = (dist <= 6).astype(np.uint8) * 200
    _write_zyx_tiff(path, arr)

    ref = load_image_stack(path)
    with open_volume_source(path, register=False) as src:
        np.testing.assert_array_equal(src.read_plane(4), ref.grayscale[4])

    a1 = analyze_stack(
        ref.grayscale,
        thresholds=50.0,
        voxel_size=ref.voxel_size,
        object_seed=ObjectSeed(x=12.0, y=12.0, frame_index=4, radius=8.0),
        include_mesh=True,
    )
    a2 = analyze_stack(
        load_image_stack(path).grayscale,
        thresholds=50.0,
        voxel_size=ref.voxel_size,
        object_seed=ObjectSeed(x=12.0, y=12.0, frame_index=4, radius=8.0),
        include_mesh=True,
    )
    assert a1.mesh is not None and a2.mesh is not None
    assert a1.mesh.surface_area_um2 == pytest.approx(a2.mesh.surface_area_um2)
    assert a1.mesh.volume_um3 == pytest.approx(a2.mesh.volume_um3)


def test_default_plane_cache_singleton_shared():
    c1 = default_plane_cache()
    c2 = default_plane_cache()
    assert c1 is c2
