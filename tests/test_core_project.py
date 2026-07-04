from __future__ import annotations

import io
import json

import pytest

from morphostack.core import (
    ProjectSettings,
    RectROI,
    SweepSettings,
    VoxelSize,
    load_project_settings,
    write_project_settings,
)


def test_project_settings_round_trip_json(tmp_path):
    path = tmp_path / "morphostack.project.json"
    settings = ProjectSettings(
        profile="rbc",
        threshold=100,
        voxel_size=VoxelSize(0.1, 0.2, 0.5),
        roi=RectROI(1, 7, 2, 8),
        include_mesh=True,
        prefer_opencv=False,
        sweep=SweepSettings(start=50, stop=150, step=25),
    )

    write_project_settings(settings, path)
    loaded = load_project_settings(path)

    assert loaded == settings
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["profile"] == "rbc"
    assert payload["voxel_size"] == {"x_um": 0.1, "y_um": 0.2, "z_um": 0.5}
    assert payload["roi"] == {"xmin": 1, "xmax": 7, "ymin": 2, "ymax": 8}
    assert payload["sweep"] == {"start": 50, "stop": 150, "step": 25}


def test_project_settings_accepts_minimal_payload():
    settings = ProjectSettings.from_mapping({"version": 1})

    assert settings.profile is None
    assert settings.threshold is None
    assert settings.voxel_size is None
    assert settings.sweep == SweepSettings()


def test_project_settings_rejects_unknown_version():
    with pytest.raises(ValueError, match="unsupported"):
        ProjectSettings.from_mapping({"version": 99})


def test_project_settings_rejects_bad_sweep_step():
    with pytest.raises(ValueError, match="sweep.step"):
        ProjectSettings.from_mapping({"version": 1, "sweep": {"step": 0}})


def test_write_project_settings_to_handle():
    handle = io.StringIO()
    write_project_settings(ProjectSettings(profile="vesicle", threshold=75), handle)

    assert json.loads(handle.getvalue())["threshold"] == 75
