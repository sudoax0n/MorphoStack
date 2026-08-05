from __future__ import annotations

import csv
from io import StringIO
import json

import numpy as np

from morphostack.core import VoxelSize, analyze_stack
from morphostack.core.export import (
    BATCH_SUMMARY_COLUMNS,
    CSV_COLUMNS,
    analysis_manifest,
    analysis_report_markdown,
    analysis_rows,
    analysis_run_warnings,
    analysis_summary,
    analysis_summary_row,
    analysis_warnings,
    write_analysis_csv,
    write_analysis_manifest_json,
    write_analysis_report_markdown,
)


def test_analysis_rows_include_empty_and_valid_frames():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[1, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    rows = analysis_rows(analysis)

    assert rows[0]["has_contour"] is False
    assert rows[0]["profile"] == "vesicle"
    assert rows[0]["area_um2"] == 0.0
    assert rows[0]["aspect_ratio"] == 0.0
    assert rows[1]["has_contour"] is True
    assert rows[1]["area_um2"] == 9.0
    assert rows[1]["aspect_ratio"] == 1.0
    assert rows[1]["elongation"] == 0.0
    assert rows[1]["deformation_index"] == 0.0
    assert rows[1]["extent"] == 1.0
    assert rows[1]["solidity"] == 1.0


def test_write_analysis_csv_writes_header_and_rows():
    """Header order matches production CSV_COLUMNS (Packet 08 threshold provenance)."""
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )
    buffer = StringIO()

    write_analysis_csv(analysis, buffer)

    csv_text = buffer.getvalue()
    lines = csv_text.splitlines()
    assert lines, "CSV must include a header line"
    # Exact column order = production schema authority (do not invent alternate order).
    assert lines[0] == ",".join(CSV_COLUMNS)
    assert CSV_COLUMNS[:9] == (
        "frame_index",
        "threshold",
        "requested_threshold",
        "effective_threshold",
        "threshold_semantics",
        "profile",
        "method",
        "excluded",
        "has_contour",
    )
    assert "bbox_width_um,bbox_height_um,aspect_ratio,elongation,deformation_index,extent,equivalent_diameter_um,solidity" in lines[0]
    assert "skel_ok,skel_perimeter_px,skel_perimeter_um" in lines[0]
    assert "mesh_surface_area_um2,mesh_volume_um3,mesh_equivalent_sphere_diameter_um,mesh_sphericity" in lines[0]

    rows = list(csv.DictReader(StringIO(csv_text)))
    assert len(rows) == 1
    row = rows[0]
    assert row["frame_index"] == "0"
    assert float(row["threshold"]) == 100.0
    assert float(row["requested_threshold"]) == 100.0
    assert float(row["effective_threshold"]) == 100.0
    assert row["threshold_semantics"] == "global_intensity"
    assert row["profile"] == "vesicle"
    assert row["method"] == "fallback"
    assert row["excluded"] == "False"
    assert row["has_contour"] == "True"
    assert float(row["area_um2"]) == 9.0
    assert float(row["aspect_ratio"]) == 1.0
    # Representative row prefix (legacy + Packet 08 provenance columns).
    assert "0,100.0,100.0,100.0,global_intensity,vesicle,fallback,False,True" in csv_text


def test_analysis_manifest_records_run_settings():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(0.5, 0.5, 1.0),
        profile="vesicle",
        prefer_opencv=False,
    )

    manifest = analysis_manifest(
        analysis,
        source_path="stack.tif",
        threshold=100,
        source_sha256="abc123",
        roi={"xmin": 1, "xmax": 4, "ymin": 2, "ymax": 6},
        include_mesh=False,
        prefer_opencv=False,
        voxel_source="metadata",
    )

    assert manifest["source_path"] == "stack.tif"
    assert manifest["source_sha256"] == "abc123"
    assert manifest["profile"] == "vesicle"
    assert manifest["threshold"] == 100
    assert manifest["roi"] == {"xmin": 1, "xmax": 4, "ymin": 2, "ymax": 6}
    assert manifest["voxel_size"] == {"x_um": 0.5, "y_um": 0.5, "z_um": 1.0}
    assert manifest["voxel_source"] == "metadata"
    assert manifest["frame_count"] == 1
    assert manifest["summary"]["metrics"]["area_um2"]["mean"] == 2.25
    assert "created_at_utc" in manifest
    assert manifest["warnings"] == []
    assert manifest["rbc"] is None


