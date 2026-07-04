from __future__ import annotations

import json
from importlib import import_module

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


def test_doctor_json_is_valid(capsys):
    assert main(["doctor", "--json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "platform" in payload
    assert "dependencies" in payload


def test_init_can_skip_dependency_install(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack first-run setup" in out
    assert "Skipped dependency installation" in out


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

    monkeypatch.setattr(cli_main_module, "load_image_stack", lambda *_, **__: Stack())
    assert main(["inspect", "sample.tif"]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack Stack Inspection" in out
    assert "Grayscale shape: (3, 10, 20)" in out
    assert "x=0.1 um" in out


def test_analyze_requires_complete_voxel_override(capsys):
    assert main(["analyze", "sample.tif", "--threshold", "100", "--out", "out.csv", "--voxel-x", "1.0"]) == 2
    out = capsys.readouterr().out
    assert "requires --voxel-x, --voxel-y, and --voxel-z" in out


def test_analyze_writes_csv_from_synthetic_tiff(tmp_path, capsys):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    input_path = tmp_path / "stack.tif"
    output_path = tmp_path / "metrics.csv"
    tifffile.imwrite(input_path, stack)

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
    assert output_path.exists()
    csv_text = output_path.read_text(encoding="utf-8")
    assert "frame_index,threshold,method,has_contour" in csv_text
    assert "0,100.0,fallback,True" in csv_text
