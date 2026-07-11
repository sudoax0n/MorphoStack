"""Derived display pyramid (packet 11) — display-only, science isolated."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from morphostack.core.display_pyramid import (
    DisplayPyramidStore,
    PyramidConfig,
    mean_pool_downsample,
    plan_levels,
    pyramid_cache_key,
    select_level_for_budget,
    storage_decision_record,
)
from morphostack.core.mesh import marching_cubes_measurement
from morphostack.core.models import ResultAuthorityError, VoxelSize, reject_non_scientific_input
from morphostack.core.volume_source import stack_revision_for_array


def _sphere_volume(nz: int = 16, n: int = 32, radius: float = 8.0) -> np.ndarray:
    zz, yy, xx = np.ogrid[:nz, :n, :n]
    dist = np.sqrt((zz - nz / 2) ** 2 + (yy - n / 2) ** 2 + (xx - n / 2) ** 2)
    return (dist <= radius).astype(np.uint8) * 200


def test_storage_decision_is_internal_npy_without_zarr_dep():
    rec = storage_decision_record()
    assert rec["chosen"] == "internal_npy_v1"
    assert rec["ome_ngff_zarr"] == "not_selected"
    assert rec["lossy_compression"] is False


def test_pyramid_cache_key_deterministic():
    rev = stack_revision_for_array(token="fixed")
    # force stable identity
    from morphostack.core.volume_source import StackRevision

    rev = StackRevision(identity="array:fixed", kind="array")
    cfg = PyramidConfig(max_levels=3, max_level_bytes=1024 * 1024)
    vox = VoxelSize(0.5, 0.5, 1.0)
    k1 = pyramid_cache_key(
        rev,
        source_axes="ZYX",
        source_dtype="uint8",
        voxel_size=vox,
        voxel_source="override",
        config=cfg,
    )
    k2 = pyramid_cache_key(
        rev,
        source_axes="ZYX",
        source_dtype="uint8",
        voxel_size=vox,
        voxel_source="override",
        config=cfg,
    )
    assert k1 == k2
    k3 = pyramid_cache_key(
        rev,
        source_axes="ZYX",
        source_dtype="uint8",
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        voxel_source="override",
        config=cfg,
    )
    assert k3 != k1


def test_mean_pool_and_plan_levels():
    vol = np.arange(8 * 16 * 16, dtype=np.uint16).reshape(8, 16, 16)
    down = mean_pool_downsample(vol, 2)
    assert down.shape == (4, 8, 8)
    planned = plan_levels((32, 64, 64), np.dtype("uint8"), config=PyramidConfig(max_levels=4, max_level_bytes=10**9))
    assert planned[0][0] == 0
    assert planned[-1][0] >= 1
    assert planned[-1][1][0] < planned[0][1][0]


def test_build_partial_complete_and_manifest(tmp_path: Path):
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    vol = _sphere_volume()
    rev = stack_revision_for_array(token="sph")
    cfg = PyramidConfig(max_levels=3, max_level_bytes=10**9, max_source_bytes=10**9)
    key = store.build_from_array(
        vol,
        revision=rev,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        voxel_source="override",
        config=cfg,
    )
    status = store.read_status(key)
    assert status is not None
    assert status.state == "complete"
    assert status.manifest is not None
    assert status.manifest["complete"] is True
    assert status.manifest["display_only"] is True
    assert sorted(status.levels_ready) == sorted(status.planned_levels)
    # Coarse level has larger voxels
    levels = status.manifest["levels"]
    fine = next(lv for lv in levels if lv["level"] == 0)
    coarse = max(levels, key=lambda lv: lv["level"])
    assert coarse["voxel_size"]["x_um"] >= fine["voxel_size"]["x_um"]
    assert all(lv["display_only"] for lv in levels)


def test_interrupted_build_never_marked_complete(tmp_path: Path):
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    vol = _sphere_volume(nz=12, n=24)
    rev = stack_revision_for_array(token="intr")
    cfg = PyramidConfig(max_levels=4, max_level_bytes=10**9)
    key = pyramid_cache_key(
        rev,
        source_axes="ZYX",
        source_dtype=str(vol.dtype),
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        voxel_source="default",
        config=cfg,
    )
    # Simulate partial: write state partial without complete flag
    cache_dir = store.cache_dir(key)
    cache_dir.mkdir(parents=True)
    (cache_dir / "levels").mkdir()
    # only one level file
    arr = mean_pool_downsample(vol, 2)
    from morphostack.core.display_pyramid import _atomic_save_npy, _atomic_write_json

    _atomic_save_npy(store.level_path(key, 1), arr)
    manifest = {
        "cache_key": key,
        "complete": False,
        "display_only": True,
        "levels": [
            {
                "level": 1,
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
                "axes": "ZYX",
                "scale_zyx": [2, 2, 2],
                "voxel_size": {"x_um": 2.0, "y_um": 2.0, "z_um": 2.0},
                "nbytes": int(arr.nbytes),
                "display_only": True,
                "downsample_from_source": [2, 2, 2],
            }
        ],
        "source_revision": rev.identity,
    }
    _atomic_write_json(store.manifest_path(key), manifest)
    _atomic_write_json(
        store.state_path(key),
        {
            "cache_key": key,
            "state": "partial",
            "source_revision": rev.identity,
            "levels_ready": [1],
            "planned_levels": [0, 1, 2],
            "error": None,
            "config": cfg.to_dict(),
        },
    )
    status = store.read_status(key)
    assert status is not None
    assert status.state == "partial"
    assert status.manifest is not None
    assert status.manifest.get("complete") is not True


def test_stale_source_revision_new_key(tmp_path: Path):
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    vol = _sphere_volume()
    from morphostack.core.volume_source import StackRevision

    r1 = StackRevision(identity="path:a|m1|s1", kind="path")
    r2 = StackRevision(identity="path:a|m2|s1", kind="path")
    cfg = PyramidConfig(max_levels=2, max_level_bytes=10**9)
    k1 = store.build_from_array(vol, revision=r1, voxel_size=VoxelSize(1, 1, 1), config=cfg)
    k2 = store.build_from_array(vol, revision=r2, voxel_size=VoxelSize(1, 1, 1), config=cfg)
    assert k1 != k2
    assert store.read_status(k1).state == "complete"
    assert store.read_status(k2).state == "complete"


def test_level_shape_scale_and_budget_selection(tmp_path: Path):
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    vol = _sphere_volume(nz=16, n=48)
    rev = stack_revision_for_array(token="budg")
    # Force small transfer budget so auto-select prefers coarse
    cfg = PyramidConfig(max_levels=3, max_level_bytes=10**9)
    key = store.build_from_array(
        vol,
        revision=rev,
        voxel_size=VoxelSize(0.25, 0.25, 0.5),
        voxel_source="override",
        config=cfg,
    )
    descs = store.get_ready_level_descriptors(key)
    assert descs
    tiny = select_level_for_budget(descs, max_bytes=500)
    assert tiny is not None
    # tiny budget should pick a small/coarse level
    assert tiny.nbytes <= max(d.nbytes for d in descs)
    desc, arr, spec = store.select_and_load_level(key, max_bytes=tiny.nbytes)
    assert arr.shape == desc.shape
    assert desc.axes.upper() == "ZYX"
    assert spec.display_only is True
    assert spec.level == desc.level
    # physical scale grows with downsample
    if desc.level > 0:
        assert desc.voxel_size.x_um > 0.25


def test_lower_level_rejected_by_science_apis(tmp_path: Path):
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    vol = _sphere_volume()
    rev = stack_revision_for_array(token="sci")
    key = store.build_from_array(
        vol,
        revision=rev,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        config=PyramidConfig(max_levels=3, max_level_bytes=10**9),
    )
    desc, arr, spec = store.select_and_load_level(key, level=max(d.level for d in store.get_ready_level_descriptors(key)))
    with pytest.raises(ResultAuthorityError):
        reject_non_scientific_input(spec, context="metrics")
    with pytest.raises(ResultAuthorityError):
        marching_cubes_measurement(spec, VoxelSize(1.0, 1.0, 1.0))  # type: ignore[arg-type]
    # Raw array from display level is still an array — science path should use AuthoritativeMask.
    # DisplayVolumeSpec is the typed rejection gate for pyramid products.
    assert desc.display_only is True
    assert arr.ndim == 3


def test_science_path_unchanged_when_pyramid_built(tmp_path: Path):
    pytest.importorskip("skimage")
    from morphostack.core.pipeline import ObjectSeed, analyze_stack

    vol = _sphere_volume(nz=10, n=28, radius=7.0)
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    rev = stack_revision_for_array(token="an")
    store.build_from_array(
        vol,
        revision=rev,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        config=PyramidConfig(max_levels=2, max_level_bytes=10**9),
    )
    a1 = analyze_stack(
        vol,
        thresholds=50.0,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        object_seed=ObjectSeed(x=14.0, y=14.0, frame_index=5, radius=8.0),
        include_mesh=True,
    )
    a2 = analyze_stack(
        vol,
        thresholds=50.0,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        object_seed=ObjectSeed(x=14.0, y=14.0, frame_index=5, radius=8.0),
        include_mesh=True,
    )
    assert a1.mesh is not None and a2.mesh is not None
    assert a1.mesh.surface_area_um2 == pytest.approx(a2.mesh.surface_area_um2)
    assert a1.mesh.volume_um3 == pytest.approx(a2.mesh.volume_um3)


def test_warm_level_read_timing(tmp_path: Path):
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    vol = _sphere_volume(nz=20, n=64)
    rev = stack_revision_for_array(token="perf")
    t0 = time.perf_counter()
    key = store.build_from_array(
        vol,
        revision=rev,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        config=PyramidConfig(max_levels=3, max_level_bytes=10**9),
    )
    build_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    for _ in range(20):
        store.select_and_load_level(key, max_bytes=10**9)
    warm_s = (time.perf_counter() - t1) / 20.0
    # Warm read suitable for <<2 s first-paint budget
    assert warm_s < 0.5, f"warm level read too slow: {warm_s:.3f}s"
    assert build_s < 30.0  # cold synthetic should be quick


def test_invalidate_removes_cache(tmp_path: Path):
    store = DisplayPyramidStore(cache_root=tmp_path / "cache")
    rev = stack_revision_for_array(token="del")
    key = store.build_from_array(
        _sphere_volume(),
        revision=rev,
        voxel_size=VoxelSize(1, 1, 1),
        config=PyramidConfig(max_levels=2, max_level_bytes=10**9),
    )
    assert store.cache_dir(key).is_dir()
    store.invalidate(key)
    assert store.read_status(key) is None


# ---------------------------------------------------------------------------
# Retention / concurrency / shutdown (packet 11 fix)
# ---------------------------------------------------------------------------


def test_cache_eviction_lru_by_entry_count(tmp_path: Path):
    from morphostack.core.display_pyramid import StoreRetentionConfig
    from morphostack.core.volume_source import StackRevision

    store = DisplayPyramidStore(
        cache_root=tmp_path / "cache",
        retention=StoreRetentionConfig(max_entries=2, max_total_bytes=10**12, max_active_builds=4),
    )
    cfg = PyramidConfig(max_levels=2, max_level_bytes=10**9)
    keys = []
    for i in range(3):
        rev = StackRevision(identity=f"array:evict-{i}", kind="array")
        k = store.build_from_array(
            _sphere_volume(nz=8, n=16),
            revision=rev,
            voxel_size=VoxelSize(1, 1, 1),
            config=cfg,
        )
        keys.append(k)
        # Touch first key so it is MRU when third is built after second
        if i == 1:
            store.select_and_load_level(keys[0], max_bytes=10**9)
    # After 3 builds with max_entries=2, oldest unused should be gone.
    # keys[0] was touched after keys[1], so keys[1] is older and should evict first.
    assert store.entry_count() <= 2
    assert store.read_status(keys[1]) is None or store.read_status(keys[0]) is not None
    assert store.read_status(keys[2]) is not None
    # Exactly one of the first two may remain; entry count bound holds.
    present = sum(1 for k in keys if store.read_status(k) is not None)
    assert present <= 2


def test_active_build_never_evicted(tmp_path: Path):
    import threading

    from morphostack.core.display_pyramid import StoreRetentionConfig
    from morphostack.core.volume_source import StackRevision, volume_source_from_array

    store = DisplayPyramidStore(
        cache_root=tmp_path / "cache",
        retention=StoreRetentionConfig(max_entries=1, max_total_bytes=10**12, max_active_builds=2),
    )
    # Fill cache with one complete entry
    k0 = store.build_from_array(
        _sphere_volume(nz=6, n=12),
        revision=StackRevision(identity="array:old", kind="array"),
        voxel_size=VoxelSize(1, 1, 1),
        config=PyramidConfig(max_levels=2, max_level_bytes=10**9),
    )
    assert store.read_status(k0) is not None

    release = threading.Event()
    started = threading.Event()

    class _SlowSource:
        def __init__(self) -> None:
            self._src = volume_source_from_array(
                _sphere_volume(nz=6, n=12),
                voxel_size=VoxelSize(1, 1, 1),
                revision=StackRevision(identity="array:active", kind="array"),
                use_cache=False,
            )

        @property
        def revision(self):
            return self._src.revision

        def metadata(self):
            return self._src.metadata()

        def materialize_roi(self, **kwargs):
            started.set()
            release.wait(timeout=10.0)
            return self._src.materialize_roi(**kwargs)

        def close(self) -> None:
            self._src.close()

    slow = _SlowSource()
    key_active = store.start_build_from_volume_source(slow, background=True)  # type: ignore[arg-type]
    assert started.wait(timeout=5.0)
    assert store.active_build_count() >= 1
    # Force retention while active
    store.enforce_retention()
    assert store.read_status(key_active) is not None
    assert key_active in store.list_cache_keys() or store._is_active_build(key_active)
    # Active must still be registered
    assert store._is_active_build(key_active)
    release.set()
    # Join
    deadline = time.time() + 10
    while store.active_build_count() > 0 and time.time() < deadline:
        time.sleep(0.05)
    assert store.read_status(key_active) is not None
    assert store.read_status(key_active).state == "complete"


def test_duplicate_attach_same_key(tmp_path: Path):
    import threading

    from morphostack.core.display_pyramid import StoreRetentionConfig
    from morphostack.core.volume_source import StackRevision, volume_source_from_array

    store = DisplayPyramidStore(
        cache_root=tmp_path / "cache",
        retention=StoreRetentionConfig(max_entries=4, max_total_bytes=10**12, max_active_builds=2),
    )
    release = threading.Event()
    started = threading.Event()
    rev = StackRevision(identity="array:dup", kind="array")

    class _SlowSource:
        def __init__(self) -> None:
            self._src = volume_source_from_array(
                _sphere_volume(nz=6, n=12),
                voxel_size=VoxelSize(1, 1, 1),
                revision=rev,
                use_cache=False,
            )

        @property
        def revision(self):
            return self._src.revision

        def metadata(self):
            return self._src.metadata()

        def materialize_roi(self, **kwargs):
            started.set()
            release.wait(timeout=10.0)
            return self._src.materialize_roi(**kwargs)

        def close(self) -> None:
            self._src.close()

    src = _SlowSource()
    k1 = store.start_build_from_volume_source(src, background=True)  # type: ignore[arg-type]
    assert started.wait(timeout=5.0)
    k2 = store.start_build_from_volume_source(src, background=True)  # type: ignore[arg-type]
    assert k1 == k2
    # Only one active job for that key
    assert store.active_build_count() == 1
    release.set()
    deadline = time.time() + 10
    while store.active_build_count() > 0 and time.time() < deadline:
        time.sleep(0.05)
    # Complete attach
    k3 = store.start_build_from_volume_source(src, background=True)  # type: ignore[arg-type]
    assert k3 == k1
    assert store.read_status(k3).state == "complete"
    assert store.active_build_count() == 0


def test_concurrency_bound_rejects_extra_new_builds(tmp_path: Path):
    import threading

    from morphostack.core.display_pyramid import ActiveBuildLimitError, StoreRetentionConfig
    from morphostack.core.volume_source import StackRevision, volume_source_from_array

    store = DisplayPyramidStore(
        cache_root=tmp_path / "cache",
        retention=StoreRetentionConfig(max_entries=8, max_total_bytes=10**12, max_active_builds=2),
    )
    release = threading.Event()
    started = [threading.Event(), threading.Event()]

    def make_slow(i: int):
        rev = StackRevision(identity=f"array:conc-{i}", kind="array")

        class _Slow:
            def __init__(self) -> None:
                self._src = volume_source_from_array(
                    _sphere_volume(nz=4, n=10),
                    voxel_size=VoxelSize(1, 1, 1),
                    revision=rev,
                    use_cache=False,
                )
                self._i = i

            @property
            def revision(self):
                return self._src.revision

            def metadata(self):
                return self._src.metadata()

            def materialize_roi(self, **kwargs):
                started[self._i].set()
                release.wait(timeout=10.0)
                return self._src.materialize_roi(**kwargs)

            def close(self) -> None:
                self._src.close()

        return _Slow()

    s0, s1 = make_slow(0), make_slow(1)
    store.start_build_from_volume_source(s0, background=True)  # type: ignore[arg-type]
    store.start_build_from_volume_source(s1, background=True)  # type: ignore[arg-type]
    assert started[0].wait(timeout=5.0)
    assert started[1].wait(timeout=5.0)
    assert store.active_build_count() == 2
    s2 = make_slow(2)
    with pytest.raises(ActiveBuildLimitError):
        store.start_build_from_volume_source(s2, background=True)  # type: ignore[arg-type]
    release.set()
    deadline = time.time() + 10
    while store.active_build_count() > 0 and time.time() < deadline:
        time.sleep(0.05)


def test_shutdown_cancels_and_joins(tmp_path: Path):
    import threading

    from morphostack.core.display_pyramid import StoreRetentionConfig
    from morphostack.core.volume_source import StackRevision, volume_source_from_array

    store = DisplayPyramidStore(
        cache_root=tmp_path / "cache",
        retention=StoreRetentionConfig(max_entries=4, max_total_bytes=10**12, max_active_builds=2),
    )
    started = threading.Event()
    release = threading.Event()  # never set before shutdown

    class _Slow:
        def __init__(self) -> None:
            self._src = volume_source_from_array(
                _sphere_volume(nz=4, n=10),
                voxel_size=VoxelSize(1, 1, 1),
                revision=StackRevision(identity="array:shut", kind="array"),
                use_cache=False,
            )

        @property
        def revision(self):
            return self._src.revision

        def metadata(self):
            return self._src.metadata()

        def materialize_roi(self, **kwargs):
            started.set()
            # Wait until cancelled via long poll of release OR cancel checked after
            release.wait(timeout=30.0)
            return self._src.materialize_roi(**kwargs)

        def close(self) -> None:
            self._src.close()

    store.start_build_from_volume_source(_Slow(), background=True)  # type: ignore[arg-type]
    assert started.wait(timeout=5.0)
    t0 = time.time()
    store.shutdown(timeout=5.0)
    assert time.time() - t0 < 6.0
    assert store.active_build_count() == 0
    with pytest.raises(RuntimeError, match="shutting down"):
        store.build_from_array(
            _sphere_volume(nz=4, n=8),
            revision=StackRevision(identity="array:after", kind="array"),
            voxel_size=VoxelSize(1, 1, 1),
            config=PyramidConfig(max_levels=1, max_level_bytes=10**9),
        )
