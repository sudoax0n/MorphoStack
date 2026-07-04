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
    RectROI,
    VoxelSize,
    analyze_stack,
    apply_rect_roi,
    load_image_stack,
    suggest_threshold,
    write_analysis_csv,
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
    analyze = subparsers.add_parser(
        "analyze",
        help="Run headless threshold analysis on an image stack and write CSV metrics.",
    )
    analyze.add_argument("path", help="Path to a .tif, .tiff, or .czi file.")
    analyze.add_argument("--threshold", type=float, required=True, help="Global intensity threshold.")
    analyze.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="vesicle",
        help="Analysis profile. Default: vesicle.",
    )
    analyze.add_argument("--out", required=True, help="CSV output path.")
    analyze.add_argument("--voxel-x", type=float, help="Override X voxel size in micrometers.")
    analyze.add_argument("--voxel-y", type=float, help="Override Y voxel size in micrometers.")
    analyze.add_argument("--voxel-z", type=float, help="Override Z voxel size in micrometers.")
    analyze.add_argument("--roi", nargs=4, type=int, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    analyze.add_argument(
        "--mesh",
        action="store_true",
        help="Assemble contour masks and compute 3D surface area/volume.",
    )
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
            voxel_x=args.voxel_x,
            voxel_y=args.voxel_y,
            voxel_z=args.voxel_z,
            roi=args.roi,
            prefer_opencv=not args.fallback_contours,
            include_mesh=args.mesh,
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
    profile: str = "vesicle",
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
    prefer_opencv: bool = True,
    include_mesh: bool = False,
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
            profile=profile,
            prefer_opencv=prefer_opencv,
            include_mesh=include_mesh,
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
    print(f"Profile: {analysis.profile}")
    print(f"Frames: {len(analysis.frames)}")
    print(f"Valid frames: {len(analysis.valid_frames)}")
    if analysis.mesh:
        print(f"3D surface area: {analysis.mesh.surface_area_um2:g} um^2")
        print(f"3D volume: {analysis.mesh.volume_um3:g} um^3")
    print(f"CSV: {output_path}")
    return 0


def run_threshold(
    *,
    path: str,
    method: str = "auto",
    voxel_x: float | None = None,
    voxel_y: float | None = None,
    voxel_z: float | None = None,
    roi: list[int] | None = None,
) -> int:
    voxel_override_result = build_voxel_override(voxel_x, voxel_y, voxel_z)
    if voxel_override_result == "partial":
        print("Voxel override requires --voxel-x, --voxel-y, and --voxel-z together.")
        return 2
    voxel_override = voxel_override_result
    rect_roi = RectROI(*roi) if roi is not None else None

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
