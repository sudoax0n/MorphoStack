#!/usr/bin/env python3
"""Freeze Scout 01 real-data tracking baselines with process instrumentation.

Produces JSON manifests for:
  - validation seed R12 (seed-frame only)
  - R20 target 65 and reverse 50
  - bridge seed B R60 target 65 (historical; may fail-close on current code)
  - bridge R55 at same XY target 65 (current unsafe acceptance fixture)
  - optional 40-Z band (z40–79) for the 10.9 s reference

Does not change scientific thresholds. Instrumentation is enabled only for
manifest collection; a short off/on parity check is recorded when possible.

Usage:
  .venv\\Scripts\\python scripts/freeze_tracking_baseline.py
  .venv\\Scripts\\python scripts/freeze_tracking_baseline.py --out .agent-runs/tracking-recovery-20260712/packet-01
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morphostack.core.io import file_sha256, load_image_stack
from morphostack.core.seeded_vesicle import (
    enable_tracking_instrumentation,
    get_tracking_instrumentation,
    reset_tracking_instrumentation,
    scientific_result_fingerprint,
    segment_slice_seeded,
    track_seeded_vesicle_stack,
)
from morphostack.core.stack_cache import (
    TrackingResultCache,
    make_tracking_cache_key,
    tracking_key_revision,
)
from morphostack.api.tracking_jobs import TrackingJobService

DEFAULT_CZI = Path(r"D:\shuchita di data\1644_z stack.czi")
EXPECTED_SHA = "e9319b31b969c062cddabc0188d176f99fcee553119d6abb811866cd1858aa2d"

# Scout 01 seed identities
VAL_X, VAL_Y, VAL_Z = 337.0, 319.0, 56
BRIDGE_X, BRIDGE_Y, BRIDGE_Z = 340.0, 350.0, 56

# Recorded Scout 01 walls (do not claim improvements).
SCOUT01_REFERENCE = {
    "r20_target_65_wall_s": 4.07,
    "r20_reverse_50_wall_s": 5.66,
    "r20_band_40z_wall_s": 10.9,
    "bridge_r60_target_65_wall_s": 11.4,
}


def _qc_brief(res) -> dict[str, Any] | None:
    if res.qc is None:
        return None
    q = res.qc
    return {
        "circularity": float(q.circularity),
        "eta": float(q.eta),
        "edge_support": float(q.edge_support),
        "n_dt_markers": int(q.n_dt_markers),
        "merge_suspect": bool(q.merge_suspect),
        "strong_two_circle": bool(q.strong_two_circle),
        "cheap": bool(q.cheap),
    }


def _frame_table(results, z0: int, z1: int) -> list[dict[str, Any]]:
    rows = []
    for z in range(z0, z1 + 1):
        r = results[z]
        rows.append(
            {
                "z": z,
                "ok": bool(r.ok),
                "method": r.method,
                "area_px": float(r.area_px),
                "center": [float(r.center_xy[0]), float(r.center_xy[1])],
                "merge_suspect": bool(r.merge_suspect),
                "mask_fp": scientific_result_fingerprint(r)["mask_fp"],
                "qc": _qc_brief(r),
            }
        )
    return rows


def _run_walk(
    stack,
    *,
    seed_x: float,
    seed_y: float,
    seed_frame: int,
    seed_radius: float,
    target: int,
    label: str,
) -> dict[str, Any]:
    enable_tracking_instrumentation(True)
    reset_tracking_instrumentation()
    t0 = time.perf_counter()
    results = track_seeded_vesicle_stack(
        stack,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_frame=seed_frame,
        seed_radius=seed_radius,
        target_frame=int(target),
    )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    instr = get_tracking_instrumentation()
    lo, hi = min(seed_frame, target), max(seed_frame, target)
    return {
        "label": label,
        "seed": {
            "x": float(seed_x),
            "y": float(seed_y),
            "frame": int(seed_frame),
            "radius_px": float(seed_radius),
            "roi": None,
        },
        "target_z": int(target),
        "wall_ms": wall_ms,
        "wall_s": wall_ms / 1000.0,
        "segment_calls": instr["segment_calls"],
        "stage_summary": instr["stage_summary"],
        "decision_count": instr["decision_count"],
        "frame_count": instr["frame_count"],
        "event_kinds": sorted({e.get("kind") for e in instr["events"] if e.get("kind")}),
        "decisions": instr["decisions"],
        "frames": instr["frames"],
        "frame_table": _frame_table(results, lo, hi),
        "scientific_fingerprints": [
            scientific_result_fingerprint(results[z]) for z in range(lo, hi + 1)
        ],
    }


def _run_seed_only(stack, *, radius: float, warm: bool) -> dict[str, Any]:
    enable_tracking_instrumentation(True)
    reset_tracking_instrumentation()
    if warm:
        # one warm pass without collecting
        enable_tracking_instrumentation(False)
        segment_slice_seeded(
            stack[VAL_Z], seed_x=VAL_X, seed_y=VAL_Y, seed_radius=radius, refine=True
        )
        enable_tracking_instrumentation(True)
        reset_tracking_instrumentation()
    t0 = time.perf_counter()
    res = segment_slice_seeded(
        stack[VAL_Z], seed_x=VAL_X, seed_y=VAL_Y, seed_radius=radius, refine=True
    )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    instr = get_tracking_instrumentation()
    return {
        "label": f"seed_R{int(radius)}_{'warm' if warm else 'cold'}",
        "seed": {
            "x": VAL_X,
            "y": VAL_Y,
            "frame": VAL_Z,
            "radius_px": float(radius),
            "roi": None,
        },
        "wall_ms": wall_ms,
        "ok": bool(res.ok),
        "method": res.method,
        "area_px": float(res.area_px),
        "merge_suspect": bool(res.merge_suspect),
        "qc": _qc_brief(res),
        "fingerprint": scientific_result_fingerprint(res),
        "stage_summary": instr["stage_summary"],
        "segment_calls": instr["segment_calls"],
    }


def _parity_check(stack) -> dict[str, Any]:
    """Instrumentation-off vs on scientific fingerprints for R20 → 58 (short walk).

    Warm the process first: first-touch skimage/MorphGAC can be non-deterministic
    relative to later warm runs (Scout 01 cold vs warm). Compare warm-off vs warm-on.
    """
    enable_tracking_instrumentation(False)
    for _ in range(2):
        track_seeded_vesicle_stack(
            stack,
            seed_x=VAL_X,
            seed_y=VAL_Y,
            seed_frame=VAL_Z,
            seed_radius=20.0,
            target_frame=58,
        )

    enable_tracking_instrumentation(False)
    off = track_seeded_vesicle_stack(
        stack,
        seed_x=VAL_X,
        seed_y=VAL_Y,
        seed_frame=VAL_Z,
        seed_radius=20.0,
        target_frame=58,
    )
    off_fps = [scientific_result_fingerprint(off[z]) for z in range(VAL_Z, 59)]

    # Warm-off self-check (documents residual non-determinism if any).
    off2 = track_seeded_vesicle_stack(
        stack,
        seed_x=VAL_X,
        seed_y=VAL_Y,
        seed_frame=VAL_Z,
        seed_radius=20.0,
        target_frame=58,
    )
    off2_fps = [scientific_result_fingerprint(off2[z]) for z in range(VAL_Z, 59)]
    warm_self_match = off_fps == off2_fps

    enable_tracking_instrumentation(True)
    reset_tracking_instrumentation()
    on = track_seeded_vesicle_stack(
        stack,
        seed_x=VAL_X,
        seed_y=VAL_Y,
        seed_frame=VAL_Z,
        seed_radius=20.0,
        target_frame=58,
    )
    on_fps = [scientific_result_fingerprint(on[z]) for z in range(VAL_Z, 59)]
    match = off_fps == on_fps
    return {
        "case": "R20_target_58_parity",
        "match": match,
        "warm_off_self_match": warm_self_match,
        "n_frames": len(off_fps),
        "off_methods": [f["method"] for f in off_fps],
        "on_methods": [f["method"] for f in on_fps],
    }


def _synthetic_ring_stack(n: int = 12) -> np.ndarray:
    """Deterministic hollow-ring stack for reproducible overhead measurement."""
    h = w = 64
    frames = []
    for z in range(n):
        cx, cy = 28.0 + z, 32.0
        yy, xx = np.ogrid[:h, :w]
        d = (xx - cx) ** 2 + (yy - cy) ** 2
        frame = np.zeros((h, w), dtype=np.float64)
        frame[(d >= 10.0**2) & (d <= 14.0**2)] = 1.0
        frames.append(frame)
    return np.stack(frames, axis=0)


def _overhead_check(_stack) -> dict[str, Any]:
    """Warm whole-track instrumentation overhead (hard ≤5% budget).

    Measured on a deterministic synthetic whole-track. Real CZI walls vary by
    path (gap/retry mix) so they cannot isolate instrumentation cost; scientific
    parity on real CZI is checked separately. The 5% limit is not optional.
    """
    synth = _synthetic_ring_stack(12)
    seed_kw = dict(seed_x=28.0, seed_y=32.0, seed_frame=0, seed_radius=14.0, target_frame=11)

    enable_tracking_instrumentation(False)
    for _ in range(3):
        track_seeded_vesicle_stack(synth, **seed_kw)

    n = 10
    offs: list[float] = []
    ons: list[float] = []
    pair_fracs: list[float] = []
    for _ in range(n):
        enable_tracking_instrumentation(False)
        t0 = time.perf_counter()
        track_seeded_vesicle_stack(synth, **seed_kw)
        off_ms_i = (time.perf_counter() - t0) * 1000.0
        offs.append(off_ms_i)

        enable_tracking_instrumentation(True)
        reset_tracking_instrumentation()
        t0 = time.perf_counter()
        track_seeded_vesicle_stack(synth, **seed_kw)
        on_ms_i = (time.perf_counter() - t0) * 1000.0
        ons.append(on_ms_i)
        pair_fracs.append((on_ms_i - off_ms_i) / max(off_ms_i, 1e-6))

    off_ms = float(np.median(offs))
    on_ms = float(np.median(ons))
    overhead = float(np.median(pair_fracs))
    return {
        "case": "synthetic_warm_whole_track_12z_overhead",
        "fixture": "deterministic_ring_stack_n12",
        "off_median_ms": off_ms,
        "on_median_ms": on_ms,
        "off_mean_ms": float(np.mean(offs)),
        "on_mean_ms": float(np.mean(ons)),
        "off_samples_ms": offs,
        "on_samples_ms": ons,
        "pair_overhead_fracs": pair_fracs,
        "overhead_frac": overhead,
        "budget_frac": 0.05,
        "pass": bool(overhead <= 0.05),
        "note": (
            "Hard ≤5% gate on deterministic synthetic whole-track; "
            "real CZI walls are recorded separately and are path-noisy."
        ),
    }


def _job_probe(stack) -> dict[str, Any]:
    enable_tracking_instrumentation(True)
    reset_tracking_instrumentation()
    cache = TrackingResultCache()
    service = TrackingJobService(result_cache=cache, max_active_jobs=1)
    key = make_tracking_cache_key(
        stack_identity=f"file:{DEFAULT_CZI}|freeze|R20",
        seed_x=VAL_X,
        seed_y=VAL_Y,
        seed_frame=VAL_Z,
        seed_radius=20.0,
        gray_shape=tuple(int(v) for v in stack.shape),
        roi=None,
        z_range=None,
        profile="vesicle",
    )
    t0 = time.perf_counter()
    snap = service.start(
        key=key,
        stack=stack,
        seed_x=VAL_X,
        seed_y=VAL_Y,
        seed_frame=VAL_Z,
        seed_radius=20.0,
        target_z=57,
        direction_priority=1,
    )
    final = service.wait(snap.job_id, timeout=300.0)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    instr = get_tracking_instrumentation()
    kinds = sorted({e.get("kind") for e in instr["events"] if e.get("kind")})
    service.shutdown(timeout=30.0)
    return {
        "label": "job_R20_target_57",
        "wall_ms": wall_ms,
        "state": final.state,
        "available_exact_frames": list(final.available_exact_frames),
        "key_revision": tracking_key_revision(key),
        "event_kinds": kinds,
        "track_invocations": service.track_invocations,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--czi",
        type=Path,
        default=DEFAULT_CZI,
        help="Path to 1644_z stack.czi",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / ".agent-runs" / "tracking-recovery-20260712" / "packet-01",
        help="Output directory for frozen manifests",
    )
    ap.add_argument(
        "--skip-band",
        action="store_true",
        help="Skip the 40-Z band timing (faster)",
    )
    ap.add_argument(
        "--skip-bridge",
        action="store_true",
        help="Skip bridge seed B walk",
    )
    args = ap.parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    czi: Path = args.czi
    if not czi.is_file():
        print(f"ERROR: CZI not found: {czi}", file=sys.stderr)
        return 2

    sha = file_sha256(czi)
    if sha != EXPECTED_SHA:
        print(
            f"ERROR: CZI SHA mismatch\n  got  {sha}\n  want {EXPECTED_SHA}",
            file=sys.stderr,
        )
        return 3

    print(f"Loading {czi} …")
    t_load = time.perf_counter()
    image = load_image_stack(czi)
    load_ms = (time.perf_counter() - t_load) * 1000.0
    stack = np.asarray(image.grayscale)
    voxel = image.voxel_size

    fixture = {
        "path": str(czi),
        "sha256": sha,
        "shape": list(stack.shape),
        "dtype": str(stack.dtype),
        "voxel": {
            "x_um": float(voxel.x_um),
            "y_um": float(voxel.y_um),
            "z_um": float(voxel.z_um),
        },
        "load_ms": load_ms,
        "roi": None,
        "profile": "vesicle",
        "algorithm_version": "1",
        "tracking_mode": "seeded_exact",
    }

    print("Parity check (R20→58) …")
    parity = _parity_check(stack)
    print(f"  match={parity['match']}")

    print("Warm whole-track overhead check (deterministic synthetic 12-Z) …")
    overhead = _overhead_check(stack)
    print(
        f"  off_med={overhead['off_median_ms']:.1f}ms on_med={overhead['on_median_ms']:.1f}ms "
        f"overhead={overhead['overhead_frac']:.2%} pass={overhead['pass']} "
        f"(hard ≤{overhead['budget_frac']:.0%})"
    )

    cases: dict[str, Any] = {}
    print("Seed R12 cold/warm …")
    cases["seed_R12_cold"] = _run_seed_only(stack, radius=12.0, warm=False)
    cases["seed_R12_warm"] = _run_seed_only(stack, radius=12.0, warm=True)

    print("R20 → 65 …")
    cases["r20_target_65"] = _run_walk(
        stack,
        seed_x=VAL_X,
        seed_y=VAL_Y,
        seed_frame=VAL_Z,
        seed_radius=20.0,
        target=65,
        label="r20_target_65",
    )
    print(f"  wall={cases['r20_target_65']['wall_s']:.3f}s (scout ref 4.07s)")

    print("R20 → 50 reverse …")
    cases["r20_reverse_50"] = _run_walk(
        stack,
        seed_x=VAL_X,
        seed_y=VAL_Y,
        seed_frame=VAL_Z,
        seed_radius=20.0,
        target=50,
        label="r20_reverse_50",
    )
    print(f"  wall={cases['r20_reverse_50']['wall_s']:.3f}s (scout ref 5.66s)")

    if not args.skip_bridge:
        print("Bridge B R60 → 65 (historical; may fail-close) …")
        cases["bridge_r60_target_65"] = _run_walk(
            stack,
            seed_x=BRIDGE_X,
            seed_y=BRIDGE_Y,
            seed_frame=BRIDGE_Z,
            seed_radius=60.0,
            target=65,
            label="bridge_r60_target_65",
        )
        print(
            f"  wall={cases['bridge_r60_target_65']['wall_s']:.3f}s (scout ref ~11.4s)"
        )
        # Current unsafe acceptance: same bridge XY with R=55 accepts multi-body split.
        print("Bridge R55 → 65 (current unsafe acceptance fixture) …")
        cases["bridge_r55_target_65"] = _run_walk(
            stack,
            seed_x=BRIDGE_X,
            seed_y=BRIDGE_Y,
            seed_frame=BRIDGE_Z,
            seed_radius=55.0,
            target=65,
            label="bridge_r55_target_65",
        )
        seed_row = cases["bridge_r55_target_65"]["frame_table"][0]
        print(
            f"  wall={cases['bridge_r55_target_65']['wall_s']:.3f}s "
            f"seed_ok={seed_row['ok']} method={seed_row['method']} "
            f"area={seed_row['area_px']:.1f} merge_suspect={seed_row['merge_suspect']}"
        )

    if not args.skip_band:
        print("R20 full band z40–79 …")
        enable_tracking_instrumentation(True)
        reset_tracking_instrumentation()
        z0, z1 = 40, 80
        sub = stack[z0:z1]
        seed_local = VAL_Z - z0
        t0 = time.perf_counter()
        results = track_seeded_vesicle_stack(
            sub,
            seed_x=VAL_X,
            seed_y=VAL_Y,
            seed_frame=seed_local,
            seed_radius=20.0,
            target_frame=None,
        )
        wall_ms = (time.perf_counter() - t0) * 1000.0
        instr = get_tracking_instrumentation()
        ok_n = sum(1 for r in results if r.ok)
        cases["r20_band_40z"] = {
            "label": "r20_band_40z",
            "z_range_global": [z0, z1 - 1],
            "seed": {
                "x": VAL_X,
                "y": VAL_Y,
                "frame_global": VAL_Z,
                "frame_local": seed_local,
                "radius_px": 20.0,
                "roi": None,
            },
            "wall_ms": wall_ms,
            "wall_s": wall_ms / 1000.0,
            "ok_frames": ok_n,
            "n_frames": len(results),
            "segment_calls": instr["segment_calls"],
            "stage_summary": instr["stage_summary"],
            "decision_count": instr["decision_count"],
            "frame_table": [
                {
                    "z_global": z0 + i,
                    "ok": bool(r.ok),
                    "method": r.method,
                    "area_px": float(r.area_px),
                    "merge_suspect": bool(r.merge_suspect),
                }
                for i, r in enumerate(results)
            ],
        }
        print(f"  wall={cases['r20_band_40z']['wall_s']:.3f}s (scout ref 10.9s)")

    print("Job service probe …")
    cases["job_probe"] = _job_probe(stack)

    enable_tracking_instrumentation(False)

    manifest = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "packet": "tracking-recovery-20260712/packet-01",
        "status": "ok" if parity["match"] else "parity_failed",
        "fixture": fixture,
        "scout01_reference_walls_s": SCOUT01_REFERENCE,
        "parity": parity,
        "overhead": overhead,
        "cases": cases,
        "notes": [
            "Walls re-measure current code; Scout 01 numbers are reference only.",
            "Do not claim speed improvements from this freeze alone.",
            "Instrumentation is process-local and off by default in production.",
        ],
    }

    out_path = out_dir / "frozen_baseline_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")

    bridge_r55 = cases.get("bridge_r55_target_65")
    bridge_r55_seed = None
    if isinstance(bridge_r55, dict) and bridge_r55.get("frame_table"):
        bridge_r55_seed = bridge_r55["frame_table"][0]

    # Compact benchmark summary for packet handoff.
    bench = {
        "generated_at": manifest["generated_at"],
        "fixture_sha256": sha,
        "parity_match": parity["match"],
        "overhead_frac": overhead["overhead_frac"],
        "overhead_pass": overhead["pass"],
        "overhead_budget_frac": 0.05,
        "overhead_case": overhead["case"],
        "walls_s": {
            k: cases[k]["wall_s"]
            for k in cases
            if isinstance(cases[k], dict) and "wall_s" in cases[k]
        },
        "scout01_reference_walls_s": SCOUT01_REFERENCE,
        "seed_R12_ok": cases["seed_R12_warm"]["ok"],
        "seed_R12_method": cases["seed_R12_warm"]["method"],
        "bridge_r60_seed_ok": (
            cases["bridge_r60_target_65"]["frame_table"][0]["ok"]
            if "bridge_r60_target_65" in cases and cases["bridge_r60_target_65"].get("frame_table")
            else None
        ),
        "bridge_r55_seed_ok": bridge_r55_seed["ok"] if bridge_r55_seed else None,
        "bridge_r55_seed_method": bridge_r55_seed["method"] if bridge_r55_seed else None,
        "bridge_r55_seed_area_px": bridge_r55_seed["area_px"] if bridge_r55_seed else None,
        "bridge_r55_seed_merge_suspect": (
            bridge_r55_seed["merge_suspect"] if bridge_r55_seed else None
        ),
    }
    bench_path = out_dir / "benchmark.json"
    bench_path.write_text(json.dumps(bench, indent=2), encoding="utf-8")
    print(f"Wrote {bench_path}")

    if not parity["match"]:
        print("ERROR: instrumentation-off vs on scientific parity failed", file=sys.stderr)
        return 4
    if not overhead["pass"]:
        print(
            f"ERROR: overhead {overhead['overhead_frac']:.2%} exceeds hard 5% budget "
            f"(off_med={overhead['off_median_ms']:.1f}ms on_med={overhead['on_median_ms']:.1f}ms)",
            file=sys.stderr,
        )
        return 5
    if not args.skip_bridge and bridge_r55_seed is not None and not bridge_r55_seed["ok"]:
        print(
            "ERROR: bridge_r55_target_65 seed did not accept "
            "(Packet 02 needs a current unsafe acceptance fixture)",
            file=sys.stderr,
        )
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
