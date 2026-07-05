from __future__ import annotations

import hashlib
from base64 import b64decode
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient

from morphostack.api import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def write_stack(path):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((3, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    tifffile.imwrite(path, stack, photometric="minisblack")


def stack_upload_bytes() -> bytes:
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((3, 8, 8), dtype=np.uint8)
    stack[:, 2:5, 1:4] = 200
    buffer = BytesIO()
    tifffile.imwrite(buffer, stack, photometric="minisblack")
    return buffer.getvalue()


def metric_csv_bytes(area_um2: float) -> bytes:
    return f"frame_index,area_um2\n0,{area_um2}\n".encode("utf-8")


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["profiles"] == ["vesicle", "rbc"]


def test_inspect_stack(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/inspect",
        json={
            "path": str(path),
            "voxel": {"x_um": 0.1, "y_um": 0.2, "z_um": 0.3},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["grayscale_shape"] == [3, 8, 8]
    assert payload["voxel_size"] == {"x_um": 0.1, "y_um": 0.2, "z_um": 0.3}
    assert payload["voxel_source"] == "override"


def test_analyze_stack_without_mesh(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/analyze",
        json={
            "path": str(path),
            "threshold": 100,
            "profile": "rbc",
            "voxel": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
            "prefer_opencv": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "rbc"
    assert payload["frame_count"] == 3
    assert payload["valid_frame_count"] == 3
    assert payload["manifest"]["profile"] == "rbc"
    assert payload["manifest"]["source_path"] == str(path)
    assert payload["manifest"]["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["manifest"]["threshold"] == 100
    assert payload["voxel_source"] == "override"
    assert payload["manifest"]["voxel_source"] == "override"
    assert payload["warnings"] == []
    assert payload["manifest"]["warnings"] == []
    assert payload["summary"]["metrics"]["area_um2"]["mean"] == 9.0
    assert payload["manifest"]["summary"]["metrics"]["area_um2"]["mean"] == 9.0
    assert payload["mesh"] is None
    assert payload["rows"][0]["area_um2"] == 9.0
    assert payload["rows"][0]["aspect_ratio"] == 1.0
    assert payload["rows"][0]["elongation"] == 0.0
    assert payload["rows"][0]["deformation_index"] == 0.0
    assert payload["rows"][0]["extent"] == 1.0
    assert payload["rows"][0]["solidity"] == 1.0


def test_analyze_stack_with_mesh(client, tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/analyze",
        json={
            "path": str(path),
            "threshold": 100,
            "voxel": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
            "prefer_opencv": False,
            "include_mesh": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mesh"]["surface_area_um2"] > 0
    assert payload["mesh"]["volume_um3"] > 0
    assert payload["mesh"]["equivalent_sphere_diameter_um"] > 0
    assert payload["mesh"]["sphericity"] > 0


def test_threshold_stack_returns_suggestion(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/threshold",
        json={"path": str(path), "method": "percentile"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(path)
    assert payload["method"] == "percentile"
    assert payload["threshold"] >= 0


def test_preview_stack_returns_png(client, tmp_path):
    pytest.importorskip("PIL")
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 1,
            "prefer_opencv": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(path)
    assert payload["frame_index"] == 1
    assert payload["width"] == 8
    assert payload["height"] == 8
    assert b64decode(payload["image_png_base64"]).startswith(b"\x89PNG")


def test_sweep_stack_returns_summary_rows(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/sweep",
        json={
            "path": str(path),
            "start": 50,
            "stop": 250,
            "step": 100,
            "voxel": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
            "prefer_opencv": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(path)
    assert payload["threshold_count"] == 3
    assert payload["best_threshold"] == 50.0
    assert payload["voxel_source"] == "override"
    assert payload["columns"][0] == "threshold"
    assert payload["rows"][0]["valid_frame_count"] == 3
    assert payload["rows"][0]["area_um2_mean"] == 9.0
    assert payload["rows"][2]["warning_codes"] == "no_valid_contours"


def test_preview_bad_frame_returns_400(client, tmp_path):
    pytest.importorskip("PIL")
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/preview",
        json={"path": str(path), "threshold": 100, "frame_index": 9},
    )

    assert response.status_code == 400
    assert "frame_index" in response.json()["detail"]


def test_upload_inspect_stack(client):
    response = client.post(
        "/upload/inspect",
        files={"file": ("stack.tif", stack_upload_bytes(), "image/tiff")},
        data={"voxel_x_um": "0.1", "voxel_y_um": "0.2", "voxel_z_um": "0.3"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == "stack.tif"
    assert payload["grayscale_shape"] == [3, 8, 8]
    assert payload["voxel_size"] == {"x_um": 0.1, "y_um": 0.2, "z_um": 0.3}
    assert payload["voxel_source"] == "override"


def test_upload_analyze_stack_with_mesh(client):
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    upload_bytes = stack_upload_bytes()

    response = client.post(
        "/upload/analyze",
        files={"file": ("stack.tif", upload_bytes, "image/tiff")},
        data={
            "threshold": "100",
            "profile": "rbc",
            "voxel_x_um": "1.0",
            "voxel_y_um": "1.0",
            "voxel_z_um": "1.0",
            "prefer_opencv": "false",
            "include_mesh": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == "stack.tif"
    assert payload["profile"] == "rbc"
    assert payload["manifest"]["source_path"] == "stack.tif"
    assert payload["manifest"]["source_sha256"] == hashlib.sha256(upload_bytes).hexdigest()
    assert payload["manifest"]["include_mesh"] is True
    assert payload["manifest"]["voxel_source"] == "override"
    assert payload["warnings"] == []
    assert payload["summary"]["metrics"]["area_um2"]["mean"] == 9.0
    assert payload["frame_count"] == 3
    assert payload["valid_frame_count"] == 3
    assert payload["rows"][0]["area_um2"] == 9.0
    assert payload["rows"][0]["deformation_index"] == 0.0
    assert payload["rows"][0]["equivalent_diameter_um"] > 0
    assert payload["mesh"]["surface_area_um2"] > 0
    assert payload["mesh"]["volume_um3"] > 0
    assert payload["mesh"]["equivalent_sphere_diameter_um"] > 0
    assert payload["mesh"]["sphericity"] > 0


def test_upload_batch_analyze_returns_summary_rows(client):
    response = client.post(
        "/upload/batch",
        files=[
            ("files", ("stack_a.tif", stack_upload_bytes(), "image/tiff")),
            ("files", ("stack_b.tif", stack_upload_bytes(), "image/tiff")),
        ],
        data={
            "threshold": "100",
            "profile": "rbc",
            "voxel_x_um": "1.0",
            "voxel_y_um": "1.0",
            "voxel_z_um": "1.0",
            "prefer_opencv": "false",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_count"] == 2
    assert payload["succeeded_count"] == 2
    assert payload["failed_count"] == 0
    assert payload["columns"][0] == "source_path"
    assert payload["rows"][0]["profile"] == "rbc"
    assert payload["rows"][0]["voxel_source"] == "override"
    assert payload["rows"][0]["area_um2_mean"] == 9.0
    assert payload["rows"][0]["deformation_index_mean"] == 0.0


def test_upload_validate_csv_passes_matching_metrics(client):
    response = client.post(
        "/upload/validate",
        files={
            "expected_file": ("expected.csv", metric_csv_bytes(9.0), "text/csv"),
            "actual_file": ("actual.csv", metric_csv_bytes(9.000001), "text/csv"),
        },
        data={"tolerance": "0.00001"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["passed"] is True
    assert payload["compared_rows"] == 1
    assert payload["compared_cells"] == 1
    assert payload["differences"] == []


def test_upload_validate_csv_reports_differences(client):
    response = client.post(
        "/upload/validate",
        files={
            "expected_file": ("expected.csv", metric_csv_bytes(9.0), "text/csv"),
            "actual_file": ("actual.csv", metric_csv_bytes(10.0), "text/csv"),
        },
        data={"columns": "area_um2"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["passed"] is False
    assert payload["differences"][0]["column"] == "area_um2"
    assert payload["differences"][0]["delta"] == 1.0


def test_upload_analyze_partial_roi_returns_400(client):
    response = client.post(
        "/upload/analyze",
        files={"file": ("stack.tif", stack_upload_bytes(), "image/tiff")},
        data={"threshold": "100", "roi_xmin": "1"},
    )

    assert response.status_code == 400
    assert "ROI requires" in response.json()["detail"]


def test_upload_preview_returns_png(client):
    pytest.importorskip("PIL")

    response = client.post(
        "/upload/preview",
        files={"file": ("stack.tif", stack_upload_bytes(), "image/tiff")},
        data={"threshold": "100", "frame_index": "2", "prefer_opencv": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == "stack.tif"
    assert payload["frame_index"] == 2
    assert payload["method"] == "fallback"
    assert b64decode(payload["image_png_base64"]).startswith(b"\x89PNG")


def test_upload_threshold_returns_suggestion(client):
    response = client.post(
        "/upload/threshold",
        files={"file": ("stack.tif", stack_upload_bytes(), "image/tiff")},
        data={"method": "percentile"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == "stack.tif"
    assert payload["method"] == "percentile"
    assert payload["threshold"] >= 0


def test_upload_sweep_returns_summary_rows(client):
    response = client.post(
        "/upload/sweep",
        files={"file": ("stack.tif", stack_upload_bytes(), "image/tiff")},
        data={
            "start": "50",
            "stop": "250",
            "step": "100",
            "voxel_x_um": "1.0",
            "voxel_y_um": "1.0",
            "voxel_z_um": "1.0",
            "prefer_opencv": "false",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == "stack.tif"
    assert payload["threshold_count"] == 3
    assert payload["best_threshold"] == 50.0
    assert payload["rows"][0]["valid_fraction"] == 1.0
    assert payload["rows"][2]["valid_fraction"] == 0.0


def test_analyze_bad_path_returns_400(client):
    response = client.post("/analyze", json={"path": "missing.tif", "threshold": 100})

    assert response.status_code == 400


def test_analyze_returns_warnings_for_no_contours(client, tmp_path):
    tifffile = pytest.importorskip("tifffile")
    path = tmp_path / "blank.tif"
    tifffile.imwrite(path, np.zeros((2, 8, 8), dtype=np.uint8), photometric="minisblack")

    response = client.post(
        "/analyze",
        json={
            "path": str(path),
            "threshold": 100,
            "voxel": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
            "prefer_opencv": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["warnings"][0]["code"] == "no_valid_contours"
    assert payload["manifest"]["warnings"][0]["code"] == "no_valid_contours"
    assert payload["summary"]["metrics"] == {}
