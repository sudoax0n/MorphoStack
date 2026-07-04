"""MorphoStack command-line entry point."""

from __future__ import annotations

import argparse
import subprocess
import shutil
import sys
from importlib import import_module
from pathlib import Path

from morphostack import __version__
from morphostack.cli.system_info import collect_diagnostics, format_diagnostics
from morphostack.core import RectROI, VoxelSize, analyze_stack, load_image_stack, write_analysis_csv


CORE_DEPENDENCIES = ("numpy", "psutil")
ANALYSIS_DEPENDENCIES = (
    "cv2",
    "skimage",
    "scipy",
    "pandas",
    "tifffile",
    "shapely",
    "plotly",
    "networkx",
    "PIL",
)
API_DEPENDENCIES = ("fastapi", "uvicorn")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="morphostack",
        description="MorphoStack local morphometry toolkit.",
    )
    parser.add_argument("--version", action="version", version=f"MorphoStack {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    doctor = subparsers.add_parser("doctor", help="Inspect local runtime and dependencies.")
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Print diagnostics as JSON for bug reports.",
    )
    init = subparsers.add_parser(
        "init",
        help="Inspect this machine and optionally install optional MorphoStack dependencies.",
    )
    init.add_argument(
        "--yes",
        action="store_true",
        help="Install optional dependencies without prompting.",
    )
    init.add_argument(
        "--extras",
        default="analysis,api",
        help="Comma-separated optional dependency groups to install. Default: analysis,api.",
    )
    inspect = subparsers.add_parser(
        "inspect",
        help="Load an image stack and print basic metadata.",
    )
    inspect.add_argument("path", help="Path to a .tif, .tiff, or .czi file.")
    inspect.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    inspect.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    inspect.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    analyze = subparsers.add_parser(
        "analyze",
        help="Run headless threshold analysis on an image stack and write CSV metrics.",
    )
    analyze.add_argument("path", help="Path to a .tif, .tiff, or .czi file.")
    analyze.add_argument("--threshold", type=float, required=True, help="Global intensity threshold.")
    analyze.add_argument("--out", required=True, help="CSV output path.")
    analyze.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    analyze.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    analyze.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    analyze.add_argument("--roi", nargs=4, type=int, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    analyze.add_argument(
        "--fallback-contours",
        action="store_true",
        help="Use dependency-light rectangular fallback contours instead of OpenCV contours.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(as_json=args.json)

    if args.command == "init":
        return run_init(yes=args.yes, extras=args.extras)

    if args.command == "inspect":
        return run_inspect(
            path=args.path,
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
        )

    if args.command == "analyze":
        return run_analyze(
            path=args.path,
            threshold=args.threshold,
            out=args.out,
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
            roi=args.roi,
            prefer_opencv=not args.fallback_contours,
        )

    parser.print_help()
    return 0


def run_doctor(as_json: bool = False) -> int:
    diagnostics = collect_diagnostics()
    diagnostics["commands"] = {
        "git": shutil.which("git") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
    }
    diagnostics["dependencies"] = {
        "core": dependency_status(CORE_DEPENDENCIES),
        "analysis": dependency_status(ANALYSIS_DEPENDENCIES),
        "api": dependency_status(API_DEPENDENCIES),
    }

    print(format_diagnostics(diagnostics, as_json=as_json))
    return 0


def run_init(yes: bool = False, extras: str = "analysis,api") -> int:
    print("MorphoStack first-run setup")
    print("==========================")
    print("")
    run_doctor(as_json=False)
    print("")

    extras_list = [item.strip() for item in extras.split(",") if item.strip()]
    if not extras_list:
        print("No optional dependency groups selected.")
        return 0

    target = f".[{','.join(extras_list)}]"
    prompt = (
        "MorphoStack can install/update optional dependencies "
        f"({', '.join(extras_list)}) into the active Python environment. Continue? [y/N] "
    )
    if not yes:
        answer = input(prompt).strip().lower()
        if answer not in {"y", "yes"}:
            print("Skipped dependency installation.")
            return 0

    print(f"Installing {target} with {sys.executable} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", target],
        check=False,
    )
    if result.returncode != 0:
        print("Dependency installation failed.")
        return result.returncode

    print("MorphoStack setup completed.")
    return 0


def run_inspect(
    *,
    path: str,
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
) -> int:
    if any(value is not None for value in (voxel_x, voxel_y, voxel_z)):
        if None in (voxel_x, voxel_y, voxel_z):
            print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
            return 2
        voxel_override = VoxelSize(voxel_x, voxel_y, voxel_z)
    else:
        voxel_override = None

    try:
        stack = load_image_stack(path, voxel_override=voxel_override)
    except Exception as exc:
        print(f"Failed to inspect image stack: {exc}")
        return 1

    print("MorphoStack Stack Inspection")
    print("============================")
    print(f"Source: {stack.source_path}")
    print(f"Grayscale shape: {stack.grayscale.shape}")
    print(f"Color shape: {stack.color.shape}")
    print(
        "Voxel size: "
        f"x={stack.voxel_size.x_um:g} um, "
        f"y={stack.voxel_size.y_um:g} um, "
        f"z={stack.voxel_size.z_um:g} um"
    )
    return 0


def run_analyze(
    *,
    path: str,
    threshold: float,
    out: str,
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
    prefer_opencv: bool = True,
) -> int:
    voxel_override_result = build_voxel_override(voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2
    voxel_override = voxel_override_result

    rect_roi = RectROI(*roi) if roi is not None else None

    try:
        stack = load_image_stack(path, voxel_override=voxel_override)
        analysis = analyze_stack(
            stack.grayscale,
            thresholds=threshold,
            voxel_size=stack.voxel_size,
            roi=rect_roi,
            prefer_opencv=prefer_opencv,
        )
        output_path = Path(out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_analysis_csv(analysis, output_path)
    except Exception as exc:
        print(f"Failed to analyze image stack: {exc}")
        return 1

    print("MorphoStack Analysis Complete")
    print("=============================")
    print(f"Source: {stack.source_path}")
    print(f"Frames: {len(analysis.frames)}")
    print(f"Valid frames: {len(analysis.valid_frames)}")
    print(f"CSV: {output_path}")
    return 0


def build_voxel_override(
    voxel_x: float | None,
    voxel_y: float | None,
    voxel_z: float | None,
) -> VoxelSize | None | str:
    if any(value is not None for value in (voxel_x, voxel_y, voxel_z)):
        if None in (voxel_x, voxel_y, voxel_z):
            return "partial"
        return VoxelSize(voxel_x, voxel_y, voxel_z)
    return None


def dependency_status(names: tuple[str, ...]) -> dict[str, bool]:
    return {name: import_available(name) for name in names}


def import_available(name: str) -> bool:
    try:
        import_module(name)
    except Exception:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
