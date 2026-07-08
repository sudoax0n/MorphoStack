#!/usr/bin/env python3
"""Save segmentation preview PNGs into validation run folders from manifest metadata."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from morphostack.core.io import load_image_stack
from morphostack.core.pipeline import ObjectSeed, ZRange
from morphostack.core.segmentation import apply_z_range
from morphostack.core.preview import render_segmentation_preview_png


@dataclass(frozen=True)
class PreviewCase:
    manifest_path: Path
    source_path: Path
    threshold: float
    profile: str
    frame_index: int
    object_seed: ObjectSeed | None
    z_range: ZRange | None
    prefer_opencv: bool


def parse_z_range(payload: object) -> ZRange | None:
    if not isinstance(payload, dict):
        return None
    if "zmin" not in payload or "zmax" not in payload:
        return None
    return ZRange(zmin=int(payload["zmin"]), zmax=int(payload["zmax"]))


def parse_object_seed(payload: object) -> ObjectSeed | None:
    if not isinstance(payload, dict):
        return None
    return ObjectSeed(
        x=float(payload["x"]),
        y=float(payload["y"]),
        frame_index=int(payload.get("frame_index", 0)),
        radius=float(payload.get("radius", 10.0)),
        max_tracking_dist_um=(
            float(payload["max_tracking_dist_um"])
            if payload.get("max_tracking_dist_um") is not None
            else None
        ),
    )


def case_from_manifest(manifest_path: Path) -> PreviewCase | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_raw = manifest.get("source_path")
    if not isinstance(source_raw, str) or source_raw in ("synthetic-sphere", "synthetic-ellipsoid", ""):
        return None
    source_path = Path(source_raw)
    if not source_path.exists():
        print(f"Skipping missing source for {manifest_path}: {source_path}")
        return None

    threshold = float(manifest.get("threshold", 100))
    profile = str(manifest.get("profile", "vesicle"))
    object_seed = parse_object_seed(manifest.get("object_seed"))
    z_range = parse_z_range(manifest.get("z_range"))
    frame_index = object_seed.frame_index if object_seed is not None else 0
    return PreviewCase(
        manifest_path=manifest_path,
        source_path=source_path,
        threshold=threshold,
        profile=profile,
        frame_index=frame_index,
        object_seed=object_seed,
        z_range=z_range,
        prefer_opencv=bool(manifest.get("prefer_opencv", True)),
    )


def discover_manifests(runs_dir: Path) -> list[Path]:
    return sorted(path for path in runs_dir.rglob("manifest.json") if path.is_file())


def local_frame_index(case: PreviewCase, global_frame_count: int) -> int:
    if case.z_range is None:
        return max(0, min(case.frame_index, global_frame_count - 1))
    trimmed_count = case.z_range.zmax - case.z_range.zmin + 1
    local = case.frame_index - case.z_range.zmin
    return max(0, min(local, trimmed_count - 1))


def capture_preview(case: PreviewCase, *, force: bool = False) -> Path | None:
    out_path = case.manifest_path.parent / "preview-seed-frame.png"
    if out_path.exists() and not force:
        return out_path

    stack = load_image_stack(case.source_path)
    grayscale = stack.grayscale
    if case.z_range is not None:
        grayscale = apply_z_range(
            grayscale,
            zmin=case.z_range.zmin,
            zmax=case.z_range.zmax,
        )
    frame_index = local_frame_index(case, stack.grayscale.shape[0])

    preview = render_segmentation_preview_png(
        grayscale,
        frame_index=frame_index,
        threshold=case.threshold,
        prefer_opencv=case.prefer_opencv,
        object_seed=case.object_seed,
    )
    out_path.write_bytes(preview.png_bytes)
    return out_path


def write_index(runs_dir: Path, captured: list[Path]) -> Path:
    index_path = runs_dir / "preview-index.json"
    payload = {
        "count": len(captured),
        "previews": [str(path.relative_to(runs_dir)) for path in captured],
    }
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default=str(PROJECT_ROOT / "validation" / "runs"),
        help="Root validation runs directory.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing preview PNGs.")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.exists():
        print(f"Validation runs directory not found: {runs_dir}")
        return 1

    captured: list[Path] = []
    skipped = 0
    for manifest_path in discover_manifests(runs_dir):
        case = case_from_manifest(manifest_path)
        if case is None:
            skipped += 1
            continue
        try:
            out_path = capture_preview(case, force=args.force)
        except Exception as exc:
            print(f"Failed {manifest_path}: {exc}")
            continue
        if out_path is not None:
            captured.append(out_path)
            print(f"Wrote {out_path}")

    index_path = write_index(runs_dir, captured)
    print(f"Preview index: {index_path}")
    print(f"Captured {len(captured)} previews ({skipped} manifests skipped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())