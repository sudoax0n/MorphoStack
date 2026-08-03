"""Focused tests for the verified Kimi audit fixes (bugs 4-13)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from morphostack.api import create_app
from morphostack.cli.main import main, object_seed_from_cli
from morphostack.core.batch import (
    BatchStackJob,
    assign_unique_batch_outputs,
    disambiguated_output_stem,
    run_batch_jobs,
    safe_output_stem,
)
from morphostack.core.pipeline import (
    ObjectSeed,
    StackViewTransform,
    _solid_mask_touches_seed_disk,
)
from morphostack.core.seed_mapping import nearest_int
from morphostack.core.seeded_vesicle import SeededSliceResult
from morphostack.core.skeleton import calculate_vs_perimeter


def test_skeleton_sums_disconnected_components():
    # Two separate 3-pixel horizontal segments far apart.
    skel = np.zeros((20, 20), dtype=bool)
    skel[5, 2:5] = True
    skel[15, 12:15] = True
    p_one, _ = calculate_vs_perimeter(skel[4:7, 1:6], voxel_size_um=1.0)
    p_all, _ = calculate_vs_perimeter(skel, voxel_size_um=1.0)
    # Full skeleton should include both components (strictly more than one alone).
    assert p_all > p_one
    assert p_all > 0


def test_skeleton_open_fragment_no_fake_closing_edge():
    """Three-pixel horizontal open fragment: 2 steps * 2 um = 4 um, not 8 um."""
    skel = np.zeros((5, 8), dtype=bool)
    skel[2, 2:5] = True  # pixels at x=2,3,4 — open chain
    p_um, p_naive = calculate_vs_perimeter(skel, voxel_size_um=2.0, voxel_y_um=0.5)
    assert p_um == pytest.approx(4.0)
    assert p_naive == pytest.approx(4.0)
    # Isotropic open fragment: 2 unit steps * 2 um
    p_iso, _ = calculate_vs_perimeter(skel, voxel_size_um=2.0, voxel_y_um=2.0)
    # VS open-path length for two even steps without wrap: 2 * 0.980 * 2 um
    assert p_iso == pytest.approx(2 * 0.980 * 2.0)


def test_skeleton_anisotropic_uses_physical_step_lengths():
    skel_h = np.zeros((5, 5), dtype=bool)
    skel_h[2, 1:4] = True  # three pixels, two open steps in x
    p_h, _ = calculate_vs_perimeter(skel_h, voxel_size_um=2.0, voxel_y_um=0.5)
    assert p_h == pytest.approx(4.0)
    p_iso, _ = calculate_vs_perimeter(skel_h, voxel_size_um=2.0, voxel_y_um=2.0)
    assert p_h != pytest.approx(p_iso)


def test_xy_distance_um_is_anisotropic():
    from morphostack.core.pipeline import xy_distance_um

    # 3 px in X, 4 px in Y with unequal spacing
    d = xy_distance_um(3.0, 4.0, x_um=2.0, y_um=0.5)
    assert d == pytest.approx(math.hypot(6.0, 2.0))
    # Mean spacing would wrongly map a physical 10 um limit; axes must stay separate.
    assert d != pytest.approx(math.hypot(3.0, 4.0) * 1.25)


def test_nearest_int_half_away_from_zero_matches_seed_mapping():
    assert nearest_int(32.5) == 33
    assert nearest_int(32.4) == 32
    assert nearest_int(-1.5) == -2
    assert nearest_int(-1.4) == -1

    transform = StackViewTransform.create(raw_shape=(10, 100, 100))
    seed = ObjectSeed(x=32.5, y=41.5, frame_index=2, radius=10.0)
    lx, ly, lz = transform.to_local_seed(seed)
    assert lx == 33
    assert ly == 42
    assert lz == 2


def test_touches_seed_disk_uses_search_center_not_centroid():
    # Solid touches disk rim around search center (10, 10), r*1.15=11.5.
    mask = np.zeros((40, 40), dtype=bool)
    # Paint a blob whose outer edge is near radius 11 from (10,10).
    yy, xx = np.ogrid[:40, :40]
    mask[(xx - 10) ** 2 + (yy - 10) ** 2 <= 11.2**2] = True
    # Centroid of a full disk is the center — force drift by using only right half.
    mask[:, :10] = False
    assert _solid_mask_touches_seed_disk(mask, seed_x=10.0, seed_y=10.0, seed_radius=10.0) is True
    # Wrong center (returned centroid would be shifted right) can miss the rim check.
    ys, xs = np.nonzero(mask)
    cx, cy = float(xs.mean()), float(ys.mean())
    assert abs(cx - 10.0) > 1.5  # drifted
    # Using drifted centroid should not be required for the true search-center check.
    res = SeededSliceResult(
        None,
        mask,
        (cx, cy),
        float(mask.sum()),
        0.0,
        "test",
        True,
        search_center_xy=(10.0, 10.0),
    )
    sc = res.search_center_xy or res.center_xy
    assert _solid_mask_touches_seed_disk(
        res.solid_mask, seed_x=sc[0], seed_y=sc[1], seed_radius=10.0
    ) is True


def test_batch_stem_collision_disambiguates_tif_tiff():
    claimed: set[str] = set()
    a = disambiguated_output_stem(Path("a/stack.tif"), claimed)
    b = disambiguated_output_stem(Path("b/stack.tiff"), claimed)
    assert a != b
    assert a == "stack"
    assert b == "stack_tiff"


def test_batch_jobs_unique_metrics_and_bundles(tmp_path: Path):
    tifffile = pytest.importorskip("tifffile")
    d = tmp_path / "in"
    d.mkdir()
    stack = np.zeros((2, 16, 16), dtype=np.uint8)
    stack[:, 4:12, 4:12] = 200
    p1 = d / "stack.tif"
    p2 = d / "stack.tiff"
    tifffile.imwrite(p1, stack, photometric="minisblack")
    tifffile.imwrite(p2, stack, photometric="minisblack")
    metrics = tmp_path / "metrics"
    bundles = tmp_path / "bundles"
    jobs = [
        BatchStackJob(
            index=0,
            source_path=str(p1.resolve()),
            threshold=100.0,
            profile="vesicle",
            prefer_opencv=False,
            include_mesh=False,
            metrics_dir=str(metrics),
            bundle_dir=str(bundles),
            input_dir=str(d.resolve()),
            compute_sha256=False,
        ),
        BatchStackJob(
            index=1,
            source_path=str(p2.resolve()),
            threshold=100.0,
            profile="vesicle",
            prefer_opencv=False,
            include_mesh=False,
            metrics_dir=str(metrics),
            bundle_dir=str(bundles),
            input_dir=str(d.resolve()),
            compute_sha256=False,
        ),
    ]
    assigned = assign_unique_batch_outputs(jobs)
    assert assigned[0].metrics_stem != assigned[1].metrics_stem
    assert assigned[0].bundle_rel != assigned[1].bundle_rel
    report = run_batch_jobs(assigned, workers=1)
    assert report.failures == 0
    metric_files = sorted(metrics.glob("*_metrics.csv"))
    assert len(metric_files) == 2
    manifests = list(bundles.rglob("manifest.json"))
    assert len(manifests) == 2
    assert len({m.parent for m in manifests}) == 2


def test_object_seed_tuning_without_coords_is_usage_error():
    with pytest.raises(SystemExit) as ei:
        object_seed_from_cli(
            seed_x=None,
            seed_y=None,
            seed_frame=None,
            seed_max_dist_um=25.0,
        )
    assert ei.value.code == 2

    with pytest.raises(SystemExit) as ei2:
        object_seed_from_cli(
            seed_x=None,
            seed_y=None,
            seed_frame=None,
            seed_radius=5.0,
            seed_radius_explicit=True,
        )
    assert ei2.value.code == 2

    assert object_seed_from_cli(seed_x=None, seed_y=None, seed_frame=None) is None
    seed = object_seed_from_cli(seed_x=1.0, seed_y=2.0, seed_frame=0, seed_radius=5.0)
    assert seed is not None
    assert seed.radius == 5.0


def test_cors_rejects_unrelated_origin():
    client = TestClient(create_app())
    # Preflight from a remote site must not be granted.
    preflight = client.options(
        "/analyze",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    allow = preflight.headers.get("access-control-allow-origin")
    assert allow in (None, "") or allow != "https://evil.example"

    # Local Vite origin is allowed.
    ok = client.options(
        "/analyze",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_sweep_invalid_step_exits_2(tmp_path: Path, capsys):
    tifffile = pytest.importorskip("tifffile")
    path = tmp_path / "s.tif"
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:6, 2:6] = 200
    tifffile.imwrite(path, stack, photometric="minisblack")
    out = tmp_path / "sweep.csv"
    code = main(
        [
            "sweep",
            str(path),
            "--start",
            "10",
            "--stop",
            "50",
            "--step",
            "0",
            "--out",
            str(out),
            "--no-mesh",
        ]
    )
    assert code == 2
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "Invalid sweep" in err or "step" in err.lower()


def test_safe_output_stem_basic():
    assert safe_output_stem(Path("foo bar.tif")) == "foo_bar"
