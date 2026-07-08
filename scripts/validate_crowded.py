#!/usr/bin/env python3
"""Create crowded-stack validation runs with two distinct object seeds."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MORPHO = REPO_ROOT / ".venv" / "Scripts" / "morphostack.exe"
RUNS_ROOT = REPO_ROOT / "validation" / "runs"


@dataclass(frozen=True)
class CrowdedCase:
    slug: str
    name: str
    source: Path
    threshold: float
    profile: str
    frame_index: int
    seeds: tuple[tuple[str, float, float], ...]
    z_range: tuple[int, int] | None = None

    @property
    def out_dir(self) -> Path:
        return RUNS_ROOT / self.slug


VALIDATION_CASES: tuple[CrowdedCase, ...] = (
    CrowdedCase(
        slug="czi-1650-crowded-two-objects",
        name="Crowded vesicle validation (CZI 1650)",
        source=Path(r"C:\Users\systemm\Downloads\1650_z stack.czi"),
        threshold=190.0,
        profile="vesicle",
        frame_index=105,
        z_range=(90, 120),
        seeds=(
            ("object_a_left", 359.97, 516.78),
            ("object_b_right", 479.06, 94.07),
        ),
    ),
    CrowdedCase(
        slug="czi-1644-crowded-two-objects",
        name="Crowded vesicle validation (CZI 1644)",
        source=Path(r"C:\Users\systemm\Downloads\1644_z stack.czi"),
        threshold=484.0,
        profile="vesicle",
        frame_index=56,
        z_range=(40, 80),
        seeds=(
            ("object_a_center", 337.0, 319.0),
            ("object_b_corner", 637.0, 170.0),
        ),
    ),
    CrowdedCase(
        slug="rbc-image46-crowded-two-objects",
        name="Crowded RBC validation (Image 46)",
        source=Path(r"D:\rbc data pranay\Image 46.lsm"),
        threshold=43.0,
        profile="rbc",
        frame_index=10,
        z_range=(0, 28),
        seeds=(
            ("object_a_lower", 290.61, 731.79),
            ("object_b_upper", 166.58, 304.13),
        ),
    ),
    CrowdedCase(
        slug="rbc-image32-crowded-two-objects",
        name="Crowded RBC validation (Image 32)",
        source=Path(r"D:\rbc data pranay\Image 32.lsm"),
        threshold=49.0,
        profile="rbc",
        frame_index=16,
        z_range=(0, 28),
        seeds=(
            ("object_a_center", 293.0, 510.0),
            ("object_b_right", 556.0, 345.0),
        ),
    ),
)


def run_case(case: CrowdedCase) -> None:
    if not case.source.exists():
        raise FileNotFoundError(f"Validation source missing: {case.source}")

    out_dir = case.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    notes_path = out_dir / "README.md"
    metrics_summary: list[dict[str, object]] = []

    for label, seed_x, seed_y in case.seeds:
        bundle = out_dir / label
        command = [
            str(MORPHO),
            "analyze",
            str(case.source),
            "--threshold",
            str(case.threshold),
            "--profile",
            case.profile,
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
            str(case.frame_index),
            "--seed-radius",
            "12",
        ]
        if case.z_range is not None:
            command.extend(["--z-range", str(case.z_range[0]), str(case.z_range[1])])
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
                "seed": (seed_x, seed_y, case.frame_index),
                "mean_area_um2": mean_area,
                "manifest": str(manifest_path),
                "metrics": str(metrics_path),
                "mesh": str(bundle_subdir / "mesh.obj"),
            }
        )

    areas = [float(item["mean_area_um2"]) for item in metrics_summary]
    distinct = abs(max(areas) - min(areas)) > 1.0
    notes = [
        f"# {case.name}",
        "",
        f"- Source: `{case.source}`",
        f"- Profile: `{case.profile}`",
        f"- Threshold: `{case.threshold}`",
        f"- Seed frame: `{case.frame_index}`",
        f"- Z range: `{case.z_range if case.z_range else 'full stack'}`",
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
            f"Distinct object metrics: `{distinct}` (mean area delta {abs(max(areas) - min(areas)):.2f} um², ratio {max(areas)/max(min(areas),1e-9):.2f})",
            "",
        ]
    )
    notes_path.write_text("\n".join(notes), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="SLUG",
        help="Run only these validation slugs (e.g. czi-1644-crowded-two-objects).",
    )
    args = parser.parse_args()

    if not MORPHO.exists():
        print(f"morphostack CLI not found: {MORPHO}", file=sys.stderr)
        return 1

    selected = VALIDATION_CASES
    if args.only:
        wanted = set(args.only)
        selected = tuple(case for case in VALIDATION_CASES if case.slug in wanted)
        missing = wanted - {case.slug for case in selected}
        if missing:
            print(f"Unknown validation slug(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

    for case in selected:
        run_case(case)
        print(f"Completed: {case.slug}")

    print("Crowded validation runs complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())