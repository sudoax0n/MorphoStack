"""Memory-bounded multi-process batch scheduling over ``analyze_stack``.

Outer-file parallelism only. Each worker loads one stack, calls the same
``analyze_stack`` science path as serial batch, and returns a serializable
summary row. ``workers=1`` is the reference/rollback path (no pool).

Windows spawn: the worker entrypoint is a top-level function in this module
and does not re-enter the CLI.
"""

from __future__ import annotations

import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Sequence

from morphostack.core.export import (
    analysis_manifest,
    analysis_summary_row,
    failed_analysis_summary_row,
    write_analysis_csv,
    write_analysis_manifest_json,
    write_analysis_report_markdown,
)
from morphostack.core.io import file_sha256, load_image_stack
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import RectROI, ZRange, analyze_stack


# Initial hard cap (Milestone A). Raise only with measured RAM evidence.
DEFAULT_MAX_WORKERS = 4
# Leave at least this much free RAM when sizing ``auto``.
_MIN_FREE_RAM_BYTES = 1 * 1024 * 1024 * 1024
# Fraction of currently available RAM allowed for concurrent stack materialization.
_RAM_BUDGET_FRACTION = 0.45
# Fallback per-stack estimate when file size is tiny/unknown (decoded float-ish).
_MIN_STACK_ESTIMATE_BYTES = 32 * 1024 * 1024


WorkerSpec = int | Literal["auto"]


@dataclass(frozen=True)
class BatchStackJob:
    """Picklable per-file work item (paths and plain scalars only)."""

    index: int
    source_path: str
    threshold: float
    profile: str
    prefer_opencv: bool
    include_mesh: bool
    voxel_x: float | None = None
    voxel_y: float | None = None
    voxel_z: float | None = None
    roi: tuple[int, int, int, int] | None = None  # xmin, xmax, ymin, ymax
    z_range: tuple[int, int] | None = None  # zmin, zmax
    metrics_dir: str | None = None
    bundle_dir: str | None = None
    input_dir: str | None = None  # for relative bundle layout
    compute_sha256: bool = True
    # Pre-assigned unique output names (set by assign_unique_batch_outputs).
    metrics_stem: str | None = None  # basename without _metrics.csv
    bundle_rel: str | None = None  # posix path relative to bundle_dir


@dataclass
class BatchStackResult:
    """Picklable per-file outcome; ordered by ``index`` after gather."""

    index: int
    source_path: str
    ok: bool
    summary_row: dict[str, object]
    error_message: str = ""
    source_sha256: str = ""
    worker_pid: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "source_path": self.source_path,
            "ok": self.ok,
            "error_message": self.error_message,
            "source_sha256": self.source_sha256,
            "worker_pid": self.worker_pid,
            "summary_row": dict(self.summary_row),
        }


@dataclass
class BatchRunReport:
    """Ordered results plus worker/RAM metadata for artifacts."""

    workers_requested: str
    workers_used: int
    results: list[BatchStackResult] = field(default_factory=list)
    governor: dict[str, Any] = field(default_factory=dict)
    failures: int = 0

    @property
    def summary_rows(self) -> list[dict[str, object]]:
        return [r.summary_row for r in self.results]


def safe_output_stem(path: Path) -> str:
    raw = path.stem.strip() or "stack"
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in raw)


def disambiguated_output_stem(path: Path, claimed: set[str]) -> str:
    """Return a unique safe stem for metrics/bundle basenames.

    Same-stem collisions (``stack.tif`` vs ``stack.tiff``, or flat metrics dir)
    append a sanitized suffix, then a numeric index. Never silently reuses a
    claimed name. Mutates ``claimed`` to record the chosen stem.
    """
    base = safe_output_stem(path)
    if base not in claimed:
        claimed.add(base)
        return base
    ext = path.suffix.lower().lstrip(".") or "file"
    ext = "".join(char if char.isalnum() or char in "._-" else "_" for char in ext)
    candidate = f"{base}_{ext}"
    if candidate not in claimed:
        claimed.add(candidate)
        return candidate
    index = 2
    while True:
        numbered = f"{candidate}_{index}"
        if numbered not in claimed:
            claimed.add(numbered)
            return numbered
        index += 1


