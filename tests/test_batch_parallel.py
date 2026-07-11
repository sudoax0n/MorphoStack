"""Packet 07: memory-bounded multi-process batch scheduler."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
import tifffile

from morphostack.core.batch import (
    BatchStackJob,
    parse_workers_spec,
    process_batch_stack_job,
    resolve_worker_count,
    run_batch_jobs,
    scientific_summary_fields,
)
from morphostack.cli.main import run_batch


def _write_sphere_tif(path: Path, *, nz: int = 12, ny: int = 48, nx: int = 48, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    zz, yy, xx = np.ogrid[:nz, :ny, :nx]
    cz, cy, cx = (nz - 1) / 2.0, (ny - 1) / 2.0, (nx - 1) / 2.0
    r = 10.0
    r2 = ((xx - cx) / r) ** 2 + ((yy - cy) / r) ** 2 + ((zz - cz) / (r * 0.6)) ** 2
    stack = np.zeros((nz, ny, nx), dtype=np.float32)
    stack[r2 <= 1.0] = 40.0
    stack[(r2 <= 1.05) & (r2 >= 0.75)] = 180.0
    stack += rng.normal(0, 4.0, size=stack.shape).astype(np.float32)
    stack = np.clip(stack, 0, 255)
    tifffile.imwrite(path, stack)


def _make_batch_dir(tmp_path: Path, n: int = 4) -> Path:
    d = tmp_path / "stacks"
    d.mkdir()
    for i in range(n):
        _write_sphere_tif(d / f"syn_{i:02d}.tif", seed=i)
    return d


def _jobs_for_dir(directory: Path, **kwargs) -> list[BatchStackJob]:
    paths = sorted(directory.glob("*.tif"))
    base = dict(
        threshold=80.0,
        profile="vesicle",
        prefer_opencv=True,
        include_mesh=False,
        compute_sha256=True,
    )
    base.update(kwargs)
    return [
        BatchStackJob(index=i, source_path=str(p.resolve()), **base) for i, p in enumerate(paths)
    ]


def test_parse_workers_spec():
    assert parse_workers_spec(1) == 1
    assert parse_workers_spec("2") == 2
    assert parse_workers_spec("auto") == "auto"
    with pytest.raises(ValueError):
        parse_workers_spec(0)


def test_resolve_worker_count_auto_respects_caps_and_ram():
    n, meta = resolve_worker_count("auto", n_jobs=10, max_workers=4, estimated_bytes_per_stack=64 * 1024 * 1024)
    assert 1 <= n <= 4
    assert meta["mode"] == "auto"
    assert meta["resolved"] == n

    n1, meta1 = resolve_worker_count(1, n_jobs=10)
    assert n1 == 1
    assert meta1["mode"] == "explicit"

    # Huge per-stack estimate forces workers down toward 1.
    n_ram, meta_ram = resolve_worker_count(
        "auto", n_jobs=50, max_workers=4, estimated_bytes_per_stack=10**12
    )
    assert n_ram == 1
    assert meta_ram.get("workers_by_ram") == 1


def test_workers_1_and_2_scientific_equivalence(tmp_path: Path):
    batch_dir = _make_batch_dir(tmp_path, n=3)
    jobs = _jobs_for_dir(batch_dir, compute_sha256=True)

    r1 = run_batch_jobs(jobs, workers=1)
    r2 = run_batch_jobs(jobs, workers=2)

    assert r1.workers_used == 1
    assert r2.workers_used >= 1
    assert len(r1.results) == len(r2.results) == 3
    assert r1.failures == 0 and r2.failures == 0

    for a, b in zip(r1.results, r2.results):
        assert a.index == b.index
        assert a.source_path == b.source_path
        assert a.ok and b.ok
        sa = scientific_summary_fields(a.summary_row)
        sb = scientific_summary_fields(b.summary_row)
        # SHA must match (computed once per file, same file).
        assert sa["source_sha256"] == sb["source_sha256"]
        assert sa["source_sha256"]
        # Scientific metrics / status / profile match (allow float string equality).
        for key in sa:
            if key in {"source_path"}:
                continue
            va, vb = sa[key], sb[key]
            if isinstance(va, float) or isinstance(vb, float):
                assert float(va) == pytest.approx(float(vb), rel=0, abs=1e-9), key
            else:
                assert va == vb, (key, va, vb)


def test_ordered_results_independent_of_completion(tmp_path: Path):
    batch_dir = _make_batch_dir(tmp_path, n=4)
    jobs = _jobs_for_dir(batch_dir)
    report = run_batch_jobs(jobs, workers=2)
    idxs = [r.index for r in report.results]
    assert idxs == list(range(4))
    paths = [r.source_path for r in report.results]
    assert paths == sorted(paths)


def test_partial_failure_preserves_successes(tmp_path: Path):
    batch_dir = _make_batch_dir(tmp_path, n=3)
    # Corrupt one file into non-image garbage.
    bad = batch_dir / "syn_01.tif"
    bad.write_bytes(b"not-a-tiff")

    jobs = _jobs_for_dir(batch_dir)
    report = run_batch_jobs(jobs, workers=2)
    assert report.failures >= 1
    oks = [r for r in report.results if r.ok]
    fails = [r for r in report.results if not r.ok]
    assert len(oks) >= 2
    assert len(fails) >= 1
    assert all(r.summary_row.get("status") == "ok" for r in oks)
    assert all(r.summary_row.get("status") == "error" for r in fails)
    # Input order retained
    assert [r.index for r in report.results] == list(range(3))


def test_bundle_and_metrics_no_collision(tmp_path: Path):
    batch_dir = _make_batch_dir(tmp_path, n=2)
    metrics = tmp_path / "metrics"
    bundles = tmp_path / "bundles"
    jobs = _jobs_for_dir(
        batch_dir,
        metrics_dir=str(metrics),
        bundle_dir=str(bundles),
        input_dir=str(batch_dir.resolve()),
    )
    report = run_batch_jobs(jobs, workers=2)
    assert report.failures == 0
    metric_files = sorted(metrics.glob("*_metrics.csv"))
    assert len(metric_files) == 2
    manifests = list(bundles.rglob("manifest.json"))
    assert len(manifests) == 2
    # Distinct run dirs
    assert len({m.parent for m in manifests}) == 2


def test_cli_run_batch_workers_1_and_summary(tmp_path: Path):
    batch_dir = _make_batch_dir(tmp_path, n=2)
    out = tmp_path / "summary.csv"
    code = run_batch(
        directory=str(batch_dir),
        threshold=80.0,
        out=str(out),
        workers="1",
        include_mesh=False,
    )
    assert code == 0
    assert out.is_file()
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert all(r["status"] == "ok" for r in rows)


def test_cli_run_batch_workers_2(tmp_path: Path):
    batch_dir = _make_batch_dir(tmp_path, n=3)
    out = tmp_path / "summary2.csv"
    code = run_batch(
        directory=str(batch_dir),
        threshold=80.0,
        out=str(out),
        workers="2",
        include_mesh=False,
    )
    assert code == 0
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3


def test_process_one_job_direct(tmp_path: Path):
    p = tmp_path / "one.tif"
    _write_sphere_tif(p)
    job = BatchStackJob(
        index=0,
        source_path=str(p),
        threshold=80.0,
        profile="vesicle",
        prefer_opencv=True,
        include_mesh=False,
    )
    res = process_batch_stack_job(job)
    assert res.ok
    assert res.summary_row["status"] == "ok"
    assert int(res.summary_row["frame_count"]) == 12
