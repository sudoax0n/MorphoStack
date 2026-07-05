from __future__ import annotations

import csv
import hashlib
import json
import socket
from importlib import import_module
from types import SimpleNamespace

import numpy as np
import pytest

from morphostack.cli.main import main
from morphostack.core import VoxelSize

cli_main_module = import_module("morphostack.cli.main")


def test_default_command_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack local morphometry toolkit" in out


def test_doctor_prints_report(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack Doctor" in out
    assert "Dependencies:" in out
    assert "Web app:" in out


def test_doctor_json_is_valid(capsys):
    assert main(["doctor", "--json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "platform" in payload
    assert "dependencies" in payload
    assert payload["commands"]["git"]["available"] in {True, False}
    assert "web" in payload
    assert "node_modules" in payload["web"]


def test_doctor_command_diagnostics_handles_missing_command(monkeypatch):
    monkeypatch.setattr(cli_main_module.shutil, "which", lambda _: None)

    payload = cli_main_module.command_diagnostics("missing-tool", "--version")

    assert payload == {"available": False, "path": None, "version": None}


def test_doctor_web_diagnostics_reports_web_files(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()

    payload = cli_main_module.web_diagnostics(tmp_path)

    assert payload["package_json"] is True
    assert payload["node_modules"] is True


def test_init_can_skip_dependency_install(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack first-run setup" in out
    assert "Skipped Python dependency installation" in out


def test_init_can_install_web_dependencies(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli_main_module.shutil, "which", lambda name: "npm.cmd" if name == "npm" else None)
    monkeypatch.setattr(
        cli_main_module.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(returncode=0),
    )

    assert main(["init", "--yes", "--extras", "", "--web"]) == 0

    out = capsys.readouterr().out
    assert "No optional Python dependency groups selected." in out
    assert "Installing browser UI dependencies" in out
    assert (["npm.cmd", "install"], {"cwd": cli_main_module.WEB_APP_DIR, "check": False}) in calls


def test_init_web_reports_missing_npm(monkeypatch, capsys):
    monkeypatch.setattr(cli_main_module.shutil, "which", lambda _: None)

    assert main(["init", "--yes", "--extras", "", "--web"]) == 1

    out = capsys.readouterr().out
    assert "npm is required to install browser UI dependencies" in out


def test_project_init_writes_settings_file(tmp_path, capsys):
    project_path = tmp_path / "morphostack.project.json"

    result = main(
        [
            "project",
            "init",
            "--out",
            str(project_path),
            "--profile",
            "rbc",
            "--threshold",
            "100",
            "--voxel-x",
            "0.1",
            "--voxel-y",
            "0.2",
            "--voxel-z",
            "0.5",
            "--roi",
            "1",
            "7",
            "2",
            "8",
            "--fallback-contours",
            "--sweep-start",
            "50",
            "--sweep-stop",
            "150",
            "--sweep-step",
            "25",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "MorphoStack Project Created" in out
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    assert payload["profile"] == "rbc"
    assert payload["threshold"] == 100
    assert payload["prefer_opencv"] is False
    assert payload["sweep"] == {"start": 50, "stop": 150, "step": 25}


def test_dev_check_reports_ready(monkeypatch, capsys):
    monkeypatch.setattr(cli_main_module, "dev_prerequisite_issues", lambda _: [])
    monkeypatch.setattr(cli_main_module, "port_availability_issues", lambda **_: [])

    assert main(["dev", "--check", "--no-open", "--api-port", "8123", "--web-port", "5123"]) == 0

    out = capsys.readouterr().out
    assert "MorphoStack dev environment is ready." in out
    assert "http://127.0.0.1:8123" in out
    assert "http://127.0.0.1:5123" in out


def test_dev_check_reports_missing_prerequisites(monkeypatch, capsys):
    monkeypatch.setattr(cli_main_module, "dev_prerequisite_issues", lambda _: ["npm was not found on PATH."])
    monkeypatch.setattr(cli_main_module, "port_availability_issues", lambda **_: [])

    assert main(["dev", "--check"]) == 1

    out = capsys.readouterr().out
    assert "MorphoStack dev environment is not ready" in out
    assert "npm was not found" in out


def test_dev_prerequisite_issues_suggest_setup_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_main_module.shutil, "which", lambda _: None)
    monkeypatch.setattr(cli_main_module, "import_available", lambda _: False)

    issues = cli_main_module.dev_prerequisite_issues(tmp_path)

    report = "\n".join(issues)
    assert "morphostack init --web" in report
    assert "morphostack init --extras api" in report


def test_port_availability_issues_reports_used_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]

        issues = cli_main_module.port_availability_issues(host="127.0.0.1", api_port=port, web_port=0)

    assert issues == [
        f"Backend port {port} is already in use on 127.0.0.1. Stop the existing process or pass --api-port."
    ]


def test_inspect_requires_complete_voxel_override(capsys):
    assert main(["inspect", "sample.tif", "--voxel-x", "1.0"]) == 2
    out = capsys.readouterr().out
    assert "requires --voxel-x, --voxel-y, and --voxel-z" in out


def test_inspect_prints_stack_metadata(monkeypatch, capsys):
    class Stack:
        source_path = "sample.tif"
        grayscale = type("Shape", (), {"shape": (3, 10, 20)})()
        color = type("Shape", (), {"shape": (3, 10, 20, 3)})()
        voxel_size = VoxelSize(0.1, 0.2, 0.3)
        voxel_source = "metadata"

    monkeypatch.setattr(cli_main_module, "load_image_stack", lambda *_, **__: Stack())
    assert main(["inspect", "sample.tif"]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack Stack Inspection" in out
    assert "Grayscale shape: (3, 10, 20)" in out
    assert "x=0.1 um" in out
    assert "Voxel source: metadata" in out


def test_analyze_requires_complete_voxel_override(capsys):
    assert main(["analyze", "sample.tif", "--threshold", "100", "--out", "out.csv", "--voxel-x", "1.0"]) == 2
    out = capsys.readouterr().out
    assert "requires --voxel-x, --voxel-y, and --voxel-z" in out


def test_analyze_requires_threshold_without_project(capsys):
    assert main(["analyze", "sample.tif", "--out", "out.csv"]) == 2
    out = capsys.readouterr().out
    assert "threshold is required" in out


def test_analyze_requires_output_or_bundle(capsys):
    assert main(["analyze", "sample.tif", "--threshold", "100"]) == 2
    out = capsys.readouterr().out
    assert "Pass --out or --bundle-dir" in out


def test_threshold_requires_complete_voxel_override(capsys):
    assert main(["threshold", "sample.tif", "--voxel-x", "1.0"]) == 2
    out = capsys.readouterr().out
    assert "requires --voxel-x, --voxel-y, and --voxel-z" in out


def test_sweep_requires_complete_voxel_override(capsys):
    assert (
        main(
            [
                "sweep",
                "sample.tif",
                "--start",
                "50",
                "--stop",
                "100",
                "--step",
                "25",
                "--out",
                "sweep.csv",
                "--voxel-x",
                "1.0",
            ]
        )
        == 2
    )
    out = capsys.readouterr().out
    assert "requires --voxel-x, --voxel-y, and --voxel-z" in out


def test_threshold_prints_suggestion_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    tifffile.imwrite(input_path, stack, photometric="minisblack")

    result = main(["threshold", str(input_path), "--method", "percentile"])

    assert result == 0
    out = capsys.readouterr().out
    assert "MorphoStack Threshold Suggestion" in out
    assert "Method: percentile" in out
    assert "Threshold:" in out


def test_sweep_writes_summary_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "sweep.csv"
    tifffile.imwrite(input_path, stack, photometric="minisblack")

    result = main(
        [
            "sweep",
            str(input_path),
            "--start",
            "50",
            "--stop",
            "250",
            "--step",
            "100",
            "--out",
            str(output_path),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "MorphoStack Threshold Sweep Complete" in out
    assert "Thresholds: 3" in out
    assert "Best valid fraction: 1 at threshold 50" in out
    csv_text = output_path.read_text(encoding="utf-8")
    assert csv_text.startswith("threshold,profile,frame_count,valid_frame_count")
    assert "50.0,vesicle,2,2,1.0" in csv_text
    assert "250.0,vesicle,2,0,0.0" in csv_text


def test_sweep_uses_project_defaults_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "sweep.csv"
    project_path = tmp_path / "morphostack.project.json"
    tifffile.imwrite(input_path, stack, photometric="minisblack")
    project_path.write_text(
        json.dumps(
            {
                "version": 1,
                "profile": "rbc",
                "voxel_size": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
                "prefer_opencv": False,
                "sweep": {"start": 50, "stop": 250, "step": 100},
            }
        ),
        encoding="utf-8",
    )

    result = main(["sweep", str(input_path), "--out", str(output_path), "--project", str(project_path)])

    assert result == 0
    out = capsys.readouterr().out
    assert "Profile: rbc" in out
    assert "Thresholds: 3" in out
    csv_text = output_path.read_text(encoding="utf-8")
    assert "50.0,rbc,2,2,1.0" in csv_text


def test_analyze_writes_csv_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "metrics.csv"
    tifffile.imwrite(input_path, stack, photometric="minisblack")

    result = main(
        [
            "analyze",
            str(input_path),
            "--threshold",
            "100",
            "--out",
            str(output_path),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "MorphoStack Analysis Complete" in out
    assert "Mean area: 9 um^2" in out
    assert "Mean circularity:" in out
    assert "Voxel source: override" in out
    assert "Manifest:" in out
    assert output_path.exists()
    manifest_path = output_path.with_suffix(".csv.manifest.json")
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_path"] == str(input_path)
    assert manifest["source_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert manifest["profile"] == "vesicle"
    assert manifest["voxel_source"] == "override"
    assert manifest["summary"]["metrics"]["area_um2"]["mean"] == 9.0
    csv_text = output_path.read_text(encoding="utf-8")
    assert "frame_index,threshold,profile,method,has_contour" in csv_text
    assert "0,100.0,vesicle,fallback,True" in csv_text


def test_analyze_can_write_markdown_report_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "metrics.csv"
    report_path = tmp_path / "report.md"
    tifffile.imwrite(input_path, stack, photometric="minisblack")

    result = main(
        [
            "analyze",
            str(input_path),
            "--threshold",
            "100",
            "--out",
            str(output_path),
            "--report",
            str(report_path),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert f"Report: {report_path}" in out
    report = report_path.read_text(encoding="utf-8")
    assert report.startswith("# MorphoStack Analysis Report")
    assert "- Valid frames: 2" in report
    assert "| area_um2 | 9 | 9 | 9 | 0 |" in report


def test_analyze_bundle_writes_run_artifacts_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    bundle_dir = tmp_path / "runs"
    tifffile.imwrite(input_path, stack, photometric="minisblack")

    result = main(
        [
            "analyze",
            str(input_path),
            "--threshold",
            "100",
            "--bundle-dir",
            str(bundle_dir),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    run_dir = bundle_dir / "stack"
    out = capsys.readouterr().out
    assert f"Bundle: {run_dir}" in out
    assert (run_dir / "metrics.csv").exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "report.md").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_path"] == str(input_path)
    assert manifest["source_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "Source SHA-256" in report
    assert "# MorphoStack Analysis Report" in report


def test_analyze_uses_project_defaults_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "metrics.csv"
    project_path = tmp_path / "morphostack.project.json"
    tifffile.imwrite(input_path, stack, photometric="minisblack")
    project_path.write_text(
        json.dumps(
            {
                "version": 1,
                "profile": "rbc",
                "threshold": 100,
                "voxel_size": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
                "prefer_opencv": False,
            }
        ),
        encoding="utf-8",
    )

    result = main(["analyze", str(input_path), "--out", str(output_path), "--project", str(project_path)])

    assert result == 0
    out = capsys.readouterr().out
    assert "Profile: rbc" in out
    assert "Voxel source: override" in out
    manifest = json.loads(output_path.with_suffix(".csv.manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "rbc"
    assert manifest["threshold"] == 100
    csv_text = output_path.read_text(encoding="utf-8")
    assert "0,100.0,rbc,fallback,True" in csv_text


def test_analyze_can_write_mesh_summary_from_synthetic_tiff(tmp_path, capsys):
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((3, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "metrics.csv"
    tifffile.imwrite(input_path, stack, photometric="minisblack")

    result = main(
        [
            "analyze",
            str(input_path),
            "--threshold",
            "100",
            "--profile",
            "rbc",
            "--out",
            str(output_path),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
            "--mesh",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "Profile: rbc" in out
    assert "3D surface area:" in out
    assert "3D sphericity:" in out
    csv_text = output_path.read_text(encoding="utf-8")
    assert "rbc" in csv_text
    assert "mesh_surface_area_um2,mesh_volume_um3,mesh_equivalent_sphere_diameter_um,mesh_sphericity" in csv_text


def test_analyze_can_skip_manifest_from_synthetic_tiff(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "metrics.csv"
    tifffile.imwrite(input_path, stack, photometric="minisblack")

    result = main(
        [
            "analyze",
            str(input_path),
            "--threshold",
            "100",
            "--out",
            str(output_path),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
            "--no-manifest",
        ]
    )

    assert result == 0
    assert output_path.exists()
    assert not output_path.with_suffix(".csv.manifest.json").exists()


def test_analyze_prints_and_records_warnings_for_blank_stack(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    input_path = tmp_path / "blank.tif"
    output_path = tmp_path / "metrics.csv"
    tifffile.imwrite(input_path, np.zeros((2, 8, 8), dtype=np.uint8), photometric="minisblack")

    result = main(
        [
            "analyze",
            str(input_path),
            "--threshold",
            "100",
            "--out",
            str(output_path),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "Warning [no_valid_contours]" in out
    manifest = json.loads(output_path.with_suffix(".csv.manifest.json").read_text(encoding="utf-8"))
    assert manifest["warnings"][0]["code"] == "no_valid_contours"


def test_batch_writes_summary_csv_from_directory(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    input_dir = tmp_path / "stacks"
    input_dir.mkdir()
    for index in range(2):
        stack = np.zeros((2, 8, 8), dtype=np.uint8)
        stack[:, 2:5, 1:4] = 200
        tifffile.imwrite(input_dir / f"stack_{index}.tif", stack, photometric="minisblack")
    (input_dir / "notes.txt").write_text("ignore me", encoding="utf-8")
    output_path = tmp_path / "batch_summary.csv"
    metrics_dir = tmp_path / "frame_metrics"

    result = main(
        [
            "batch",
            str(input_dir),
            "--threshold",
            "100",
            "--out",
            str(output_path),
            "--metrics-dir",
            str(metrics_dir),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "MorphoStack Batch Complete" in out
    assert "Succeeded: 2" in out
    summary_csv = output_path.read_text(encoding="utf-8")
    assert "source_path,source_sha256,status,error_message,profile,threshold" in summary_csv
    assert "area_um2_mean" in summary_csv
    assert "voxel_source" in summary_csv
    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    for index, row in enumerate(rows):
        input_path = input_dir / f"stack_{index}.tif"
        assert row["source_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
        assert row["status"] == "ok"
        assert row["profile"] == "vesicle"
        assert row["valid_fraction"] == "1.0"
    assert len(list(metrics_dir.glob("*_metrics.csv"))) == 2


def test_batch_can_write_per_stack_run_bundles(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    input_dir = tmp_path / "stacks"
    input_dir.mkdir()
    for index in range(2):
        stack = np.zeros((2, 8, 8), dtype=np.uint8)
        stack[:, 2:5, 1:4] = 200
        tifffile.imwrite(input_dir / f"stack_{index}.tif", stack, photometric="minisblack")
    output_path = tmp_path / "batch_summary.csv"
    bundle_dir = tmp_path / "runs"

    result = main(
        [
            "batch",
            str(input_dir),
            "--threshold",
            "100",
            "--out",
            str(output_path),
            "--bundle-dir",
            str(bundle_dir),
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    out = capsys.readouterr().out
    assert f"Run bundles: {bundle_dir}" in out
    for index in range(2):
        run_dir = bundle_dir / f"stack_{index}"
        assert (run_dir / "metrics.csv").exists()
        assert (run_dir / "manifest.json").exists()
        assert (run_dir / "report.md").exists()


def test_batch_recursive_bundles_preserve_relative_paths(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    input_dir = tmp_path / "stacks"
    nested_dir = input_dir / "day_1"
    nested_dir.mkdir(parents=True)
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    tifffile.imwrite(nested_dir / "cell.tif", stack, photometric="minisblack")
    output_path = tmp_path / "batch_summary.csv"
    bundle_dir = tmp_path / "runs"

    result = main(
        [
            "batch",
            str(input_dir),
            "--threshold",
            "100",
            "--out",
            str(output_path),
            "--bundle-dir",
            str(bundle_dir),
            "--recursive",
            "--voxel-x",
            "1.0",
            "--voxel-y",
            "1.0",
            "--voxel-z",
            "1.0",
            "--fallback-contours",
        ]
    )

    assert result == 0
    assert (bundle_dir / "day_1" / "cell" / "metrics.csv").exists()
    assert (bundle_dir / "day_1" / "cell" / "manifest.json").exists()
    assert (bundle_dir / "day_1" / "cell" / "report.md").exists()


def test_batch_reports_when_no_supported_stacks(tmp_path, capsys):
    result = main(["batch", str(tmp_path), "--threshold", "100", "--out", str(tmp_path / "summary.csv")])

    assert result == 1
    out = capsys.readouterr().out
    assert "No supported stacks found" in out


def test_validate_passes_matching_metric_csvs(tmp_path, capsys):
    expected = tmp_path / "expected.csv"
    actual = tmp_path / "actual.csv"
    expected.write_text("frame_index,area_um2\n0,9.0\n", encoding="utf-8")
    actual.write_text("frame_index,area_um2\n0,9.000001\n", encoding="utf-8")

    result = main(["validate", str(expected), str(actual), "--tolerance", "0.00001"])

    assert result == 0
    out = capsys.readouterr().out
    assert "MorphoStack CSV Validation" in out
    assert "Result: PASS" in out


def test_validate_fails_different_metric_csvs(tmp_path, capsys):
    expected = tmp_path / "expected.csv"
    actual = tmp_path / "actual.csv"
    expected.write_text("frame_index,area_um2\n0,9.0\n", encoding="utf-8")
    actual.write_text("frame_index,area_um2\n0,10.0\n", encoding="utf-8")

    result = main(["validate", str(expected), str(actual)])

    assert result == 1
    out = capsys.readouterr().out
    assert "Result: FAIL" in out
    assert "area_um2" in out


def test_validate_all_columns_reports_text_differences(tmp_path, capsys):
    expected = tmp_path / "expected.csv"
    actual = tmp_path / "actual.csv"
    expected.write_text("frame_index,area_um2,source_sha256\n0,9.0,abc\n", encoding="utf-8")
    actual.write_text("frame_index,area_um2,source_sha256\n0,9.0,def\n", encoding="utf-8")

    result = main(["validate", str(expected), str(actual), "--all-columns"])

    assert result == 1
    out = capsys.readouterr().out
    assert "source_sha256" in out
    assert "expected=abc, actual=def" in out
