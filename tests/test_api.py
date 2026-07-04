from __future__ import annotations

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


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


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


def test_analyze_stack_without_mesh(client, tmp_path):
    path = tmp_path / "stack.tif"
    write_stack(path)

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
    assert payload["frame_count"] == 3
    assert payload["valid_frame_count"] == 3
    assert payload["mesh"] is None
    assert payload["rows"][0]["area_um2"] == 9.0


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


def test_analyze_bad_path_returns_400(client):
    response = client.post("/analyze", json={"path": "missing.tif", "threshold": 100})

    assert response.status_code == 400
