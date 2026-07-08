#!/usr/bin/env python3
"""Compare threshold (vesicle) and LimeSeg profiles on the same stack and seed."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from morphostack.core.export import analysis_run_warnings, analysis_summary
from morphostack.core.io import load_image_stack
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import ObjectSeed, analyze_stack


@dataclass(frozen=True)
class ProfileSnapshot:
    profile: str
    valid_frame_count: int
    valid_fraction: float
    mean_area_um2: float | None
    mesh_volume_um3: float | None
    mesh_surface_area_um2: float | None
    mesh_sphericity: float | None
    warning_codes: tuple[str, ...]


def build_sphere_stack() -> np.ndarray:
    shape = (10, 40, 40)
    stack = np.zeros(shape, dtype=np.uint8)
    cz, cy, cx = 5.0, 20.0, 20.0
    for z in range(shape[0]):
        for y in range(shape[1]):
            for x in range(shape[2]):
                dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2)
                if dist < 6.0:
                    stack[z, y, x] = 255
    return stack


def snapshot(analysis, *, voxel_source: str = "override") -> ProfileSnapshot:
    summary = analysis_summary(analysis)
    metrics = summary.get("metrics", {})
    area = metrics.get("area_um2", {}) if isinstance(metrics, dict) else {}
    mesh = analysis.mesh
    warnings = analysis_run_warnings(analysis, voxel_source=voxel_source)
    return ProfileSnapshot(
        profile=analysis.profile,
        valid_frame_count=int(summary["valid_frame_count"]),
        valid_fraction=float(summary["valid_fraction"]),
        mean_area_um2=float(area["mean"]) if isinstance(area, dict) and "mean" in area else None,
        mesh_volume_um3=mesh.volume_um3 if mesh else None,
        mesh_surface_area_um2=mesh.surface_area_um2 if mesh else None,
        mesh_sphericity=mesh.sphericity if mesh else None,
        warning_codes=tuple(str(item["code"]) for item in warnings),
    )


def compare_on_array(
    stack: np.ndarray,
    *,
    threshold: float,
    voxel: VoxelSize,
    seed: ObjectSeed,
    threshold_profile: str = "vesicle",
    prefer_opencv: bool = False,
    voxel_source: str = "override",
    z_range=None,
) -> tuple[ProfileSnapshot, ProfileSnapshot]:
    threshold_analysis = analyze_stack(
        stack,
        thresholds=threshold,
        voxel_size=voxel,
        profile=threshold_profile,
        include_mesh=True,
        prefer_opencv=prefer_opencv,
        object_seed=seed,
        z_range=z_range,
    )
    limeseg_analysis = analyze_stack(
        stack,
        thresholds=threshold,
        voxel_size=voxel,
        profile="limeseg",
        include_mesh=True,
        prefer_opencv=prefer_opencv,
        object_seed=seed,
        z_range=z_range,
    )
    return (
        snapshot(threshold_analysis, voxel_source=voxel_source),
        snapshot(limeseg_analysis, voxel_source=voxel_source),
    )


def pct_delta(baseline: float | None, candidate: float | None) -> str:
    if baseline is None or candidate is None or baseline == 0:
        return "n/a"
    return f"{100.0 * (candidate - baseline) / baseline:+.1f}%"


def report_markdown(
    *,
    title: str,
    source_label: str,
    threshold: float,
    seed: ObjectSeed,
    vesicle: ProfileSnapshot,
    limeseg: ProfileSnapshot,
    threshold_profile: str = "vesicle",
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Source: `{source_label}`",
        f"- Threshold: `{threshold}`",
        f"- Seed: frame `{seed.frame_index}`, center `({seed.x:.2f}, {seed.y:.2f})`, radius `{seed.radius}` px",
        "",
        "## Summary",
        "",
        f"| Metric | Threshold ({threshold_profile}) | LimeSeg | Delta |",
        "| --- | ---: | ---: | ---: |",
        f"| Valid frames | {vesicle.valid_frame_count} | {limeseg.valid_frame_count} | — |",
        f"| Valid fraction | {vesicle.valid_fraction:.3f} | {limeseg.valid_fraction:.3f} | — |",
        f"| Mean area (µm²) | {vesicle.mean_area_um2} | {limeseg.mean_area_um2} | {pct_delta(vesicle.mean_area_um2, limeseg.mean_area_um2)} |",
        f"| Mesh volume (µm³) | {vesicle.mesh_volume_um3} | {limeseg.mesh_volume_um3} | {pct_delta(vesicle.mesh_volume_um3, limeseg.mesh_volume_um3)} |",
        f"| Mesh surface (µm²) | {vesicle.mesh_surface_area_um2} | {limeseg.mesh_surface_area_um2} | {pct_delta(vesicle.mesh_surface_area_um2, limeseg.mesh_surface_area_um2)} |",
        f"| Mesh sphericity | {vesicle.mesh_sphericity} | {limeseg.mesh_sphericity} | {pct_delta(vesicle.mesh_sphericity, limeseg.mesh_sphericity)} |",
        "",
        "## Warnings",
        "",
        f"- Threshold: `{', '.join(vesicle.warning_codes) or 'none'}`",
        f"- LimeSeg: `{', '.join(limeseg.warning_codes) or 'none'}`",
        "",
        "## Interpretation",
        "",
        "- Large mesh-volume deltas on crowded or touching data usually mean LimeSeg or tracking picked a different object region.",
        "- On synthetic spheres, profiles should agree within a few percent when the seed sits on the object center.",
        "- Treat LimeSeg as experimental until side-by-side previews look correct on your dataset.",
        "",
    ]
    return "\n".join(lines)


def write_case(
    *,
    slug: str,
    title: str,
    source_label: str,
    threshold: float,
    seed: ObjectSeed,
    vesicle: ProfileSnapshot,
    limeseg: ProfileSnapshot,
    reports_dir: Path,
    threshold_profile: str = "vesicle",
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"limeseg-vs-threshold-{slug}.md"
    summary_path = reports_dir / f"limeseg-vs-threshold-{slug}.json"
    report_path.write_text(
        report_markdown(
            title=title,
            source_label=source_label,
            threshold=threshold,
            seed=seed,
            vesicle=vesicle,
            limeseg=limeseg,
            threshold_profile=threshold_profile,
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "title": title,
                "source": source_label,
                "threshold": threshold,
                "seed": {
                    "x": seed.x,
                    "y": seed.y,
                    "frame_index": seed.frame_index,
                    "radius": seed.radius,
                },
                "vesicle": asdict(vesicle),
                "limeseg": asdict(limeseg),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report_path


def run_synthetic(reports_dir: Path) -> Path:
    stack = build_sphere_stack()
    seed = ObjectSeed(x=20.0, y=20.0, frame_index=5, radius=6.0)
    vesicle, limeseg = compare_on_array(stack, threshold=100.0, voxel=VoxelSize(1.0, 1.0, 1.0), seed=seed)
    return write_case(
        slug="synthetic-sphere",
        title="LimeSeg vs Threshold — Synthetic Sphere",
        source_label="in-memory synthetic sphere (r=6 µm)",
        threshold=100.0,
        seed=seed,
        vesicle=vesicle,
        limeseg=limeseg,
        reports_dir=reports_dir,
    )


def run_crowded_rbc(reports_dir: Path, source: Path) -> Path | None:
    if not source.exists():
        print(f"Skipping crowded RBC case; source missing: {source}")
        return None
    from morphostack.core.pipeline import ZRange

    stack = load_image_stack(source)
    seed = ObjectSeed(x=290.61, y=731.79, frame_index=10, radius=12.0)
    z_range = ZRange(zmin=0, zmax=28)
    vesicle, limeseg = compare_on_array(
        stack.grayscale,
        threshold=43.0,
        voxel=stack.voxel_size,
        seed=seed,
        threshold_profile="rbc",
        prefer_opencv=True,
        voxel_source=stack.voxel_source,
        z_range=z_range,
    )
    return write_case(
        slug="rbc-image46-object-a",
        title="LimeSeg vs Threshold — Crowded RBC Image 46 (object A)",
        source_label=str(source),
        threshold=43.0,
        seed=seed,
        vesicle=vesicle,
        limeseg=limeseg,
        reports_dir=reports_dir,
        threshold_profile="rbc",
    )


def run_crowded_vesicle(reports_dir: Path, source: Path) -> Path | None:
    if not source.exists():
        print(f"Skipping crowded vesicle case; source missing: {source}")
        return None
    from morphostack.core.pipeline import ZRange

    stack = load_image_stack(source)
    seed = ObjectSeed(x=359.97, y=516.78, frame_index=105, radius=12.0)
    z_range = ZRange(zmin=90, zmax=120)
    vesicle, limeseg = compare_on_array(
        stack.grayscale,
        threshold=190.0,
        voxel=stack.voxel_size,
        seed=seed,
        prefer_opencv=True,
        voxel_source=stack.voxel_source,
        z_range=z_range,
    )
    return write_case(
        slug="czi-1650-object-a",
        title="LimeSeg vs Threshold — Crowded CZI 1650 (object A)",
        source_label=str(source),
        threshold=190.0,
        seed=seed,
        vesicle=vesicle,
        limeseg=limeseg,
        reports_dir=reports_dir,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports-dir",
        default=str(PROJECT_ROOT / "validation" / "reports"),
        help="Directory for markdown/json comparison reports.",
    )
    parser.add_argument("--skip-crowded", action="store_true", help="Only run synthetic comparison.")
    args = parser.parse_args()
    reports_dir = Path(args.reports_dir)

    paths = [run_synthetic(reports_dir)]
    if not args.skip_crowded:
        for runner, source in (
            (run_crowded_vesicle, Path(r"C:\Users\systemm\Downloads\1650_z stack.czi")),
            (run_crowded_rbc, Path(r"D:\rbc data pranay\Image 46.lsm")),
        ):
            report = runner(reports_dir, source)
            if report is not None:
                paths.append(report)

    print("LimeSeg vs threshold comparison complete:")
    for path in paths:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())