"""MorphoStack command-line entry point."""

from __future__ import annotations

import argparse
import os
import subprocess
import shutil
import sys
import time
import webbrowser
from importlib import import_module
from pathlib import Path

from morphostack import __version__
from morphostack.cli.system_info import collect_diagnostics, format_diagnostics
from morphostack.core import (
    PROFILE_CHOICES,
    ProjectSettings,
    RectROI,
    SweepSettings,
    VoxelSize,
    analyze_stack,
    analysis_manifest,
    analysis_run_warnings,
    analysis_summary,
    analysis_summary_row,
    apply_rect_roi,
    best_sweep_result,
    failed_analysis_summary_row,
    compare_metric_csv,
    format_validation_report,
    load_image_stack,
    load_project_settings,
    suggest_threshold,
    threshold_sweep,
    threshold_values,
    write_analysis_csv,
    write_analysis_manifest_json,
    write_analysis_report_markdown,
    write_batch_summary_csv,
    write_project_settings,
    write_threshold_sweep_csv,
)


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
API_DEPENDENCIES = ("fastapi", "python_multipart", "uvicorn")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_APP_DIR = PROJECT_ROOT / "apps" / "web"


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
    init.add_argument(
        "--web",
        action="store_true",
        help="Also install browser UI dependencies with npm install in apps/web.",
    )
    project = subparsers.add_parser("project", help="Create and inspect MorphoStack project settings.")
    project_subparsers = project.add_subparsers(dest="project_command")
    project_init = project_subparsers.add_parser("init", help="Write a reusable project settings JSON file.")
    project_init.add_argument("--out", default="morphostack.project.json", help="Project settings output path.")
    project_init.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="vesicle",
        help="Default analysis profile. Default: vesicle.",
    )
    project_init.add_argument("--threshold", type=float, help="Default analysis threshold.")
    project_init.add_argument("--voxel-x", type=float, help="Default X voxel size in micrometers.")
    project_init.add_argument("--voxel-y", type=float, help="Default Y voxel size in micrometers.")
    project_init.add_argument("--voxel-z", type=float, help="Default Z voxel size in micrometers.")
    project_init.add_argument("--roi", nargs=4, type=int, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    project_init.add_argument("--mesh", action="store_true", help="Default to 3D mesh measurements.")
    project_init.add_argument(
        "--fallback-contours",
        action="store_true",
        help="Default to dependency-light fallback contours.",
    )
    project_init.add_argument("--sweep-start", type=float, help="Default threshold sweep start.")
    project_init.add_argument("--sweep-stop", type=float, help="Default threshold sweep stop.")
    project_init.add_argument("--sweep-step", type=float, help="Default threshold sweep step.")
    serve = subparsers.add_parser("serve", help="Run the local FastAPI backend.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1.")
    serve.add_argument("--port", default=8000, type=int, help="Bind port. Default: 8000.")
    dev = subparsers.add_parser("dev", help="Run the local backend and browser UI together.")
    dev.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1.")
    dev.add_argument("--api-port", default=8000, type=int, help="Backend port. Default: 8000.")
    dev.add_argument("--web-port", default=5173, type=int, help="Frontend port. Default: 5173.")
    dev.add_argument("--no-open", action="store_true", help="Do not open the browser.")
    dev.add_argument("--check", action="store_true", help="Validate dev prerequisites and exit.")
    inspect = subparsers.add_parser(
        "inspect",
        help="Load an image stack and print basic metadata.",
    )
    inspect.add_argument("path", help="Path to a .tif, .tiff, or .czi file.")
    inspect.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    inspect.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    inspect.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    inspect.add_argument("--project", help="Project settings JSON path.")
    threshold = subparsers.add_parser(
        "threshold",
        help="Suggest an intensity threshold for an image stack.",
    )
    threshold.add_argument("path", help="Path to a .tif, .tiff, or .czi file.")
    threshold.add_argument(
        "--method",
        choices=("auto", "otsu", "percentile"),
        default="auto",
        help="Threshold suggestion method. Default: auto.",
    )
    threshold.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    threshold.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    threshold.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    threshold.add_argument("--roi", nargs=4, type=int, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    threshold.add_argument("--project", help="Project settings JSON path.")
    sweep = subparsers.add_parser(
        "sweep",
        help="Run the analysis pipeline across a range of thresholds and write summary CSV rows.",
    )
    sweep.add_argument("path", help="Path to a .tif, .tiff, or .czi file.")
    sweep.add_argument("--start", type=float, help="First threshold to analyze.")
    sweep.add_argument("--stop", type=float, help="Last threshold to analyze.")
    sweep.add_argument("--step", type=float, help="Threshold increment.")
    sweep.add_argument("--out", required=True, help="Sweep summary CSV output path.")
    sweep.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default=None,
        help="Analysis profile. Default: project profile or vesicle.",
    )
    sweep.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    sweep.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    sweep.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    sweep.add_argument("--roi", nargs=4, type=int, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    sweep.add_argument("--project", help="Project settings JSON path.")
    sweep.add_argument(
        "--mesh",
        dest="include_mesh",
        action="store_true",
        default=None,
        help="Compute 3D surface area/volume for each threshold.",
    )
    sweep.add_argument("--no-mesh", dest="include_mesh", action="store_false", help="Do not compute 3D mesh measurements.")
    sweep.add_argument(
        "--fallback-contours",
        dest="fallback_contours",
        action="store_true",
        default=None,
        help="Use dependency-light rectangular fallback contours instead of OpenCV contours.",
    )
    sweep.add_argument("--opencv-contours", dest="fallback_contours", action="store_false", help="Use OpenCV contours when available.")
    analyze = subparsers.add_parser(
        "analyze",
        help="Run headless threshold analysis on an image stack and write CSV metrics.",
    )
    analyze.add_argument("path", help="Path to a .tif, .tiff, or .czi file.")
    analyze.add_argument("--threshold", type=float, help="Global intensity threshold.")
    analyze.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default=None,
        help="Analysis profile. Default: project profile or vesicle.",
    )
    analyze.add_argument("--out", help="CSV output path.")
    analyze.add_argument(
        "--bundle-dir",
        help="Directory where a run bundle folder should be created. Writes metrics.csv, manifest.json, and report.md.",
    )
    analyze.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    analyze.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    analyze.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    analyze.add_argument("--roi", nargs=4, type=int, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    analyze.add_argument("--manifest", help="Manifest JSON output path. Default: <csv>.manifest.json.")
    analyze.add_argument("--no-manifest", action="store_true", help="Do not write a manifest JSON sidecar.")
    analyze.add_argument(
        "--report",
        nargs="?",
        const="",
        help="Write a Markdown analysis report. Default path: <csv>.report.md.",
    )
    analyze.add_argument("--project", help="Project settings JSON path.")
    analyze.add_argument(
        "--mesh",
        dest="include_mesh",
        action="store_true",
        default=None,
        help="Assemble contour masks and compute 3D surface area/volume.",
    )
    analyze.add_argument("--no-mesh", dest="include_mesh", action="store_false", help="Do not compute 3D mesh measurements.")
    analyze.add_argument(
        "--fallback-contours",
        dest="fallback_contours",
        action="store_true",
        default=None,
        help="Use dependency-light rectangular fallback contours instead of OpenCV contours.",
    )
    analyze.add_argument("--opencv-contours", dest="fallback_contours", action="store_false", help="Use OpenCV contours when available.")
    batch = subparsers.add_parser(
        "batch",
        help="Analyze every supported stack in a directory and write one summary CSV.",
    )
    batch.add_argument("directory", help="Directory containing .tif, .tiff, or .czi stacks.")
    batch.add_argument("--threshold", type=float, help="Global intensity threshold.")
    batch.add_argument("--out", required=True, help="Batch summary CSV output path.")
    batch.add_argument("--recursive", action="store_true", help="Search subdirectories too.")
    batch.add_argument("--metrics-dir", help="Optional directory for per-stack frame CSV files.")
    batch.add_argument(
        "--bundle-dir",
        help="Optional directory for per-stack run bundles with metrics.csv, manifest.json, and report.md.",
    )
    batch.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default=None,
        help="Analysis profile. Default: project profile or vesicle.",
    )
    batch.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    batch.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    batch.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    batch.add_argument("--roi", nargs=4, type=int, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    batch.add_argument("--project", help="Project settings JSON path.")
    batch.add_argument(
        "--mesh",
        dest="include_mesh",
        action="store_true",
        default=None,
        help="Compute 3D surface area/volume for each stack.",
    )
    batch.add_argument("--no-mesh", dest="include_mesh", action="store_false", help="Do not compute 3D mesh measurements.")
    batch.add_argument(
        "--fallback-contours",
        dest="fallback_contours",
        action="store_true",
        default=None,
        help="Use dependency-light rectangular fallback contours instead of OpenCV contours.",
    )
    batch.add_argument("--opencv-contours", dest="fallback_contours", action="store_false", help="Use OpenCV contours when available.")
    validate = subparsers.add_parser(
        "validate",
        help="Compare two MorphoStack CSV exports within a numeric tolerance.",
    )
    validate.add_argument("expected", help="Reference CSV path.")
    validate.add_argument("actual", help="CSV path to validate.")
    validate.add_argument(
        "--tolerance",
        type=float,
        default=1e-6,
        help="Absolute numeric tolerance. Default: 1e-6.",
    )
    validate.add_argument(
        "--columns",
        nargs="+",
        help="Optional metric columns to compare. Default: all shared numeric columns.",
    )
    validate.add_argument(
        "--key-column",
        default="frame_index",
        help="Column used to match rows. Default: frame_index.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(as_json=args.json)

    if args.command == "init":
        return run_init(yes=args.yes, extras=args.extras, web=args.web)

    if args.command == "project":
        if args.project_command == "init":
            return run_project_init(
                out=args.out,
                profile=args.profile,
                threshold=args.threshold,
                voxel_x=args.voxel_x,
                voxel_y=args.voxel_y,
                voxel_z=args.voxel_z,
                roi=args.roi,
                include_mesh=args.mesh,
                prefer_opencv=not args.fallback_contours,
                sweep_start=args.sweep_start,
                sweep_stop=args.sweep_stop,
                sweep_step=args.sweep_step,
            )
        print("Specify a project command, for example: morphostack project init")
        return 2

    if args.command == "inspect":
        return run_inspect(
            path=args.path,
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
            project=args.project,
        )

    if args.command == "serve":
        return run_serve(host=args.host, port=args.port)

    if args.command == "threshold":
        return run_threshold(
            path=args.path,
            method=args.method,
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
            roi=args.roi,
            project=args.project,
        )

    if args.command == "dev":
        return run_dev(
            host=args.host,
            api_port=args.api_port,
            web_port=args.web_port,
            open_browser=not args.no_open,
            check_only=args.check,
        )

    if args.command == "analyze":
        return run_analyze(
            path=args.path,
            threshold=args.threshold,
            profile=args.profile,
            out=args.out,
            bundle_dir=args.bundle_dir,
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
            roi=args.roi,
            manifest=args.manifest,
            report=args.report,
            write_manifest=not args.no_manifest,
            prefer_opencv=prefer_opencv_from_flag(args.fallback_contours),
            include_mesh=args.include_mesh,
            project=args.project,
        )

    if args.command == "sweep":
        return run_sweep(
            path=args.path,
            start=args.start,
            stop=args.stop,
            step=args.step,
            out=args.out,
            profile=args.profile,
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
            roi=args.roi,
            prefer_opencv=prefer_opencv_from_flag(args.fallback_contours),
            include_mesh=args.include_mesh,
            project=args.project,
        )

    if args.command == "batch":
        return run_batch(
            directory=args.directory,
            threshold=args.threshold,
            out=args.out,
            recursive=args.recursive,
            metrics_dir=args.metrics_dir,
            bundle_dir=args.bundle_dir,
            profile=args.profile,
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
            roi=args.roi,
            prefer_opencv=prefer_opencv_from_flag(args.fallback_contours),
            include_mesh=args.include_mesh,
            project=args.project,
        )

    if args.command == "validate":
        return run_validate(
            expected=args.expected,
            actual=args.actual,
            tolerance=args.tolerance,
            columns=args.columns,
            key_column=args.key_column,
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


def run_init(yes: bool = False, extras: str = "analysis,api", web: bool = False) -> int:
    print("MorphoStack first-run setup")
    print("==========================")
    print("")
    run_doctor(as_json=False)
    print("")

    extras_list = [item.strip() for item in extras.split(",") if item.strip()]
    if extras_list:
        target = f".[{','.join(extras_list)}]"
        prompt = (
            "MorphoStack can install/update optional dependencies "
            f"({', '.join(extras_list)}) into the active Python environment. Continue? [y/N] "
        )
        if yes or confirm(prompt):
            print(f"Installing {target} with {sys.executable} ...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", target],
                check=False,
            )
            if result.returncode != 0:
                print("Dependency installation failed.")
                return result.returncode
        else:
            print("Skipped Python dependency installation.")
    else:
        print("No optional Python dependency groups selected.")

    if web:
        prompt = "MorphoStack can install/update browser UI dependencies with npm install. Continue? [y/N] "
        if yes or confirm(prompt):
            result_code = install_web_dependencies()
            if result_code != 0:
                return result_code
        else:
            print("Skipped web dependency installation.")

    print("MorphoStack setup completed.")
    return 0


def confirm(prompt: str) -> bool:
    return input(prompt).strip().lower() in {"y", "yes"}


def install_web_dependencies() -> int:
    npm_command = shutil.which("npm")
    if npm_command is None:
        print("npm is required to install browser UI dependencies.")
        return 1
    if not WEB_APP_DIR.exists():
        print(f"Web app directory was not found: {WEB_APP_DIR}")
        return 1

    print(f"Installing browser UI dependencies in {WEB_APP_DIR} ...")
    result = subprocess.run([npm_command, "install"], cwd=WEB_APP_DIR, check=False)
    if result.returncode != 0:
        print("Web dependency installation failed.")
        return result.returncode
    return 0


def run_inspect(
    *,
    path: str,
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    project: str | None = None,
) -> int:
    project_settings = load_project_for_command(project)
    if isinstance(project_settings, int):
        return project_settings
    voxel_override_result = resolve_voxel_override(project_settings, voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2
    voxel_override = voxel_override_result

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
    print(f"Voxel source: {stack.voxel_source}")
    return 0


def run_project_init(
    *,
    out: str,
    profile: str,
    threshold: float | None = None,
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
    include_mesh: bool = False,
    prefer_opencv: bool = True,
    sweep_start: float | None = None,
    sweep_stop: float | None = None,
    sweep_step: float | None = None,
) -> int:
    voxel_override_result = build_voxel_override(voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2

    sweep_values = (sweep_start, sweep_stop, sweep_step)
    if any(value is not None for value in sweep_values) and any(value is None for value in sweep_values):
        print("Sweep defaults require --sweep-start, --sweep-stop, and --sweep-step together.")
        return 2

    try:
        settings = ProjectSettings(
            profile=profile,
            threshold=threshold,
            voxel_size=voxel_override_result if isinstance(voxel_override_result, VoxelSize) else None,
            roi=RectROI(*roi) if roi is not None else None,
            include_mesh=include_mesh,
            prefer_opencv=prefer_opencv,
            sweep=SweepSettings(start=sweep_start, stop=sweep_stop, step=sweep_step),
        )
        output_path = Path(out)
        write_project_settings(settings, output_path)
    except Exception as exc:
        print(f"Failed to write project settings: {exc}")
        return 1

    print("MorphoStack Project Created")
    print("===========================")
    print(f"Project: {output_path}")
    print(f"Profile: {profile}")
    if threshold is not None:
        print(f"Threshold: {threshold:g}")
    return 0


def run_analyze(
    *,
    path: str,
    threshold: float | None,
    out: str | None,
    bundle_dir: str | None = None,
    profile: str | None = None,
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
    manifest: str | None = None,
    report: str | None = None,
    write_manifest: bool = True,
    prefer_opencv: bool | None = None,
    include_mesh: bool | None = None,
    project: str | None = None,
) -> int:
    project_settings = load_project_for_command(project)
    if isinstance(project_settings, int):
        return project_settings
    resolved_threshold = resolve_threshold(project_settings, threshold)
    if resolved_threshold is None:
        print("Analysis threshold is required. Pass --threshold or set threshold in --project.")
        return 2
    if out is None and bundle_dir is None:
        print("Analysis output is required. Pass --out or --bundle-dir.")
        return 2
    resolved_profile = resolve_profile(project_settings, profile)
    resolved_mesh = resolve_bool(include_mesh, project_settings.include_mesh, False)
    resolved_prefer_opencv = resolve_bool(prefer_opencv, project_settings.prefer_opencv, True)
    voxel_override_result = resolve_voxel_override(project_settings, voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2
    voxel_override = voxel_override_result

    rect_roi = resolve_roi(project_settings, roi)
    run_bundle_dir = None

    try:
        stack = load_image_stack(path, voxel_override=voxel_override)
        analysis = analyze_stack(
            stack.grayscale,
            thresholds=resolved_threshold,
            voxel_size=stack.voxel_size,
            roi=rect_roi,
            profile=resolved_profile,
            prefer_opencv=resolved_prefer_opencv,
            include_mesh=resolved_mesh,
        )
        warnings = analysis_run_warnings(analysis, voxel_source=stack.voxel_source)
        summary = analysis_summary(analysis)
        run_bundle_dir = bundle_run_directory(bundle_dir, stack.source_path) if bundle_dir else None
        output_path = Path(out) if out is not None else run_bundle_dir / "metrics.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_analysis_csv(analysis, output_path)
        manifest_path = None
        if write_manifest:
            if manifest:
                manifest_path = Path(manifest)
            elif run_bundle_dir is not None:
                manifest_path = run_bundle_dir / "manifest.json"
            else:
                manifest_path = output_path.with_suffix(f"{output_path.suffix}.manifest.json")
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            write_analysis_manifest_json(
                analysis_manifest(
                    analysis,
                    source_path=str(stack.source_path),
                    threshold=resolved_threshold,
                    roi=roi_to_payload(rect_roi),
                    include_mesh=resolved_mesh,
                    prefer_opencv=resolved_prefer_opencv,
                    voxel_source=stack.voxel_source,
                ),
                manifest_path,
            )
        report_path = None
        if report is not None or run_bundle_dir is not None:
            if report:
                report_path = Path(report)
            elif run_bundle_dir is not None:
                report_path = run_bundle_dir / "report.md"
            else:
                report_path = output_path.with_suffix(f"{output_path.suffix}.report.md")
            write_analysis_report_markdown(
                analysis,
                report_path,
                source_path=str(stack.source_path),
                threshold=resolved_threshold,
                roi=roi_to_payload(rect_roi),
                include_mesh=resolved_mesh,
                prefer_opencv=resolved_prefer_opencv,
                voxel_source=stack.voxel_source,
            )
    except Exception as exc:
        print(f"Failed to analyze image stack: {exc}")
        return 1

    print("MorphoStack Analysis Complete")
    print("=============================")
    print(f"Source: {stack.source_path}")
    print(f"Profile: {analysis.profile}")
    print(f"Frames: {len(analysis.frames)}")
    print(f"Valid frames: {len(analysis.valid_frames)}")
    print(f"Voxel source: {stack.voxel_source}")
    metric_summary = summary["metrics"]
    if isinstance(metric_summary, dict) and metric_summary:
        area_summary = metric_summary.get("area_um2")
        circularity_summary = metric_summary.get("circularity")
        if isinstance(area_summary, dict):
            print(f"Mean area: {area_summary['mean']:g} um^2")
        if isinstance(circularity_summary, dict):
            print(f"Mean circularity: {circularity_summary['mean']:g}")
    for warning in warnings:
        print(f"Warning [{warning['code']}]: {warning['message']}")
    if analysis.mesh:
        print(f"3D surface area: {analysis.mesh.surface_area_um2:g} um^2")
        print(f"3D volume: {analysis.mesh.volume_um3:g} um^3")
        print(f"3D equivalent sphere diameter: {analysis.mesh.equivalent_sphere_diameter_um:g} um")
        print(f"3D sphericity: {analysis.mesh.sphericity:g}")
    print(f"CSV: {output_path}")
    if run_bundle_dir:
        print(f"Bundle: {run_bundle_dir}")
    if manifest_path:
        print(f"Manifest: {manifest_path}")
    if report_path:
        print(f"Report: {report_path}")
    return 0


def run_threshold(
    *,
    path: str,
    method: str = "auto",
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
    project: str | None = None,
) -> int:
    project_settings = load_project_for_command(project)
    if isinstance(project_settings, int):
        return project_settings
    voxel_override_result = resolve_voxel_override(project_settings, voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2
    voxel_override = voxel_override_result
    rect_roi = resolve_roi(project_settings, roi)

    try:
        stack = load_image_stack(path, voxel_override=voxel_override)
        grayscale = stack.grayscale
        if rect_roi is not None:
            grayscale = apply_rect_roi(
                grayscale,
                xmin=rect_roi.xmin,
                xmax=rect_roi.xmax,
                ymin=rect_roi.ymin,
                ymax=rect_roi.ymax,
            )
        threshold, used_method = suggest_threshold(grayscale, method=method)
    except Exception as exc:
        print(f"Failed to suggest threshold: {exc}")
        return 1

    print("MorphoStack Threshold Suggestion")
    print("================================")
    print(f"Source: {stack.source_path}")
    print(f"Method: {used_method}")
    print(f"Threshold: {threshold:g}")
    return 0


def run_sweep(
    *,
    path: str,
    start: float | None,
    stop: float | None,
    step: float | None,
    out: str,
    profile: str | None = None,
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
    prefer_opencv: bool | None = None,
    include_mesh: bool | None = None,
    project: str | None = None,
) -> int:
    project_settings = load_project_for_command(project)
    if isinstance(project_settings, int):
        return project_settings
    start = start if start is not None else project_settings.sweep.start
    stop = stop if stop is not None else project_settings.sweep.stop
    step = step if step is not None else project_settings.sweep.step
    if None in (start, stop, step):
        print("Sweep requires --start, --stop, and --step or sweep defaults in --project.")
        return 2
    resolved_profile = resolve_profile(project_settings, profile)
    resolved_mesh = resolve_bool(include_mesh, project_settings.include_mesh, False)
    resolved_prefer_opencv = resolve_bool(prefer_opencv, project_settings.prefer_opencv, True)
    voxel_override_result = resolve_voxel_override(project_settings, voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2
    voxel_override = voxel_override_result
    rect_roi = resolve_roi(project_settings, roi)

    try:
        thresholds = threshold_values(start, stop, step)
        stack = load_image_stack(path, voxel_override=voxel_override)
        results = threshold_sweep(
            stack.grayscale,
            thresholds=thresholds,
            voxel_size=stack.voxel_size,
            roi=rect_roi,
            profile=resolved_profile,
            prefer_opencv=resolved_prefer_opencv,
            include_mesh=resolved_mesh,
            voxel_source=stack.voxel_source,
        )
        output_path = Path(out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_threshold_sweep_csv(results, output_path)
        best = best_sweep_result(results)
    except Exception as exc:
        print(f"Failed to run threshold sweep: {exc}")
        return 1

    print("MorphoStack Threshold Sweep Complete")
    print("====================================")
    print(f"Source: {stack.source_path}")
    print(f"Profile: {resolved_profile}")
    print(f"Thresholds: {len(results)}")
    print(f"Voxel source: {stack.voxel_source}")
    if best is not None:
        frame_count = len(best.analysis.frames)
        valid_fraction = len(best.analysis.valid_frames) / frame_count if frame_count else 0.0
        print(f"Best valid fraction: {valid_fraction:g} at threshold {best.threshold:g}")
    print(f"CSV: {output_path}")
    return 0


def run_batch(
    *,
    directory: str,
    threshold: float | None,
    out: str,
    recursive: bool = False,
    metrics_dir: str | None = None,
    bundle_dir: str | None = None,
    profile: str | None = None,
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
    prefer_opencv: bool | None = None,
    include_mesh: bool | None = None,
    project: str | None = None,
) -> int:
    project_settings = load_project_for_command(project)
    if isinstance(project_settings, int):
        return project_settings
    resolved_threshold = resolve_threshold(project_settings, threshold)
    if resolved_threshold is None:
        print("Batch threshold is required. Pass --threshold or set threshold in --project.")
        return 2
    resolved_profile = resolve_profile(project_settings, profile)
    resolved_mesh = resolve_bool(include_mesh, project_settings.include_mesh, False)
    resolved_prefer_opencv = resolve_bool(prefer_opencv, project_settings.prefer_opencv, True)
    voxel_override_result = resolve_voxel_override(project_settings, voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2
    voxel_override = voxel_override_result
    rect_roi = resolve_roi(project_settings, roi)
    input_dir = Path(directory)
    if not input_dir.is_dir():
        print(f"Batch directory does not exist: {input_dir}")
        return 1

    stack_paths = discover_stack_paths(input_dir, recursive=recursive)
    if not stack_paths:
        print(f"No supported stacks found in {input_dir}.")
        return 1

    output_path = Path(out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_metrics_dir = Path(metrics_dir) if metrics_dir else None
    if frame_metrics_dir:
        frame_metrics_dir.mkdir(parents=True, exist_ok=True)
    run_bundles_dir = Path(bundle_dir) if bundle_dir else None
    if run_bundles_dir:
        run_bundles_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    failures = 0
    for stack_path in stack_paths:
        try:
            stack = load_image_stack(stack_path, voxel_override=voxel_override)
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=resolved_threshold,
                voxel_size=stack.voxel_size,
                roi=rect_roi,
                profile=resolved_profile,
                prefer_opencv=resolved_prefer_opencv,
                include_mesh=resolved_mesh,
            )
            rows.append(
                analysis_summary_row(
                    analysis,
                    source_path=str(stack.source_path),
                    threshold=resolved_threshold,
                    voxel_source=stack.voxel_source,
                )
            )
            if frame_metrics_dir:
                write_analysis_csv(analysis, frame_metrics_dir / f"{safe_output_stem(stack_path)}_metrics.csv")
            if run_bundles_dir:
                run_dir = bundle_run_directory(run_bundles_dir, stack_path, relative_to=input_dir)
                run_dir.mkdir(parents=True, exist_ok=True)
                write_analysis_csv(analysis, run_dir / "metrics.csv")
                write_analysis_manifest_json(
                    analysis_manifest(
                        analysis,
                        source_path=str(stack.source_path),
                        threshold=resolved_threshold,
                        roi=roi_to_payload(rect_roi),
                        include_mesh=resolved_mesh,
                        prefer_opencv=resolved_prefer_opencv,
                        voxel_source=stack.voxel_source,
                    ),
                    run_dir / "manifest.json",
                )
                write_analysis_report_markdown(
                    analysis,
                    run_dir / "report.md",
                    source_path=str(stack.source_path),
                    threshold=resolved_threshold,
                    roi=roi_to_payload(rect_roi),
                    include_mesh=resolved_mesh,
                    prefer_opencv=resolved_prefer_opencv,
                    voxel_source=stack.voxel_source,
                )
        except Exception as exc:
            failures += 1
            rows.append(failed_analysis_summary_row(str(stack_path), str(exc)))

    write_batch_summary_csv(rows, output_path)

    print("MorphoStack Batch Complete")
    print("==========================")
    print(f"Stacks found: {len(stack_paths)}")
    print(f"Succeeded: {len(stack_paths) - failures}")
    print(f"Failed: {failures}")
    print(f"Summary CSV: {output_path}")
    if frame_metrics_dir:
        print(f"Frame metrics: {frame_metrics_dir}")
    if run_bundles_dir:
        print(f"Run bundles: {run_bundles_dir}")
    return 1 if failures else 0


def run_validate(
    *,
    expected: str,
    actual: str,
    tolerance: float = 1e-6,
    columns: list[str] | None = None,
    key_column: str = "frame_index",
) -> int:
    try:
        report = compare_metric_csv(
            expected,
            actual,
            tolerance=tolerance,
            columns=columns,
            key_column=key_column,
        )
    except Exception as exc:
        print(f"Failed to validate CSV metrics: {exc}")
        return 1

    print(format_validation_report(report))
    return 0 if report.passed else 1


def discover_stack_paths(directory: Path, *, recursive: bool = False) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() in {".tif", ".tiff", ".czi"}
    )


def safe_output_stem(path: Path) -> str:
    raw = path.stem.strip() or "stack"
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in raw)


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


def roi_to_payload(roi: RectROI | None) -> dict[str, int] | None:
    if roi is None:
        return None
    return {"xmin": roi.xmin, "xmax": roi.xmax, "ymin": roi.ymin, "ymax": roi.ymax}


def run_serve(*, host: str, port: int) -> int:
    try:
        import uvicorn
    except Exception as exc:
        print(f"Failed to start API server: uvicorn is required ({exc})")
        return 1

    uvicorn.run("morphostack.api:app", host=host, port=port)
    return 0


def run_dev(
    *,
    host: str = "127.0.0.1",
    api_port: int = 8000,
    web_port: int = 5173,
    open_browser: bool = True,
    check_only: bool = False,
) -> int:
    issues = dev_prerequisite_issues(WEB_APP_DIR)
    if issues:
        print("MorphoStack dev environment is not ready:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    if check_only:
        print("MorphoStack dev environment is ready.")
        print(f"Backend: http://{host}:{api_port}")
        print(f"Web UI: http://{host}:{web_port}")
        return 0

    npm_command = shutil.which("npm")
    if npm_command is None:
        print("npm is required to run the web UI.")
        return 1

    api_target = f"http://{host}:{api_port}"
    web_url = f"http://{host}:{web_port}"
    env = dict(os.environ)
    env["MORPHOSTACK_API_TARGET"] = api_target
    processes: list[subprocess.Popen[bytes]] = []

    try:
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "morphostack.api:app",
                "--host",
                host,
                "--port",
                str(api_port),
            ]
        )
        processes.append(backend)

        frontend = subprocess.Popen(
            [
                npm_command,
                "run",
                "dev",
                "--",
                "--host",
                host,
                "--port",
                str(web_port),
            ],
            cwd=WEB_APP_DIR,
            env=env,
        )
        processes.append(frontend)

        print("MorphoStack dev app is starting.")
        print(f"Backend: {api_target}")
        print(f"Web UI: {web_url}")
        print("Press Ctrl+C to stop both processes.")
        if open_browser:
            webbrowser.open(web_url)

        while True:
            for process in processes:
                returncode = process.poll()
                if returncode is not None:
                    print(f"A dev process exited with code {returncode}.")
                    return returncode
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping MorphoStack dev app...")
        return 0
    finally:
        stop_processes(processes)


def dev_prerequisite_issues(web_app_dir: Path) -> list[str]:
    issues: list[str] = []
    if shutil.which("npm") is None:
        issues.append("npm was not found on PATH.")
    if not import_available("uvicorn"):
        issues.append("uvicorn is not installed in this Python environment.")
    if not (web_app_dir / "package.json").exists():
        issues.append(f"web package.json was not found at {web_app_dir}.")
    if not (web_app_dir / "node_modules").exists():
        issues.append("web dependencies are not installed; run npm install in apps/web.")
    return issues


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def load_project_for_command(project: str | None) -> ProjectSettings | int:
    if project is None:
        return ProjectSettings()
    try:
        return load_project_settings(project)
    except Exception as exc:
        print(f"Failed to load project settings: {exc}")
        return 1


def resolve_threshold(settings: ProjectSettings, threshold: float | None) -> float | None:
    return threshold if threshold is not None else settings.threshold


def resolve_profile(settings: ProjectSettings, profile: str | None) -> str:
    return profile or settings.profile or "vesicle"


def resolve_bool(command_value: bool | None, project_value: bool | None, default: bool) -> bool:
    if command_value is not None:
        return command_value
    if project_value is not None:
        return project_value
    return default


def prefer_opencv_from_flag(fallback_contours: bool | None) -> bool | None:
    if fallback_contours is None:
        return None
    return not fallback_contours


def resolve_roi(settings: ProjectSettings, roi: list[int] | None) -> RectROI | None:
    if roi is not None:
        return RectROI(*roi)
    return settings.roi


def resolve_voxel_override(
    settings: ProjectSettings,
    voxel_x: float | None,
    voxel_y: float | None,
    voxel_z: float | None,
) -> VoxelSize | None | str:
    command_value = build_voxel_override(voxel_x, voxel_y, voxel_z)
    if command_value is not None:
        return command_value
    return settings.voxel_size


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
