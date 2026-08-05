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
    assert payload["profiles"] == ["vesicle", "rbc", "active_surfaces"]


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
            "object_seed": {"x": 2.5, "y": 3.5, "frame_index": 1, "radius": 4.0},
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
    warning_codes = {w["code"] for w in payload["warnings"]}
    assert "seeded_adaptive_threshold" in warning_codes
    assert payload["summary"]["metrics"]["area_um2"]["mean"] > 0
    assert payload["manifest"]["summary"]["metrics"]["area_um2"]["mean"] > 0
    assert payload["mesh"] is None
    assert payload["rows"][0]["area_um2"] > 0
    assert payload["rows"][0]["aspect_ratio"] >= 1.0
    assert payload["rows"][0]["extent"] > 0
    assert payload["rows"][0]["solidity"] > 0


def test_analyze_stack_accepts_z_range(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/analyze",
        json={
            "path": str(path),
            "threshold": 100,
            "voxel": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
            "z_range": {"zmin": 1, "zmax": 3},
            "prefer_opencv": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["frame_count"] == 2
    assert payload["manifest"]["z_range"] == {"zmin": 1, "zmax": 3}
    assert [row["frame_index"] for row in payload["rows"]] == [1, 2]


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


def test_mesh_preview_returns_display_geometry(client, tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/mesh-preview",
        json={
            "path": str(path),
            "threshold": 100,
            "voxel": {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0},
            "prefer_opencv": False,
            "downsample": 1,
            "max_faces": 5000,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_mesh"] is True
    assert payload["vertex_count"] == len(payload["vertices"])
    assert payload["face_count"] == len(payload["faces"])
    assert len(payload["vertices"][0]) == 3
    assert len(payload["faces"][0]) == 3
    assert payload["surface_area_um2"] > 0
    assert payload["volume_um3"] > 0


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
    assert isinstance(payload.get("stack_id"), str) and payload["stack_id"]


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
            "object_seed_x": "2.5",
            "object_seed_y": "3.5",
            "object_seed_frame": "1",
            "object_seed_radius": "4.0",
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
    codes = {w["code"] for w in payload["warnings"]}
    assert "slice_volume_stack_boundary" in codes
    assert "sparse_z_sampling" in codes
    assert payload["frame_count"] == 3
    assert payload["valid_frame_count"] == 3
    assert payload["rows"][0]["area_um2"] > 0
    assert payload["rows"][0]["equivalent_diameter_um"] > 0
    # Short stacks touch Z caps → 3D mesh withheld; envelope carries capability.
    assert payload["rbc"] is not None
    assert payload["rbc"]["capability"] in {
        "PIXEL_PREVIEW",
        "2D_OUTER_CONTOUR",
        "3D_OCCUPANCY_VALIDATED",
    }
    if payload["rbc"]["capability"] == "3D_OCCUPANCY_VALIDATED":
        assert payload["mesh"] is not None
        assert payload["mesh"]["surface_area_um2"] > 0
        assert payload["mesh"]["volume_um3"] > 0
    else:
        assert payload["mesh"] is None
        assert payload["rbc"].get("measured") is None or payload["rbc"]["measured"].get(
            "volume_um3"
        ) is None


def test_upload_batch_analyze_returns_summary_rows(client):
    upload_bytes = stack_upload_bytes()
    # Batch has no seed form fields; use vesicle (RBC requires an explicit seed).
    response = client.post(
        "/upload/batch",
        files=[
            ("files", ("stack_a.tif", upload_bytes, "image/tiff")),
            ("files", ("stack_b.tif", upload_bytes, "image/tiff")),
        ],
        data={
            "threshold": "100",
            "profile": "vesicle",
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
    assert payload["rows"][0]["profile"] == "vesicle"
    assert payload["rows"][0]["source_sha256"] == hashlib.sha256(upload_bytes).hexdigest()
    assert payload["rows"][0]["voxel_source"] == "override"
    assert payload["rows"][0]["area_um2_mean"] == 9.0
    assert payload["rows"][0]["deformation_index_mean"] == 0.0


def test_api_refuses_rbc_without_seed(client, tmp_path):
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
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "seed_required"
    assert "mesh" not in response.json()


def test_api_uncalibrated_lsm_runs_estimated_not_measured(client, tmp_path, monkeypatch):
    """Direct .lsm without manual X/Y/Z: disclaimer + ESTIMATED mesh, no MEASURED."""
    import importlib

    from morphostack.core.models import ImageStack, VoxelSize
    from morphostack.core.rbc_models import CalibrationAssessment, CalibrationAxis

    path = tmp_path / "cell.lsm"
    path.write_bytes(b"not-a-real-lsm")
    n, size = 9, 32
    gray = np.zeros((n, size, size), dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    disk = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= 8**2
    for z in range(1, n - 1):
        gray[z][disk] = 210
    color = np.zeros((n, size, size, 3), dtype=np.uint8)
    fake = ImageStack(
        source_path=path,
        grayscale=gray,
        color=color,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        voxel_source="default",
        calibration=CalibrationAssessment(
            x=CalibrationAxis(1.0, "default", False),
            y=CalibrationAxis(1.0, "default", False),
            z=CalibrationAxis(1.0, "default", False),
            source_format="lsm",
        ),
    )

    def _fake_resolve(*args, **kwargs):
        return fake, "deadbeef"

    app_module = importlib.import_module("morphostack.api.app")
    monkeypatch.setattr(app_module, "resolve_stack", _fake_resolve)
    response = client.post(
        "/analyze",
        json={
            "path": str(path),
            "threshold": 100,
            "profile": "rbc",
            "prefer_opencv": False,
            "include_mesh": True,
            "object_seed": {"x": 16.0, "y": 16.0, "frame_index": 4, "radius": 12.0},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    rbc = payload["rbc"]
    assert rbc is not None
    assert "lsm_requires_conversion_or_manual_calibration" in rbc["qc_issues"]
    assert rbc["authority"] == "ESTIMATED"
    assert rbc["measured"] is None
    assert rbc["estimated"] is not None
    assert rbc["estimated"]["authority"] == "ESTIMATED"
    assert any(
        "lsm" in str(w.get("message", "")).lower() or w.get("code") == "rbc_calibration_disclaimer"
        for w in payload["warnings"]
    )
    # Mesh may be present only as ESTIMATED display.
    if payload.get("mesh") is not None:
        assert payload.get("mesh_authority") == "ESTIMATED"


def test_api_rbc_estimate_unavailable_until_registered(client):
    response = client.post("/rbc/estimate", json={})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "rbc_estimator_not_validated"


def test_api_rbc_analyze_includes_envelope(client, tmp_path):
    tifffile = pytest.importorskip("tifffile")
    path = tmp_path / "rbc.tif"
    n, size = 9, 48
    stack = np.zeros((n, size, size), dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    disk = (yy - size // 2) ** 2 + (xx - size // 2) ** 2 <= 12**2
    for z in range(1, n - 1):
        stack[z][disk] = 210
    tifffile.imwrite(path, stack, photometric="minisblack")
    response = client.post(
        "/analyze",
        json={
            "path": str(path),
            "threshold": 100,
            "profile": "rbc",
            "voxel": {"x_um": 0.1, "y_um": 0.1, "z_um": 0.2},
            "prefer_opencv": False,
            "include_mesh": True,
            "object_seed": {"x": 24.0, "y": 24.0, "frame_index": 4, "radius": 16.0},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "rbc" in payload and payload["rbc"] is not None
    assert payload["rbc"]["authority"] in {"MEASURED", "WITHHELD"}
    assert "qc_issues" in payload["rbc"]
    assert payload["manifest"]["rbc"]["capability"] == payload["rbc"]["capability"]
    # No unlabeled estimated block in production.
    assert payload["rbc"]["estimated"] is None
    measured = payload["rbc"].get("measured")
    if measured is None or measured.get("volume_um3") is None:
        assert payload["mesh"] is None


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


def test_upload_validate_csv_can_compare_all_columns(client):
    response = client.post(
        "/upload/validate",
        files={
            "expected_file": ("expected.csv", b"frame_index,area_um2,source_sha256\n0,9.0,abc\n", "text/csv"),
            "actual_file": ("actual.csv", b"frame_index,area_um2,source_sha256\n0,9.0,def\n", "text/csv"),
        },
        data={"all_columns": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["passed"] is False
    assert payload["differences"][0]["column"] == "source_sha256"
    assert payload["differences"][0]["expected"] == "abc"
    assert payload["differences"][0]["actual"] == "def"


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


def test_upload_inspect_no_voxel_defaults_to_metadata(client):
    response = client.post(
        "/upload/inspect",
        files={"file": ("stack.tif", stack_upload_bytes(), "image/tiff")},
        data={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["voxel_source"] == "metadata"
    assert payload["voxel_size"] == {"x_um": 1.0, "y_um": 1.0, "z_um": 1.0}


def test_upload_inspect_partial_voxel_returns_400(client):
    response = client.post(
        "/upload/inspect",
        files={"file": ("stack.tif", stack_upload_bytes(), "image/tiff")},
        data={"voxel_x_um": "0.1", "voxel_y_um": "0.2"},
    )

    assert response.status_code == 400
    assert "Partial voxel override" in response.json()["detail"]


def test_preview_with_z_range_accepts_global_frame_index(client, tmp_path):
    pytest.importorskip("PIL")
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 1,
            "z_range": {"zmin": 0, "zmax": 2},
            "prefer_opencv": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["frame_index"] == 1


def test_preview_roi_returns_cropped_dimensions(client, tmp_path):
    pytest.importorskip("PIL")
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 1,
            "roi": {"xmin": 1, "xmax": 5, "ymin": 2, "ymax": 6},
            "prefer_opencv": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["frame_index"] == 1
    assert payload["width"] == 4
    assert payload["height"] == 4
    assert b64decode(payload["image_png_base64"]).startswith(b"\x89PNG")


def test_preview_path_does_not_call_full_stack_apply_rect_roi(client, tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    import importlib

    # Package re-exports FastAPI as morphostack.api.app; load the real module.
    api_app_module = importlib.import_module("morphostack.api.app")
    path = tmp_path / "stack.tif"
    write_stack(path)

    def _boom(*_args, **_kwargs):
        raise AssertionError("preview path must not call full-stack apply_rect_roi")

    monkeypatch.setattr(api_app_module, "apply_rect_roi", _boom)

    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 0,
            "roi": {"xmin": 1, "xmax": 6, "ymin": 1, "ymax": 6},
            "prefer_opencv": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["width"] == 5
    assert response.json()["height"] == 5


def test_mesh_export_writes_obj_with_seed_and_z_range(client, tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    from test_core_object_seed import write_two_circle_tiff

    path = tmp_path / "two_circle.tif"
    write_two_circle_tiff(path)
    destination = tmp_path / "exported.obj"

    response = client.post(
        "/mesh-export",
        json={
            "path": str(path),
            "threshold": 100,
            "z_range": {"zmin": 0, "zmax": 3},
            "object_seed": {"x": 60, "y": 20, "frame_index": 1, "radius": 10},
            "prefer_opencv": True,
            "destination": str(destination),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "obj"
    assert payload["face_count"] > 0
    assert destination.exists()
    obj_text = destination.read_text(encoding="utf-8")
    assert obj_text.startswith("# MorphoStack mesh export\n")
    assert "v " in obj_text
    assert "f " in obj_text
    assert payload["object_seed"]["x"] == 60
    assert payload["tracking"] is not None


def test_upload_session_then_preview_by_stack_id(client):
    pytest.importorskip("PIL")
    open_response = client.post(
        "/upload/session",
        files={"file": ("session_stack.tif", stack_upload_bytes(), "image/tiff")},
        data={"voxel_x_um": "1.0", "voxel_y_um": "1.0", "voxel_z_um": "1.0"},
    )
    assert open_response.status_code == 200
    opened = open_response.json()
    stack_id = opened["stack_id"]
    assert opened["source_path"] == "session_stack.tif"
    assert opened["grayscale_shape"] == [3, 8, 8]
    assert opened["voxel_source"] == "override"

    preview = client.post(
        "/preview",
        json={
            "stack_id": stack_id,
            "threshold": 100,
            "frame_index": 1,
            "prefer_opencv": False,
        },
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["source_path"] == "session_stack.tif"
    assert payload["frame_index"] == 1
    assert b64decode(payload["image_png_base64"]).startswith(b"\x89PNG")

    threshold = client.post(
        "/threshold",
        json={"stack_id": stack_id, "method": "percentile"},
    )
    assert threshold.status_code == 200
    assert threshold.json()["threshold"] >= 0


def _write_ring_stack(path, *, n: int = 8, h: int = 64, w: int = 64, cx: int = 32, cy: int = 32):
    tifffile = pytest.importorskip("tifffile")
    yy, xx = np.ogrid[:h, :w]
    stack = np.zeros((n, h, w), dtype=np.uint8)
    for z in range(n):
        d = (xx - cx) ** 2 + (yy - cy) ** 2
        stack[z][((d >= 10**2) & (d <= 14**2))] = 200
    tifffile.imwrite(path, stack, photometric="minisblack")
    return path


def test_preview_caching_reuses_results(client, tmp_path, monkeypatch):
    """Two previews with same seed / different frames: second uses extend path."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")

    from morphostack.core.seeded_vesicle import (
        extend_track as real_extend,
        track_seeded_vesicle_stack as real_track,
    )
    from morphostack.core.stack_cache import default_tracking_cache
    import morphostack.core.seeded_vesicle as sv

    default_tracking_cache.clear()
    calls = {"track": 0, "extend": 0}

    def counting_track(*args, **kwargs):
        calls["track"] += 1
        return real_track(*args, **kwargs)

    def counting_extend(*args, **kwargs):
        calls["extend"] += 1
        return real_extend(*args, **kwargs)

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", counting_track)
    monkeypatch.setattr(sv, "extend_track", counting_extend)

    path = _write_ring_stack(tmp_path / "ring_stack.tif")

    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}
    # Diagnostic sync path still exercises extend-from-cache identity.
    r1 = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 2,
            "object_seed": seed,
            "prefer_opencv": False,
            "force_sync_exact": True,
        },
    )
    assert r1.status_code == 200
    p1 = r1.json()
    assert b64decode(p1["image_png_base64"]).startswith(b"\x89PNG")
    assert p1["preview_quality"] == "exact"
    assert p1["cache_hit"] is False
    assert calls["track"] == 1
    assert calls["extend"] == 0

    r2 = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 5,
            "object_seed": seed,
            "prefer_opencv": False,
            "force_sync_exact": True,
        },
    )
    assert r2.status_code == 200
    p2 = r2.json()
    assert b64decode(p2["image_png_base64"]).startswith(b"\x89PNG")
    assert p2["preview_quality"] == "exact"
    assert p2["cache_hit"] is True
    # Second request must extend from cache, not full re-walk from seed.
    assert calls["extend"] == 1
    assert calls["track"] == 1
    assert len(default_tracking_cache) >= 1


def test_fast_preview_is_provisional_and_skips_tracker(client, tmp_path, monkeypatch):
    """fast_preview=true stays one-plane provisional and never runs seeded Z track."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")

    import morphostack.core.seeded_vesicle as sv
    from morphostack.core.stack_cache import default_tracking_cache

    default_tracking_cache.clear()
    calls = {"track": 0, "extend": 0}

    def boom_track(*_a, **_k):
        calls["track"] += 1
        raise AssertionError("fast provisional path must not call track_seeded_vesicle_stack")

    def boom_extend(*_a, **_k):
        calls["extend"] += 1
        raise AssertionError("fast provisional path must not call extend_track")

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", boom_track)
    monkeypatch.setattr(sv, "extend_track", boom_extend)

    path = _write_ring_stack(tmp_path / "fast_ring.tif")
    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}
    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 3,
            "object_seed": seed,
            "prefer_opencv": False,
            "fast_preview": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_quality"] == "provisional"
    assert payload["cache_hit"] is False
    assert payload["frame_index"] == 3
    assert b64decode(payload["image_png_base64"]).startswith(b"\x89PNG")
    assert calls["track"] == 0
    assert calls["extend"] == 0
    assert len(default_tracking_cache) == 0


def test_exact_preview_uses_tracker_and_marks_quality(client, tmp_path, monkeypatch):
    """Diagnostic sync exact path still marks quality=exact and runs tracker once."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")

    from morphostack.core.seeded_vesicle import track_seeded_vesicle_stack as real_track
    from morphostack.core.stack_cache import default_tracking_cache
    import morphostack.core.seeded_vesicle as sv

    default_tracking_cache.clear()
    calls = {"track": 0}

    def counting_track(*args, **kwargs):
        calls["track"] += 1
        return real_track(*args, **kwargs)

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", counting_track)

    path = _write_ring_stack(tmp_path / "exact_ring.tif")
    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}
    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 2,
            "object_seed": seed,
            "prefer_opencv": False,
            "fast_preview": False,
            "force_sync_exact": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_quality"] == "exact"
    assert payload["cache_hit"] is False
    assert calls["track"] == 1
    assert b64decode(payload["image_png_base64"]).startswith(b"\x89PNG")


def test_tracking_cache_not_reused_across_roi_or_source(client, tmp_path, monkeypatch):
    """Cache entries must not be reused when ROI or stack identity changes."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")

    from morphostack.core.seeded_vesicle import (
        extend_track as real_extend,
        track_seeded_vesicle_stack as real_track,
    )
    from morphostack.core.stack_cache import default_tracking_cache
    import morphostack.core.seeded_vesicle as sv

    default_tracking_cache.clear()
    calls = {"track": 0, "extend": 0}

    def counting_track(*args, **kwargs):
        calls["track"] += 1
        return real_track(*args, **kwargs)

    def counting_extend(*args, **kwargs):
        calls["extend"] += 1
        return real_extend(*args, **kwargs)

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", counting_track)
    monkeypatch.setattr(sv, "extend_track", counting_extend)

    path_a = _write_ring_stack(tmp_path / "cache_a.tif")
    path_b = _write_ring_stack(tmp_path / "cache_b.tif")
    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}

    r1 = client.post(
        "/preview",
        json={
            "path": str(path_a),
            "threshold": 100,
            "frame_index": 2,
            "object_seed": seed,
            "prefer_opencv": False,
            "force_sync_exact": True,
        },
    )
    assert r1.status_code == 200
    assert r1.json()["cache_hit"] is False
    assert calls["track"] == 1

    # Same seed/frame but different source path → full track again, not extend.
    r2 = client.post(
        "/preview",
        json={
            "path": str(path_b),
            "threshold": 100,
            "frame_index": 2,
            "object_seed": seed,
            "prefer_opencv": False,
            "force_sync_exact": True,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["cache_hit"] is False
    assert calls["track"] == 2
    assert calls["extend"] == 0

    # Same source, different ROI → must not hit previous full-field cache.
    r3 = client.post(
        "/preview",
        json={
            "path": str(path_a),
            "threshold": 100,
            "frame_index": 2,
            "object_seed": {"x": 16, "y": 16, "frame_index": 0, "radius": 14},
            "roi": {"xmin": 16, "xmax": 48, "ymin": 16, "ymax": 48},
            "prefer_opencv": False,
            "force_sync_exact": True,
        },
    )
    assert r3.status_code == 200
    assert r3.json()["cache_hit"] is False
    assert calls["track"] == 3


def test_preview_quality_distinguishes_provisional_vs_exact(client, tmp_path):
    """Response metadata must distinguish provisional vs exact overlays."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    path = _write_ring_stack(tmp_path / "quality_ring.tif")
    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}
    body = {
        "path": str(path),
        "threshold": 100,
        "frame_index": 1,
        "object_seed": seed,
        "prefer_opencv": False,
    }
    fast = client.post("/preview", json={**body, "fast_preview": True})
    exact = client.post("/preview", json={**body, "fast_preview": False, "force_sync_exact": True})
    assert fast.status_code == 200
    assert exact.status_code == 200
    assert fast.json()["preview_quality"] == "provisional"
    assert exact.json()["preview_quality"] == "exact"
    assert fast.json()["preview_quality"] != exact.json()["preview_quality"]


def test_tracking_cache_miss_when_file_revision_changes(client, tmp_path, monkeypatch):
    """Same path with replaced pixels/mtime must not reuse tracking cache."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    tifffile = pytest.importorskip("tifffile")

    from morphostack.core.seeded_vesicle import track_seeded_vesicle_stack as real_track
    from morphostack.core.stack_cache import default_tracking_cache, default_stack_cache
    import morphostack.core.seeded_vesicle as sv
    import time

    default_tracking_cache.clear()
    default_stack_cache.clear()
    calls = {"track": 0}

    def counting_track(*args, **kwargs):
        calls["track"] += 1
        return real_track(*args, **kwargs)

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", counting_track)

    path = _write_ring_stack(tmp_path / "rev_ring.tif", cx=32, cy=32)
    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}
    body = {
        "path": str(path),
        "threshold": 100,
        "frame_index": 2,
        "object_seed": seed,
        "prefer_opencv": False,
        "fast_preview": False,
        "force_sync_exact": True,
    }
    r1 = client.post("/preview", json=body)
    assert r1.status_code == 200
    assert r1.json()["cache_hit"] is False
    assert calls["track"] == 1

    # Replace file contents and bump mtime so path_source_identity changes.
    time.sleep(0.02)
    _write_ring_stack(path, cx=40, cy=40)
    # Ensure mtime differs even on coarse FS timestamps.
    path.touch()
    default_stack_cache.clear()

    r2 = client.post("/preview", json={**body, "object_seed": {"x": 40, "y": 40, "frame_index": 0, "radius": 14}})
    assert r2.status_code == 200
    # New source revision + different seed → full track, not cache hit.
    assert r2.json()["cache_hit"] is False
    assert calls["track"] == 2


def test_tracking_cache_miss_for_subpixel_distinct_seeds(client, tmp_path, monkeypatch):
    """Sub-pixel distinct seeds must not share a tracking cache entry."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")

    from morphostack.core.seeded_vesicle import track_seeded_vesicle_stack as real_track
    from morphostack.core.stack_cache import default_tracking_cache
    import morphostack.core.seeded_vesicle as sv

    default_tracking_cache.clear()
    calls = {"track": 0}

    def counting_track(*args, **kwargs):
        calls["track"] += 1
        return real_track(*args, **kwargs)

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", counting_track)
    path = _write_ring_stack(tmp_path / "subpx.tif")

    r1 = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 2,
            "object_seed": {"x": 32.10, "y": 32.10, "frame_index": 0, "radius": 14.10},
            "prefer_opencv": False,
            "force_sync_exact": True,
        },
    )
    r2 = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 2,
            "object_seed": {"x": 32.49, "y": 32.49, "frame_index": 0, "radius": 14.49},
            "prefer_opencv": False,
            "force_sync_exact": True,
        },
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["cache_hit"] is False
    assert r2.json()["cache_hit"] is False
    assert calls["track"] == 2


def test_multipart_upload_preview_does_not_share_tracking_cache(client, tmp_path, monkeypatch):
    """Distinct multipart uploads must not reuse tracking results via content sample."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    tifffile = pytest.importorskip("tifffile")

    from morphostack.core.seeded_vesicle import track_seeded_vesicle_stack as real_track
    from morphostack.core.stack_cache import default_tracking_cache
    import morphostack.core.seeded_vesicle as sv

    default_tracking_cache.clear()
    calls = {"track": 0}

    def counting_track(*args, **kwargs):
        calls["track"] += 1
        return real_track(*args, **kwargs)

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", counting_track)

    def ring_bytes(cx: int) -> bytes:
        h, w, n = 48, 48, 4
        yy, xx = np.ogrid[:h, :w]
        stack = np.zeros((n, h, w), dtype=np.uint8)
        for z in range(n):
            d = (xx - cx) ** 2 + (yy - 24) ** 2
            stack[z][((d >= 8**2) & (d <= 12**2))] = 200
        buf = BytesIO()
        tifffile.imwrite(buf, stack, photometric="minisblack")
        return buf.getvalue()

    data = {
        "threshold": "100",
        "frame_index": "1",
        "object_seed_x": "24",
        "object_seed_y": "24",
        "object_seed_frame": "0",
        "object_seed_radius": "12",
        "prefer_opencv": "false",
    }
    r1 = client.post(
        "/upload/preview",
        files={"file": ("a.tif", ring_bytes(24), "image/tiff")},
        data=data,
    )
    r2 = client.post(
        "/upload/preview",
        files={"file": ("b.tif", ring_bytes(28), "image/tiff")},
        data={**data, "object_seed_x": "28"},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    # Each multipart request must track fresh (no cross-upload cache).
    assert calls["track"] == 2
    assert len(default_tracking_cache) == 0


def test_exact_subscription_starts_one_job_for_rapid_scrub(client, tmp_path):
    """Ten uncached exact frames → one tracking job writer, not ten sync walks."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    import time

    from morphostack.core.stack_cache import default_tracking_cache

    default_tracking_cache.clear()
    path = _write_ring_stack(tmp_path / "scrub_ring.tif", n=12)
    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}
    job_ids: set[str] = set()
    for frame in range(1, 11):
        r = client.post(
            "/preview",
            json={
                "path": str(path),
                "threshold": 100,
                "frame_index": frame,
                "object_seed": seed,
                "prefer_opencv": False,
                "fast_preview": False,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Until published, exact path is pending (provisional paint + job).
        if not body.get("exact_available"):
            assert body["preview_quality"] == "provisional"
            assert body.get("exact_pending") is True
            job = body.get("tracking_job") or {}
            assert job.get("job_id")
            job_ids.add(str(job["job_id"]))
        else:
            assert body["preview_quality"] == "exact"
            job = body.get("tracking_job")
            if job and job.get("job_id"):
                job_ids.add(str(job["job_id"]))
    # Single-flight: at most one job id across the scrub.
    assert len(job_ids) <= 1
    # Wait for completion and confirm target frames become exact cache hits.
    if job_ids:
        jid = next(iter(job_ids))
        deadline = time.time() + 60
        state = "running"
        while state not in ("complete", "cancelled", "failed") and time.time() < deadline:
            time.sleep(0.05)
            st = client.get(f"/tracking/jobs/{jid}")
            assert st.status_code == 200
            state = st.json()["state"]
        assert state == "complete"
    r_hit = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 5,
            "object_seed": seed,
            "prefer_opencv": False,
            "fast_preview": False,
        },
    )
    assert r_hit.status_code == 200
    hit = r_hit.json()
    assert hit["exact_available"] is True
    assert hit["preview_quality"] == "exact"
    assert hit["cache_hit"] is True


def test_exact_subscription_no_sync_walk_without_force_flag(client, tmp_path, monkeypatch):
    """Default exact preview must not call track/extend on the request thread."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    import morphostack.core.seeded_vesicle as sv
    from morphostack.core.stack_cache import default_tracking_cache

    default_tracking_cache.clear()
    calls = {"track": 0, "extend": 0}

    def boom_track(*_a, **_k):
        calls["track"] += 1
        raise AssertionError("request-thread must not call track_seeded_vesicle_stack")

    def boom_extend(*_a, **_k):
        calls["extend"] += 1
        raise AssertionError("request-thread must not call extend_track")

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", boom_track)
    monkeypatch.setattr(sv, "extend_track", boom_extend)

    path = _write_ring_stack(tmp_path / "nosync.tif")
    r = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 3,
            "object_seed": {"x": 32, "y": 32, "frame_index": 0, "radius": 14},
            "prefer_opencv": False,
            "fast_preview": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Job worker uses its own track_fn reference (captured at service start), so
    # request-thread boom must not fire even if worker tracks.
    assert calls["track"] == 0
    assert calls["extend"] == 0
    assert body.get("tracking_job") is not None or body.get("exact_available") is True


def test_upload_session_exact_subscription_one_job_no_request_thread_track(
    client, tmp_path, monkeypatch
):
    """Browser upload path: session + stack_id scrub → one job, no sync track on request thread."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    import time

    import morphostack.core.seeded_vesicle as sv
    from morphostack.core.stack_cache import default_tracking_cache

    default_tracking_cache.clear()
    calls = {"track": 0, "extend": 0}

    def boom_track(*_a, **_k):
        calls["track"] += 1
        raise AssertionError("request-thread must not call track_seeded_vesicle_stack")

    def boom_extend(*_a, **_k):
        calls["extend"] += 1
        raise AssertionError("request-thread must not call extend_track")

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", boom_track)
    monkeypatch.setattr(sv, "extend_track", boom_extend)

    path = _write_ring_stack(tmp_path / "upload_scrub.tif", n=12)
    with path.open("rb") as fh:
        sess = client.post(
            "/upload/session",
            files={"file": ("upload_scrub.tif", fh, "image/tiff")},
        )
    assert sess.status_code == 200, sess.text
    stack_id = sess.json()["stack_id"]
    assert stack_id

    seed = {"x": 32, "y": 32, "frame_index": 0, "radius": 14}
    job_ids: set[str] = set()

    # JSON /preview with stack_id (browser after ensureUploadSession).
    for frame in range(1, 11):
        r = client.post(
            "/preview",
            json={
                "stack_id": stack_id,
                "threshold": 100,
                "frame_index": frame,
                "object_seed": seed,
                "prefer_opencv": False,
                "fast_preview": False,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert calls["track"] == 0
        assert calls["extend"] == 0
        job = body.get("tracking_job") or {}
        jid = job.get("job_id")
        if jid:
            assert str(jid).strip()  # nonzero / non-empty
            job_ids.add(str(jid))
        if body.get("exact_available"):
            assert body["preview_quality"] == "exact"
        else:
            assert body["preview_quality"] == "provisional"
            assert body.get("exact_pending") is True
            assert jid

    assert len(job_ids) == 1
    jid = next(iter(job_ids))
    deadline = time.time() + 60
    state = "running"
    while state not in ("complete", "cancelled", "failed") and time.time() < deadline:
        time.sleep(0.05)
        st = client.get(f"/tracking/jobs/{jid}")
        assert st.status_code == 200
        state = st.json()["state"]
    assert state == "complete"

    # Multipart /upload/preview with same stack_id shares session identity + cache.
    form = {
        "stack_id": stack_id,
        "threshold": "100",
        "frame_index": "5",
        "object_seed_x": "32",
        "object_seed_y": "32",
        "object_seed_frame": "0",
        "object_seed_radius": "14",
        "prefer_opencv": "false",
        "fast_preview": "false",
    }
    up = client.post("/upload/preview", data=form)
    assert up.status_code == 200, up.text
    up_body = up.json()
    assert calls["track"] == 0
    assert calls["extend"] == 0
    assert up_body["exact_available"] is True
    assert up_body["preview_quality"] == "exact"
    assert up_body["cache_hit"] is True
    # Session key still serves hits after multipart form path.
    r_hit = client.post(
        "/preview",
        json={
            "stack_id": stack_id,
            "threshold": 100,
            "frame_index": 5,
            "object_seed": seed,
            "prefer_opencv": False,
            "fast_preview": False,
        },
    )
    assert r_hit.status_code == 200
    assert r_hit.json()["cache_hit"] is True
    assert r_hit.json()["exact_available"] is True

    # Rapid scrub via /upload/preview + stack_id still one job writer.
    job_ids2: set[str] = set()
    default_tracking_cache.clear()
    # New stack_id so cache is cold but same policy:
    path2 = _write_ring_stack(tmp_path / "upload_scrub2.tif", n=12)
    with path2.open("rb") as fh:
        sess2 = client.post(
            "/upload/session",
            files={"file": ("upload_scrub2.tif", fh, "image/tiff")},
        )
    sid2 = sess2.json()["stack_id"]
    for frame in range(1, 11):
        r = client.post(
            "/upload/preview",
            data={
                "stack_id": sid2,
                "threshold": "100",
                "frame_index": str(frame),
                "object_seed_x": "32",
                "object_seed_y": "32",
                "object_seed_frame": "0",
                "object_seed_radius": "14",
                "prefer_opencv": "false",
                "fast_preview": "false",
            },
        )
        assert r.status_code == 200, r.text
        assert calls["track"] == 0
        body = r.json()
        job = body.get("tracking_job") or {}
        if job.get("job_id"):
            job_ids2.add(str(job["job_id"]))
    assert len(job_ids2) == 1
    assert next(iter(job_ids2)).strip()


def test_path_fast_preview_skips_full_file_sha(client, tmp_path, monkeypatch):
    """Path-mode fast_preview must not call full-file SHA (keeps scrub cheap)."""
    pytest.importorskip("PIL")
    import importlib

    # Package re-exports FastAPI as morphostack.api.app; load the real module.
    api_app_module = importlib.import_module("morphostack.api.app")
    path = _write_ring_stack(tmp_path / "sha_fast.tif")
    calls = {"sha": 0}

    def boom_sha(*_a, **_k):
        calls["sha"] += 1
        raise AssertionError("fast_preview path must not compute full-file SHA")

    monkeypatch.setattr(api_app_module, "file_sha256", boom_sha)
    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 100,
            "frame_index": 0,
            "fast_preview": True,
            "prefer_opencv": False,
        },
    )
    assert response.status_code == 200
    assert calls["sha"] == 0


def test_should_apply_preview_stale_generation_rule():
    """Pure stale-response rule: older gen never replaces newer; provisional never overwrites exact."""
    # Mirrors apps/web/src/main.ts shouldApplyPreview without a frontend test runner.
    def should_apply(
        gen: int,
        current_gen: int,
        frame_index: int,
        quality: str,
        last: dict | None,
    ) -> bool:
        if gen != current_gen:
            return False
        if (
            last
            and last["gen"] == gen
            and last["frameIndex"] == frame_index
            and last["quality"] == "exact"
            and quality == "provisional"
        ):
            return False
        return True

    # Frame A (gen 1) must not apply after user moved to gen 2.
    assert should_apply(1, 2, 0, "exact", None) is False
    # Newest gen always applies when nothing rendered yet.
    assert should_apply(2, 2, 5, "provisional", None) is True
    # Exact for frame B wins.
    last = {"gen": 2, "frameIndex": 5, "quality": "exact"}
    assert should_apply(2, 2, 5, "exact", last) is True
    # Late provisional for same frame must not replace exact.
    assert should_apply(2, 2, 5, "provisional", last) is False
    # Provisional for a different frame under same gen is allowed only if gen matches
    # (UI re-bumps gen on each schedule, so this is defensive).
    assert should_apply(2, 2, 6, "provisional", last) is True


def test_preview_unknown_stack_id_returns_400(client):
    response = client.post(
        "/preview",
        json={
            "stack_id": "00000000-0000-0000-0000-000000000000",
            "threshold": 100,
            "frame_index": 0,
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "stack_id" in detail
    assert "expired" in detail.lower() or "unknown" in detail.lower()


def test_preview_requires_path_or_stack_id(client):
    response = client.post(
        "/preview",
        json={"threshold": 100, "frame_index": 0},
    )
    assert response.status_code == 400
    assert "path or stack_id" in response.json()["detail"].lower()


def test_upload_session_analyze_by_stack_id(client):
    open_response = client.post(
        "/upload/session",
        files={"file": ("analyze_session.tif", stack_upload_bytes(), "image/tiff")},
        data={"voxel_x_um": "1.0", "voxel_y_um": "1.0", "voxel_z_um": "1.0"},
    )
    assert open_response.status_code == 200
    stack_id = open_response.json()["stack_id"]

    response = client.post(
        "/analyze",
        json={
            "stack_id": stack_id,
            "threshold": 100,
            "profile": "vesicle",
            "prefer_opencv": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == "analyze_session.tif"
    assert payload["frame_count"] == 3
    assert payload["valid_frame_count"] == 3


def test_mesh_preview_active_surfaces_without_seed_returns_400(client, tmp_path):
    """Experimental mesh must fail fast without Select Object (no long hang)."""
    path = tmp_path / "stack.tif"
    write_stack(path)

    response = client.post(
        "/mesh-preview",
        json={
            "path": str(path),
            "threshold": 100,
            "profile": "active_surfaces",
            "prefer_opencv": False,
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "seed" in detail


def test_upload_session_mesh_preview_by_stack_id(client):
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    open_response = client.post(
        "/upload/session",
        files={"file": ("mesh_session.tif", stack_upload_bytes(), "image/tiff")},
        data={"voxel_x_um": "1.0", "voxel_y_um": "1.0", "voxel_z_um": "1.0"},
    )
    assert open_response.status_code == 200
    stack_id = open_response.json()["stack_id"]

    response = client.post(
        "/mesh-preview",
        json={
            "stack_id": stack_id,
            "threshold": 100,
            "profile": "vesicle",
            "prefer_opencv": False,
            "downsample": 1,
            "max_faces": 5000,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == "mesh_session.tif"
    assert payload["has_mesh"] is True
    assert payload["vertex_count"] > 0

