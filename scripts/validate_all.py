#!/usr/bin/env python3
"""Run MorphoStack validation checks and write a combined report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_command(command: list[str], *, cwd: Path = PROJECT_ROOT) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def collect_run_summaries(runs_dir: Path) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for manifest_path in sorted(runs_dir.rglob("manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            summaries.append(
                {
                    "manifest": str(manifest_path.relative_to(runs_dir)),
                    "status": "error",
                    "message": str(exc),
                }
            )
            continue
        summary = manifest.get("summary", {})
        summaries.append(
            {
                "manifest": str(manifest_path.relative_to(runs_dir)),
                "source_path": manifest.get("source_path"),
                "profile": manifest.get("profile"),
                "threshold": manifest.get("threshold"),
                "valid_frame_count": summary.get("valid_frame_count"),
                "valid_fraction": summary.get("valid_fraction"),
                "preview_png": str(
                    (manifest_path.parent / "preview-seed-frame.png").relative_to(runs_dir)
                )
                if (manifest_path.parent / "preview-seed-frame.png").exists()
                else None,
                "status": "ok",
            }
        )
    return summaries


def write_report(
    *,
    reports_dir: Path,
    synthetic_ok: bool,
    synthetic_output: str,
    preview_output: str,
    run_summaries: list[dict[str, object]],
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    report_path = reports_dir / "validation-all.md"
    json_path = reports_dir / "validation-all.json"

    lines = [
        "# MorphoStack Validation Summary",
        "",
        f"- Generated: `{timestamp}`",
        f"- Synthetic regression: `{'PASS' if synthetic_ok else 'FAIL'}`",
        f"- Validation runs indexed: `{len(run_summaries)}`",
        "",
        "## Synthetic Sphere",
        "",
        "```text",
        synthetic_output or "(no output)",
        "```",
        "",
        "## Preview Capture",
        "",
        "```text",
        preview_output or "(not run)",
        "```",
        "",
        "## Validation Runs",
        "",
        "| Manifest | Profile | Valid frames | Preview PNG |",
        "| --- | --- | ---: | --- |",
    ]
    for item in run_summaries:
        lines.append(
            f"| `{item.get('manifest')}` | `{item.get('profile')}` | "
            f"{item.get('valid_frame_count')} | "
            f"{'yes' if item.get('preview_png') else 'no'} |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated_at_utc": timestamp,
                "synthetic_ok": synthetic_ok,
                "runs": run_summaries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default=str(PROJECT_ROOT / "validation" / "runs"),
        help="Validation runs root directory.",
    )
    parser.add_argument(
        "--reports-dir",
        default=str(PROJECT_ROOT / "validation" / "reports"),
        help="Directory for combined validation report.",
    )
    parser.add_argument("--skip-previews", action="store_true", help="Do not regenerate preview PNGs.")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    reports_dir = Path(args.reports_dir)

    synthetic_code, synthetic_output = run_command(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_synthetic.py")]
    )
    preview_output = ""
    if not args.skip_previews:
        preview_code, preview_output = run_command(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "capture_validation_previews.py")]
        )
        if preview_code != 0:
            print(preview_output)
            return preview_code

    run_summaries = collect_run_summaries(runs_dir)
    report_path = write_report(
        reports_dir=reports_dir,
        synthetic_ok=synthetic_code == 0,
        synthetic_output=synthetic_output,
        preview_output=preview_output,
        run_summaries=run_summaries,
    )
    print(f"Validation summary: {report_path}")
    return 0 if synthetic_code == 0 else synthetic_code


if __name__ == "__main__":
    raise SystemExit(main())