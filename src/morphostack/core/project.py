"""Project settings for reproducible MorphoStack runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import RectROI, ZRange
from morphostack.core.profiles import DEFAULT_PROFILE, normalize_profile

PROJECT_SETTINGS_VERSION = 1


@dataclass(frozen=True)
class SweepSettings:
    start: float | None = None
    stop: float | None = None
    step: float | None = None

    @classmethod
    def from_mapping(cls, payload: Any) -> "SweepSettings":
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("project sweep settings must be an object")
        return cls(
            start=optional_float(payload.get("start"), "sweep.start"),
            stop=optional_float(payload.get("stop"), "sweep.stop"),
            step=optional_float(payload.get("step"), "sweep.step"),
        )

    def to_payload(self) -> dict[str, float]:
        payload: dict[str, float] = {}
        if self.start is not None:
            payload["start"] = self.start
        if self.stop is not None:
            payload["stop"] = self.stop
        if self.step is not None:
            payload["step"] = self.step
        return payload


@dataclass(frozen=True)
class ProjectSettings:
    profile: str | None = None
    threshold: float | None = None
    voxel_size: VoxelSize | None = None
    roi: RectROI | None = None
    z_range: ZRange | None = None
    include_mesh: bool | None = None
    prefer_opencv: bool | None = None
    sweep: SweepSettings = SweepSettings()

    @classmethod
    def from_mapping(cls, payload: Any) -> "ProjectSettings":
        if not isinstance(payload, dict):
            raise ValueError("project settings must be a JSON object")

        version = payload.get("version", PROJECT_SETTINGS_VERSION)
        if version != PROJECT_SETTINGS_VERSION:
            raise ValueError(f"unsupported project settings version: {version}")

        profile = payload.get("profile")
        if profile is not None:
            profile = normalize_profile(str(profile))

        return cls(
            profile=profile,
            threshold=optional_float(payload.get("threshold"), "threshold"),
            voxel_size=voxel_from_mapping(payload.get("voxel_size")),
            roi=roi_from_mapping(payload.get("roi")),
            z_range=z_range_from_mapping(payload.get("z_range")),
            include_mesh=optional_bool(payload.get("include_mesh"), "include_mesh"),
            prefer_opencv=optional_bool(payload.get("prefer_opencv"), "prefer_opencv"),
            sweep=SweepSettings.from_mapping(payload.get("sweep")),
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "version": PROJECT_SETTINGS_VERSION,
            "profile": self.profile or DEFAULT_PROFILE,
        }
        if self.threshold is not None:
            payload["threshold"] = self.threshold
        if self.voxel_size is not None:
            payload["voxel_size"] = {
                "x_um": self.voxel_size.x_um,
                "y_um": self.voxel_size.y_um,
                "z_um": self.voxel_size.z_um,
            }
        if self.roi is not None:
            payload["roi"] = {
                "xmin": self.roi.xmin,
                "xmax": self.roi.xmax,
                "ymin": self.roi.ymin,
                "ymax": self.roi.ymax,
            }
        if self.z_range is not None:
            payload["z_range"] = {
                "zmin": self.z_range.zmin,
                "zmax": self.z_range.zmax,
            }
        if self.include_mesh is not None:
            payload["include_mesh"] = self.include_mesh
        if self.prefer_opencv is not None:
            payload["prefer_opencv"] = self.prefer_opencv
        sweep = self.sweep.to_payload()
        if sweep:
            payload["sweep"] = sweep
        return payload


def load_project_settings(path: str | Path) -> ProjectSettings:
    with Path(path).open("r", encoding="utf-8") as handle:
        return ProjectSettings.from_mapping(json.load(handle))


def write_project_settings(settings: ProjectSettings, destination: str | Path | TextIO) -> None:
    close_after = False
    if hasattr(destination, "write"):
        handle = destination
    else:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", encoding="utf-8")
        close_after = True

    try:
        json.dump(settings.to_payload(), handle, indent=2, sort_keys=True)
        handle.write("\n")
    finally:
        if close_after:
            handle.close()


def optional_float(value: Any, name: str) -> float | None:
    if value is None:
        return None
    result = float(value)
    if name.endswith("step") and result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return result


def optional_bool(value: Any, name: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"{name} must be true or false")


def voxel_from_mapping(payload: Any) -> VoxelSize | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("project voxel_size must be an object")
    return VoxelSize(
        x_um=float(payload["x_um"]),
        y_um=float(payload["y_um"]),
        z_um=float(payload["z_um"]),
    )


def roi_from_mapping(payload: Any) -> RectROI | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("project roi must be an object")
    return RectROI(
        xmin=int(payload["xmin"]),
        xmax=int(payload["xmax"]),
        ymin=int(payload["ymin"]),
        ymax=int(payload["ymax"]),
    )


def z_range_from_mapping(payload: Any) -> ZRange | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("project z_range must be an object")
    return ZRange(
        zmin=int(payload["zmin"]),
        zmax=int(payload["zmax"]),
    )
