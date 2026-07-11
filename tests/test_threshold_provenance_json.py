"""JSON-safe threshold provenance (no NaN; explicit requested/effective/semantics)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from morphostack.api import create_app
from morphostack.core import VoxelSize, analyze_stack
from morphostack.core.export import (
    analysis_manifest,
    analysis_report_markdown,
    analysis_rows,
    analysis_run_warnings,
)
from morphostack.core.pipeline import ObjectSeed, threshold_provenance
from morphostack.core.seeded_vesicle import SeededSliceResult


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _ring_stack(n: int = 3, h: int = 64, w: int = 64) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - 32) ** 2 + (yy - 32) ** 2
    ring = ((d >= 10**2) & (d <= 14**2)).astype(np.float64)
    return np.stack([ring * 200.0 for _ in range(n)], axis=0)


def _write_ring(path, **kwargs):
    tifffile = pytest.importorskip("tifffile")
    tifffile.imwrite(path, _ring_stack(**kwargs).astype(np.uint8), photometric="minisblack")
    return path


def test_threshold_provenance_helper_no_nan():
    p = threshold_provenance(
        requested=42.0,
        method="polar_dp",
        effective=None,
        ok=True,
        seeded=True,
    )
    assert p["effective_threshold"] is None
    assert p["threshold"] is None
    assert p["threshold_semantics"] == "polar_ridge"
    assert p["requested_threshold"] == 42.0
    # JSON serializable
    json.dumps(p)

    fail = threshold_provenance(
        requested=99.0,
        method="circle_seed_gap",
        effective=None,
        ok=False,
        seeded=True,
    )
    assert fail["threshold_semantics"] == "seeded_unavailable"
    assert fail["effective_threshold"] is None
    assert fail["threshold"] is None
    assert fail["requested_threshold"] == 99.0


def test_exact_polar_preview_serializes_null_effective(client, tmp_path, monkeypatch):
    """Exact polar path must not emit NaN (Starlette JSON rejects it)."""
    pytest.importorskip("PIL")
    pytest.importorskip("skimage")
    path = _write_ring(tmp_path / "polar.tif")

    from morphostack.core import seeded_vesicle as sv

    def fake_track(*_a, **_k):
        yy, xx = np.ogrid[:64, :64]
        mask = (xx - 32) ** 2 + (yy - 32) ** 2 <= 12**2
        theta = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        contour = np.column_stack([32 + 12 * np.cos(theta), 32 + 12 * np.sin(theta)])
        return [
            SeededSliceResult(
                contour_xy=contour,
                solid_mask=mask,
                center_xy=(32.0, 32.0),
                area_px=100.0,
                perimeter_px=40.0,
                method="polar_dp",
                ok=True,
                effective_threshold=None,
            )
            for _ in range(3)
        ]

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", fake_track)
    monkeypatch.setattr(sv, "extend_track", lambda *a, **k: fake_track())

    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 77.0,
            "frame_index": 1,
            "object_seed": {"x": 32, "y": 32, "frame_index": 0, "radius": 14},
            "prefer_opencv": False,
            "fast_preview": False,
        },
    )
    assert response.status_code == 200, response.text
    # Must be strict JSON (no NaN tokens).
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["threshold_semantics"] == "polar_ridge"
    assert payload["effective_threshold"] is None
    assert payload["requested_threshold"] == 77.0
    assert payload["threshold"] is None  # legacy does not claim UI gate
    assert payload["preview_quality"] == "exact"


def test_exact_seeded_failed_frame_never_claims_ui_slider(client, tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    path = _write_ring(tmp_path / "fail.tif")
    from morphostack.core import seeded_vesicle as sv

    def fake_track(*_a, **_k):
        return [
            SeededSliceResult(
                None, None, (32.0, 32.0), 0.0, 0.0, "circle_seed_gap", False, effective_threshold=None
            )
            for _ in range(3)
        ]

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", fake_track)
    monkeypatch.setattr(sv, "extend_track", lambda *a, **k: fake_track())

    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 55.0,
            "frame_index": 1,
            "object_seed": {"x": 32, "y": 32, "frame_index": 0, "radius": 14},
            "prefer_opencv": False,
            "fast_preview": False,
        },
    )
    assert response.status_code == 200
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["threshold_semantics"] == "seeded_unavailable"
    assert payload["effective_threshold"] is None
    assert payload["requested_threshold"] == 55.0
    assert payload["threshold"] is None


def test_adaptive_seeded_frame_separates_requested_and_effective():
    stack = _ring_stack()
    seed = ObjectSeed(x=32, y=32, frame_index=0, radius=14.0)
    analysis = analyze_stack(
        stack,
        thresholds=42.0,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=seed,
        profile="vesicle",
    )
    valid = [f for f in analysis.frames if f.contour is not None]
    assert valid
    f0 = valid[0]
    assert f0.requested_threshold == 42.0
    assert f0.effective_threshold is not None
    assert math.isfinite(f0.effective_threshold)
    assert abs(float(f0.effective_threshold) - 42.0) > 1.0
    assert f0.threshold_semantics == "seeded_adaptive_local"
    # Legacy threshold mirrors effective, not UI.
    assert f0.threshold == f0.effective_threshold

    rows = analysis_rows(analysis)
    row = next(r for r in rows if r["has_contour"])
    assert float(row["requested_threshold"]) == 42.0
    assert row["effective_threshold"] != ""
    assert abs(float(row["effective_threshold"]) - 42.0) > 1.0
    assert row["threshold_semantics"] == "seeded_adaptive_local"
    # Legacy column still present and equals effective.
    assert float(row["threshold"]) == float(row["effective_threshold"])

    manifest = analysis_manifest(analysis, source_path="ring.tif", threshold=42.0, object_seed=seed)
    assert manifest["requested_threshold"] == 42.0
    assert "threshold_field_notes" in manifest
    assert "threshold" in manifest  # legacy root key

    report = analysis_report_markdown(
        analysis, source_path="ring.tif", threshold=42.0, object_seed=seed
    )
    assert "Requested threshold" in report
    assert "effective_threshold" in report


def test_provisional_preview_reports_provisional_global(client, tmp_path):
    pytest.importorskip("PIL")
    path = _write_ring(tmp_path / "prov.tif")
    response = client.post(
        "/preview",
        json={
            "path": str(path),
            "threshold": 88.0,
            "frame_index": 0,
            "object_seed": {"x": 32, "y": 32, "frame_index": 0, "radius": 14},
            "prefer_opencv": False,
            "fast_preview": True,
        },
    )
    assert response.status_code == 200
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["preview_quality"] == "provisional"
    assert payload["threshold_semantics"] == "provisional_global"
    assert payload["requested_threshold"] == 88.0
    assert payload["effective_threshold"] == 88.0
    assert payload["threshold"] == 88.0


def test_gap_frame_analyze_not_ui_as_effective(monkeypatch):
    import morphostack.core.seeded_vesicle as sv

    stack = _ring_stack(n=2)

    def fake_track(*_a, **_k):
        yy, xx = np.ogrid[:64, :64]
        mask = (xx - 32) ** 2 + (yy - 32) ** 2 <= 10**2
        ok = SeededSliceResult(
            contour_xy=np.array([[28.0, 28.0], [36.0, 28.0], [36.0, 36.0], [28.0, 36.0]]),
            solid_mask=mask,
            center_xy=(32.0, 32.0),
            area_px=80.0,
            perimeter_px=30.0,
            method="circle_seed",
            ok=True,
            effective_threshold=17.5,
        )
        gap = SeededSliceResult(
            None, None, (32.0, 32.0), 0.0, 0.0, "circle_seed_gap", False, effective_threshold=None
        )
        return [ok, gap]

    monkeypatch.setattr(sv, "track_seeded_vesicle_stack", fake_track)

    analysis = analyze_stack(
        stack,
        thresholds=123.0,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        object_seed=ObjectSeed(x=32, y=32, frame_index=0, radius=14.0),
        profile="vesicle",
    )

    gap_frame = analysis.frames[1]
    assert gap_frame.contour is None
    assert gap_frame.threshold_semantics == "seeded_unavailable"
    assert gap_frame.effective_threshold is None
    assert gap_frame.threshold is None
    assert gap_frame.requested_threshold == 123.0
    rows = analysis_rows(analysis)
    assert rows[1]["threshold"] == ""
    assert rows[1]["effective_threshold"] == ""
    assert float(rows[1]["requested_threshold"]) == 123.0