def test_rbc_manifest_carries_capability_envelope():
    from morphostack.core.pipeline import ObjectSeed
    from morphostack.core.rbc_capabilities import calibration_from_override
    from morphostack.core.rbc_models import RBC_METRIC_DEFINITION_VERSION

    n, size = 9, 48
    stack = np.zeros((n, size, size), dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    disk = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= 12**2
    for z in range(1, n - 1):
        stack[z][disk] = 210
    cal = calibration_from_override(0.1, 0.1, 0.2, source_format="tiff")
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(0.1, 0.1, 0.2),
        profile="rbc",
        prefer_opencv=False,
        object_seed=ObjectSeed(x=24.0, y=24.0, frame_index=4, radius=16.0),
        source_path="cell.tif",
        calibration=cal,
        include_mesh=True,
    )
    manifest = analysis_manifest(
        analysis,
        source_path="cell.tif",
        threshold=100,
        voxel_source="override",
        calibration=cal,
    )
    rbc = manifest["rbc"]
    assert rbc is not None
    assert rbc["metric_definition_version"] == RBC_METRIC_DEFINITION_VERSION
    assert rbc["authority"] in {"MEASURED", "WITHHELD"}
    assert rbc["capability"] in {
        "PIXEL_PREVIEW",
        "2D_OUTER_CONTOUR",
        "3D_OCCUPANCY_VALIDATED",
    }
    # Withheld / 2D-only must not publish measured mesh volume as zeros.
    if rbc["capability"] != "3D_OCCUPANCY_VALIDATED":
        assert manifest["mesh"] is None or (
            rbc.get("measured") is None or rbc["measured"].get("volume_um3") is None
        )
        if rbc.get("measured") is not None:
            assert rbc["measured"].get("volume_um3") is None


def test_analysis_summary_uses_valid_frames_only():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[1, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    summary = analysis_summary(analysis)

    assert summary["frame_count"] == 2
    assert summary["valid_frame_count"] == 1
    assert summary["valid_fraction"] == 0.5
    assert summary["metrics"]["area_um2"] == {"mean": 9.0, "min": 9.0, "max": 9.0, "std": 0.0}
    assert summary["metrics"]["circularity"]["mean"] > 0


def test_analysis_summary_handles_no_valid_frames():
    analysis = analyze_stack(
        np.zeros((2, 8, 8), dtype=np.uint8),
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    summary = analysis_summary(analysis)

    assert summary["frame_count"] == 2
    assert summary["valid_frame_count"] == 0
    assert summary["valid_fraction"] == 0.0
    assert summary["metrics"] == {}


def test_analysis_summary_row_records_source_sha256():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    row = analysis_summary_row(
        analysis,
        source_path="stack.tif",
        threshold=100,
        source_sha256="abc123",
        voxel_source="override",
    )

    assert BATCH_SUMMARY_COLUMNS[1] == "source_sha256"
    assert row["source_sha256"] == "abc123"


def test_analysis_warnings_report_no_valid_contours():
    analysis = analyze_stack(
        np.zeros((2, 8, 8), dtype=np.uint8),
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    warnings = analysis_warnings(analysis)

    assert warnings[0]["code"] == "no_valid_contours"
    assert warnings[0]["severity"] == "error"


def test_analysis_run_warnings_report_default_voxel_source():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    warnings = analysis_run_warnings(analysis, voxel_source="default")

    assert warnings[0]["code"] == "default_voxel_size"
    assert warnings[0]["severity"] == "warning"

    manifest = analysis_manifest(
        analysis,
        source_path="uncalibrated.tif",
        threshold=100,
        voxel_source="default",
    )
    assert manifest["warnings"][0]["code"] == "default_voxel_size"


def test_analysis_warnings_report_partial_contours():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[1, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )

    warnings = analysis_warnings(analysis)

    assert warnings[0]["code"] == "partial_contours"
    assert warnings[0]["invalid_frame_count"] == 1


def test_write_analysis_manifest_json_writes_pretty_json():
    buffer = StringIO()
    manifest = {"source_path": "stack.tif", "profile": "vesicle"}

    write_analysis_manifest_json(manifest, buffer)

    payload = json.loads(buffer.getvalue())
    assert payload == manifest


def test_analysis_report_markdown_summarizes_run():
    stack = np.zeros((2, 8, 8), dtype=np.uint8)
    stack[1, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="vesicle",
        prefer_opencv=False,
    )

    report = analysis_report_markdown(
        analysis,
        source_path="stack.tif",
        threshold=100,
        source_sha256="abc123",
        include_mesh=False,
        prefer_opencv=False,
        voxel_source="override",
    )

    assert report.startswith("# MorphoStack Analysis Report")
    assert "- Source: `stack.tif`" in report
    assert "- Source SHA-256: `abc123`" in report
    assert "- Profile: `vesicle`" in report
    assert "- Valid frames: 1" in report
    assert "`partial_contours`" in report
    assert "| area_um2 | 9 | 9 | 9 | 0 |" in report
    assert "| 1 | yes | 9 | 12 |" in report


def test_write_analysis_report_markdown_writes_text():
    stack = np.zeros((1, 8, 8), dtype=np.uint8)
    stack[0, 2:5, 1:4] = 200
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )
    buffer = StringIO()

    write_analysis_report_markdown(
        analysis,
        buffer,
        source_path="stack.tif",
        threshold=100,
    )

    assert "## Metric Summary" in buffer.getvalue()
