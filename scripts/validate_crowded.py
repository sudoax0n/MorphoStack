#!/usr/bin/env python3
"""Create crowded-stack validation runs with two distinct object seeds."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MORPHO = REPO_ROOT / ".venv" / "Scripts" / "morphostack.exe"

VESICLE_SOURCE = Path(r"C:\Users\systemm\Downloads\1650_z stack.czi")
RBC_SOURCE = Path(r"D:\rbc data pranay\Image 46.lsm")

VESICLE_RUN = REPO_ROOT / "validation" / "runs" / "czi-1650-crowded-two-objects"
RBC_RUN = REPO_ROOT / "validation" / "runs" / "rbc-image46-crowded-two-objects"


def run_case(
    *,
    name: str,
    source: Path,
    out_dir: Path,
    threshold: float,
    profile: str,
    frame_index: int,
    seeds: list[tuple[str, float, float]],
    z_range: tuple[int, int] | None = None,
) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Validation source missing: {source}")

    out_dir.mkdir(parents=True, exist_ok=True)
    notes_path = out_dir / "README.md"
    metrics_summary: list[dict[str, object]] = []

    for label, seed_x, seed_y in seeds:
        bundle = out_dir / label
        command = [
            str(MORPHO),
            "analyze",
            str(source),
            "--threshold",
            str(threshold),
            "--profile",
            profile,
            "--bundle-dir",
            str(bundle),
            "--report",
            "--mesh",
            "--mesh-export",
            "mesh.obj",
            "--seed-x",
            str(seed_x),
            "--seed-y",
            str(seed_y),
            "--seed-frame",
            str(frame_index),
            "--seed-radius",
            "12",
        ]
        if z_range is not None:
            command.extend(["--z-range", str(z_range[0]), str(z_range[1])])
        print("Running:", " ".join(command))
        subprocess.run(command, check=True, cwd=REPO_ROOT)

        manifest_candidates = sorted(bundle.glob("*/manifest.json"))
        if not manifest_candidates:
            raise FileNotFoundError(f"No manifest.json found under {bundle}")
        manifest_path = manifest_candidates[0]
        bundle_subdir = manifest_path.parent
        metrics_path = bundle_subdir / "metrics.csv"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mean_area = manifest["summary"]["metrics"]["area_um2"]["mean"]
        metrics_summary.append(
            {
                "label": label,
                "seed": (seed_x, seed_y, frame_index),
                "mean_area_um2": mean_area,
                "manifest": str(manifest_path),
                "metrics": str(metrics_path),
                "mesh": str(bundle_subdir / "mesh.obj"),
            }
        )

    areas = [float(item["mean_area_um2"]) for item in metrics_summary]
    distinct = max(areas) / max(min(areas), 1e-9) > 1.2
    notes = [
        f"# {name}",
        "",
        f"- Source: `{source}`",
        f"- Profile: `{profile}`",
        f"- Threshold: `{threshold}`",
        f"- Seed frame: `{frame_index}`",
        f"- Z range: `{z_range if z_range else 'full stack'}`",
        "",
        "## Selected objects",
        "",
    ]
    for item in metrics_summary:
        notes.append(
            f"- **{item['label']}** seed `{item['seed']}` → mean area `{item['mean_area_um2']}` µm²"
        )
    notes.extend(
        [
            "",
            "## Limitations",
            "",
            "- Tracking can switch objects when vesicles/RBCs touch or move farther than the max tracking distance.",
            "- Default-voxel LSM runs are exploratory; physical units require verified calibration.",
            "- Mesh exports are for inspection only when voxel calibration is missing or default.",
            "",
            f"Distinct object metrics: `{distinct}` (ratio {max(areas)/max(min(areas),1e-9):.2f})",
            "",
        ]
    )
    notes_path.write_text("\n".join(notes), encoding="utf-8")


def main() -> int:
    if not MORPHO.exists():
        print(f"morphostack CLI not found: {MORPHO}", file=sys.stderr)
        return 1

    run_case(
        name="Crowded vesicle validation (CZI 1650)",
        source=VESICLE_SOURCE,
        out_dir=VESICLE_RUN,
        threshold=190.0,
        profile="vesicle",
        frame_index=105,
        z_range=(90, 120),
        seeds=[
            ("object_a_left", 359.97, 516.78),
            ("object_b_right", 479.06, 94.07),
        ],
    )
    run_case(
        name="Crowded RBC validation (Image 46)",
        source=RBC_SOURCE,
        out_dir=RBC_RUN,
        threshold=43.0,
        profile="rbc",
        frame_index=10,
        z_range=(0, 28),
        seeds=[
            ("object_a_lower", 290.61, 731.79),
            ("object_b_upper", 166.58, 304.13),
        ],
    )
    print("Crowded validation runs complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())