def unique_bundle_run_directory(
    bundle_dir: str | Path,
    source_path: str | Path,
    *,
    relative_to: str | Path | None = None,
    claimed_posix: set[str],
) -> Path:
    """Like ``bundle_run_directory`` but never reuses a claimed output path."""
    source = Path(source_path)
    if relative_to is None:
        stem = disambiguated_output_stem(source, claimed_posix)
        return Path(bundle_dir) / stem

    relative = source.relative_to(relative_to)
    parent_parts = [
        safe_output_stem(Path(part)) for part in relative.parent.parts if part not in (".", "")
    ]
    parent_key = "/".join(parent_parts)
    if parent_key:
        prefix = parent_key + "/"
        local_claimed = {
            key[len(prefix) :]
            for key in claimed_posix
            if key.startswith(prefix) and "/" not in key[len(prefix) :]
        }
    else:
        local_claimed = {key for key in claimed_posix if "/" not in key}
    stem = disambiguated_output_stem(source, local_claimed)
    full_key = f"{parent_key}/{stem}" if parent_key else stem
    claimed_posix.add(full_key)
    return Path(bundle_dir).joinpath(*parent_parts, stem)


def assign_unique_batch_outputs(jobs: Sequence[BatchStackJob]) -> list[BatchStackJob]:
    """Pre-assign collision-free metrics stems and bundle paths for all jobs."""
    metrics_claimed: set[str] = set()
    bundle_claimed: set[str] = set()
    assigned: list[BatchStackJob] = []
    for job in jobs:
        path = Path(job.source_path)
        metrics_stem = job.metrics_stem
        if job.metrics_dir and not metrics_stem:
            metrics_stem = disambiguated_output_stem(path, metrics_claimed)
        bundle_rel = job.bundle_rel
        if job.bundle_dir and not bundle_rel:
            rel = Path(job.input_dir) if job.input_dir else None
            run_dir = unique_bundle_run_directory(
                job.bundle_dir, path, relative_to=rel, claimed_posix=bundle_claimed
            )
            bundle_rel = Path(run_dir).relative_to(job.bundle_dir).as_posix()
        assigned.append(replace(job, metrics_stem=metrics_stem, bundle_rel=bundle_rel))
    return assigned


def bundle_run_directory(
    bundle_dir: str | Path,
    source_path: str | Path,
    *,
    relative_to: str | Path | None = None,
) -> Path:
    source = Path(source_path)
    if relative_to is None:
        return Path(bundle_dir) / safe_output_stem(source)
    relative = source.relative_to(relative_to).with_suffix("")
    return Path(bundle_dir).joinpath(*(safe_output_stem(Path(part)) for part in relative.parts))


def available_ram_bytes() -> int | None:
    """Best-effort free/available RAM (bytes). Prefer psutil; Windows ctypes fallback."""
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullAvailPhys)
    except Exception:
        pass
    return None


def estimate_stack_bytes(path: str | Path) -> int:
    """Conservative decoded-size estimate from on-disk size (no full load)."""
    p = Path(path)
    try:
        size = int(p.stat().st_size)
    except OSError:
        return _MIN_STACK_ESTIMATE_BYTES
    # Compressed TIFF/CZI can expand; use 4× file size with a floor.
    return max(_MIN_STACK_ESTIMATE_BYTES, size * 4)


def parse_workers_spec(value: str | int | None) -> WorkerSpec:
    """Parse CLI/API worker specification into int or ``'auto'``."""
    if value is None:
        return 1
    if isinstance(value, int):
        if value < 1:
            raise ValueError("workers must be >= 1")
        return int(value)
    text = str(value).strip().lower()
    if text in {"auto", "a"}:
        return "auto"
    n = int(text)
    if n < 1:
        raise ValueError("workers must be >= 1")
    return n


