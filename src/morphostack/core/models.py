"""Shared core data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoxelSize:
    """Physical voxel spacing in micrometers."""

    x_um: float
    y_um: float
    z_um: float

    def __post_init__(self) -> None:
        for name, value in (
            ("x_um", self.x_um),
            ("y_um", self.y_um),
            ("z_um", self.z_um),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

    @property
    def marching_cubes_spacing(self) -> tuple[float, float, float]:
        """Spacing order for arrays shaped as (z, y, x)."""

        return (self.z_um, self.y_um, self.x_um)

