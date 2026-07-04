"""Shared core data models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


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


@dataclass(frozen=True)
class ImageStack:
    """Loaded microscope stack with standardized arrays and physical spacing."""

    source_path: Path
    grayscale: np.ndarray
    color: np.ndarray
    voxel_size: VoxelSize

    def __post_init__(self) -> None:
        if self.grayscale.ndim != 3:
            raise ValueError("grayscale stack must have shape (z, y, x)")
        if self.color.ndim != 4:
            raise ValueError("color stack must have shape (z, y, x, c)")
        if self.color.shape[:3] != self.grayscale.shape:
            raise ValueError("color and grayscale stacks must share z/y/x dimensions")