def resolve_worker_count(
    workers: WorkerSpec,
    *,
    n_jobs: int,
    stack_paths: Sequence[str | Path] | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    estimated_bytes_per_stack: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return (worker_count, governor_metadata).

    Formula for ``auto``:
      min(DEFAULT_MAX_WORKERS, cpu_count, n_jobs,
          floor(available_ram * RAM_BUDGET_FRACTION / est_bytes_per_stack))
      then max(1, that), and never exceed free-RAM headroom of MIN_FREE_RAM.
    """
    n_jobs = max(0, int(n_jobs))
    meta: dict[str, Any] = {
        "requested": workers if not isinstance(workers, int) else int(workers),
        "n_jobs": n_jobs,
        "max_workers_cap": int(max_workers),
        "cpu_count": os.cpu_count(),
        "available_ram_bytes": available_ram_bytes(),
    }
    if n_jobs <= 0:
        meta["resolved"] = 1
        return 1, meta

    if workers != "auto":
        n = max(1, min(int(workers), int(max_workers), n_jobs))
        meta["resolved"] = n
        meta["mode"] = "explicit"
        return n, meta

    cpu = max(1, int(os.cpu_count() or 1))
    n = min(int(max_workers), cpu, n_jobs)

    if estimated_bytes_per_stack is None and stack_paths:
        estimates = [estimate_stack_bytes(p) for p in stack_paths]
        estimated_bytes_per_stack = int(max(estimates)) if estimates else _MIN_STACK_ESTIMATE_BYTES
    if estimated_bytes_per_stack is None:
        estimated_bytes_per_stack = _MIN_STACK_ESTIMATE_BYTES
    estimated_bytes_per_stack = max(int(estimated_bytes_per_stack), _MIN_STACK_ESTIMATE_BYTES)
    meta["estimated_bytes_per_stack"] = estimated_bytes_per_stack

    avail = available_ram_bytes()
    if avail is not None and avail > 0:
        budget = int(avail * _RAM_BUDGET_FRACTION)
        # Keep a hard free-RAM floor when possible.
        budget = min(budget, max(0, avail - _MIN_FREE_RAM_BYTES))
        by_ram = max(1, budget // estimated_bytes_per_stack) if budget > 0 else 1
        meta["ram_budget_bytes"] = budget
        meta["workers_by_ram"] = by_ram
        n = min(n, by_ram)
    else:
        meta["ram_budget_bytes"] = None
        meta["workers_by_ram"] = None

    n = max(1, int(n))
    meta["resolved"] = n
    meta["mode"] = "auto"
    return n, meta


def _init_worker() -> None:
    """Cap BLAS/OpenMP threads inside each child to avoid nested oversubscription."""
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ.setdefault(key, "1")


def _roi_from_job(job: BatchStackJob) -> RectROI | None:
    if job.roi is None:
        return None
    xmin, xmax, ymin, ymax = job.roi
    return RectROI(xmin=int(xmin), xmax=int(xmax), ymin=int(ymin), ymax=int(ymax))


def _z_range_from_job(job: BatchStackJob) -> ZRange | None:
    if job.z_range is None:
        return None
    return ZRange(zmin=int(job.z_range[0]), zmax=int(job.z_range[1]))


def _voxel_override_from_job(job: BatchStackJob) -> VoxelSize | None:
    if job.voxel_x is None or job.voxel_y is None or job.voxel_z is None:
        return None
    return VoxelSize(x_um=float(job.voxel_x), y_um=float(job.voxel_y), z_um=float(job.voxel_z))


def process_batch_stack_job(job: BatchStackJob) -> BatchStackResult:
    """Top-level worker entry: load one stack, analyze, optional exports.

    Must remain a module-level function for Windows ``spawn`` pickling.
    """
    _init_worker()
    path = Path(job.source_path)
    source_sha256 = ""
    try:
        if job.compute_sha256:
            source_sha256 = file_sha256(path)
        stack = load_image_stack(path, voxel_override=_voxel_override_from_job(job))
        analysis = analyze_stack(
            stack.grayscale,
            thresholds=float(job.threshold),
            voxel_size=stack.voxel_size,
            roi=_roi_from_job(job),
            z_range=_z_range_from_job(job),
            profile=job.profile,
            prefer_opencv=bool(job.prefer_opencv),
            include_mesh=bool(job.include_mesh),
            source_path=stack.source_path,
            calibration=stack.calibration,
        )
        row = analysis_summary_row(
            analysis,
            source_path=str(stack.source_path),
            threshold=float(job.threshold),
            source_sha256=source_sha256,
            voxel_source=stack.voxel_source,
        )
        if job.metrics_dir:
            metrics_dir = Path(job.metrics_dir)
            metrics_dir.mkdir(parents=True, exist_ok=True)
            stem = job.metrics_stem or safe_output_stem(path)
            write_analysis_csv(analysis, metrics_dir / f"{stem}_metrics.csv")
        if job.bundle_dir:
            if job.bundle_rel:
                run_dir = Path(job.bundle_dir) / Path(job.bundle_rel)
            else:
                rel = Path(job.input_dir) if job.input_dir else None
                run_dir = bundle_run_directory(job.bundle_dir, path, relative_to=rel)
            run_dir.mkdir(parents=True, exist_ok=True)
            write_analysis_csv(analysis, run_dir / "metrics.csv")
            roi_payload = None
            if job.roi is not None:
                roi_payload = {
                    "xmin": int(job.roi[0]),
                    "xmax": int(job.roi[1]),
                    "ymin": int(job.roi[2]),
                    "ymax": int(job.roi[3]),
                }
            z_payload = None
            if job.z_range is not None:
                z_payload = {"zmin": int(job.z_range[0]), "zmax": int(job.z_range[1])}
            write_analysis_manifest_json(
                analysis_manifest(
                    analysis,
                    source_path=str(stack.source_path),
                    source_sha256=source_sha256,
                    threshold=float(job.threshold),
                    roi=roi_payload,
                    z_range=z_payload,
                    include_mesh=bool(job.include_mesh),
                    prefer_opencv=bool(job.prefer_opencv),
                    voxel_source=stack.voxel_source,
                ),
                run_dir / "manifest.json",
            )
            write_analysis_report_markdown(
                analysis,
                run_dir / "report.md",
                source_path=str(stack.source_path),
                source_sha256=source_sha256,
                threshold=float(job.threshold),
                roi=roi_payload,
                z_range=z_payload,
                include_mesh=bool(job.include_mesh),
                prefer_opencv=bool(job.prefer_opencv),
                voxel_source=stack.voxel_source,
            )
        return BatchStackResult(
            index=int(job.index),
            source_path=str(path),
            ok=True,
            summary_row=row,
            source_sha256=source_sha256,
            worker_pid=os.getpid(),
        )
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        return BatchStackResult(
            index=int(job.index),
            source_path=str(path),
            ok=False,
            summary_row=failed_analysis_summary_row(
                str(path), msg, source_sha256=source_sha256
            ),
            error_message=msg,
            source_sha256=source_sha256,
            worker_pid=os.getpid(),
        )


def run_batch_jobs(
    jobs: Sequence[BatchStackJob],
    *,
    workers: WorkerSpec = 1,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> BatchRunReport:
    """Run jobs with ``workers`` processes; results ordered by input index.

    ``workers=1`` never constructs a process pool (exact rollback semantics).
    """
    job_list = assign_unique_batch_outputs(list(jobs))
    paths = [j.source_path for j in job_list]
    n_workers, governor = resolve_worker_count(
        workers,
        n_jobs=len(job_list),
        stack_paths=paths,
        max_workers=max_workers,
    )
    requested = "auto" if workers == "auto" else str(int(workers))
    report = BatchRunReport(
        workers_requested=requested,
        workers_used=n_workers,
        governor=governor,
    )
    if not job_list:
        return report

    if n_workers == 1:
        results = [process_batch_stack_job(job) for job in job_list]
        results.sort(key=lambda r: r.index)
        report.results = results
        report.failures = sum(1 for r in results if not r.ok)
        return report

    # Multi-process: submit lightweight jobs only (paths, not arrays).
    results_by_index: dict[int, BatchStackResult] = {}
    try:
        # Reuse workers for the job set (Windows spawn import cost is high).
        # Each job loads its own stack; no shared StackCache/TrackingResultCache
        # across processes. Do not use max_tasks_per_child=1 (would re-import
        # the science stack per file and destroy throughput).
        with ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_init_worker,
        ) as pool:
            future_map = {pool.submit(process_batch_stack_job, job): job for job in job_list}
            try:
                for fut in as_completed(future_map):
                    job = future_map[fut]
                    try:
                        results_by_index[job.index] = fut.result()
                    except Exception as exc:
                        msg = f"worker_failure: {type(exc).__name__}: {exc}"
                        results_by_index[job.index] = BatchStackResult(
                            index=job.index,
                            source_path=job.source_path,
                            ok=False,
                            summary_row=failed_analysis_summary_row(
                                job.source_path, msg, source_sha256=""
                            ),
                            error_message=msg,
                            worker_pid=0,
                        )
            except BrokenProcessPool as exc:
                # Mark any unfinished jobs failed; completed ones are kept.
                msg = f"BrokenProcessPool: {exc}"
                for job in job_list:
                    if job.index not in results_by_index:
                        results_by_index[job.index] = BatchStackResult(
                            index=job.index,
                            source_path=job.source_path,
                            ok=False,
                            summary_row=failed_analysis_summary_row(
                                job.source_path, msg, source_sha256=""
                            ),
                            error_message=msg,
                            worker_pid=0,
                        )
    except Exception as exc:
        # Pool construction failure → fall back to serial for remaining work.
        governor["pool_error"] = f"{type(exc).__name__}: {exc}"
        governor["traceback"] = traceback.format_exc(limit=5)
        for job in job_list:
            if job.index not in results_by_index:
                results_by_index[job.index] = process_batch_stack_job(job)

    ordered = [results_by_index[i] for i in sorted(results_by_index)]
    report.results = ordered
    report.failures = sum(1 for r in ordered if not r.ok)
    return report


def scientific_summary_fields(row: dict[str, object]) -> dict[str, object]:
    """Subset of batch summary used for workers=1 vs N equivalence."""
    skip = {"error_message"}  # free text may differ on crashes only
    return {k: row.get(k) for k in row if k not in skip}
