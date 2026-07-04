"""MorphoStack command-line entry point."""

from __future__ import annotations

import argparse
import subprocess
import shutil
import sys
from importlib import import_module

from morphostack import __version__
from morphostack.cli.system_info import collect_diagnostics, format_diagnostics


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(as_json=args.json)

    if args.command == "init":
        return run_init(yes=args.yes, extras=args.extras)

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
