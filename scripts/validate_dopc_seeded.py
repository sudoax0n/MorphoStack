#!/usr/bin/env python3
"""Re-run DOPC validation with an explicit object seed on the largest GUV."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MORPHO = REPO_ROOT / ".venv" / "Scripts" / "morphostack.exe"
DOPC_SOURCE = Path(r"D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif")
OUT_DIR = REPO_ROOT / "validation" / "runs" / "dopc-seeded-object"

# From LimeSeg vs threshold report on middle frame (largest component centroid).
SEED_FRAME = 13
SEED_X = 209.0
SEED_Y = 419.0
SEED_RADIUS = 12.0
THRESHOLD = 127.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args()

    if not MORPHO.exists():
        print(f"morphostack CLI not found: {MORPHO}", file=sys.stderr)
        return 1
    if not DOPC_SOURCE.exists():
        print(f"DOPC source missing: {DOPC_SOURCE}", file=sys.stderr)
        return 1

    bundle = OUT_DIR / "seeded_guv"
    command = [
        str(MORPHO),
        "analyze",
        str(DOPC_SOURCE),
        "--threshold",
        str(args.threshold),
        "--profile",
        "vesicle",
        "--bundle-dir",
        str(bundle),
        "--report",
        "--mesh",
        "--mesh-export",
        "mesh.obj",
        "--seed-x",
        str(SEED_X),
        "--seed-y",
        str(SEED_Y),
        "--seed-frame",
        str(SEED_FRAME),
        "--seed-radius",
        str(SEED_RADIUS),
    ]
    print("Running:", " ".join(command))
    subprocess.run(command, check=True, cwd=REPO_ROOT)

    manifest_candidates = sorted(bundle.glob("*/manifest.json"))
    if not manifest_candidates:
        raise FileNotFoundError(f"No manifest.json found under {bundle}")
    manifest_path = manifest_candidates[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mean_area = manifest["summary"]["metrics"]["area_um2"]["mean"]

    readme = OUT_DIR / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# DOPC Movie 1 — Seeded GUV Validation",
                "",
                f"- Source: `{DOPC_SOURCE}`",
                f"- Threshold: `{args.threshold}`",
                f"- Seed frame: `{SEED_FRAME}`",
                f"- Seed center: `({SEED_X}, {SEED_Y})`, radius `{SEED_RADIUS}` px",
                "",
                f"- Mean area: `{mean_area}` µm² (default voxel — not biological units)",
                "",
                "## Notes",
                "",
                "- Seed placed on the largest thresholded component in the middle Z slice.",
                "- Compare against the unseeded smoke test in `validation/runs/dopc-smoke-test/`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"DOPC seeded validation complete: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())