"""Headless analysis pipeline primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from morphostack.core.contours import SegmentationPreview, segmentation_preview
from morphostack.core.mesh import MeshMeasurement, measure_contour_stack
from morphostack.core.metrics import ContourMetrics, contour_metrics
from morphostack.core.models import VoxelSize
from morphostack.core.profiles import AnalysisProfile, DEFAULT_PROFILE, normalize_profile
from morphostack.core.segmentation import apply_rect_roi, apply_z_range


@dataclass(frozen=True)
class RectROI:
    xmin: int
    xmax: int
    ymin: int
    ymax: int


@dataclass(frozen=True)
class ZRange:
    zmin: int
    zmax: int

    def __post_init__(self) -> None:
        if self.zmin < 0:
            raise ValueError("zmin must be greater than or equal to zero")
        if self.zmax <= self.zmin:
            raise ValueError("zmax must be greater than zmin")


@dataclass(frozen=True)
class FrameAnalysis:
    frame_index: int
    threshold: float
    profile: AnalysisProfile
    contour: np.ndarray | None
    metrics: ContourMetrics | None
    preview: SegmentationPreview


@dataclass(frozen=True)
class StackAnalysis:
    voxel_size: VoxelSize
    profile: AnalysisProfile
    frames: tuple[FrameAnalysis, ...]
    mesh: MeshMeasurement | None = None
    z_range: ZRange | None = None

    @property
    def valid_frames(self) -> tuple[FrameAnalysis, ...]:
        return tuple(frame for frame in self.frames if frame.metrics is not None)


def analyze_frame(
    image: np.ndarray,
    *,
    frame_index: int,
    threshold: float,
    voxel_size: VoxelSize,
    profile: str | None = DEFAULT_PROFILE,
    prefer_opencv: bool = True,
) -> FrameAnalysis:
    analysis_profile = normalize_profile(profile)
    preview = segmentation_preview(image, threshold, prefer_opencv=prefer_opencv)
    metrics = None
    if preview.contour is not None:
        metrics = contour_metrics(preview.contour, voxel_size)
    return FrameAnalysis(
        frame_index=frame_index,
        threshold=threshold,
        profile=analysis_profile,
        contour=preview.contour,
        metrics=metrics,
        preview=preview,
    )


def analyze_stack(
    stack: np.ndarray,
    *,
    thresholds: float | Sequence[float],
    voxel_size: VoxelSize,
    roi: RectROI | None = None,
    z_range: ZRange | None = None,
    profile: str | None = DEFAULT_PROFILE,
    prefer_opencv: bool = True,
    include_mesh: bool = False,
) -> StackAnalysis:
    analysis_profile = normalize_profile(profile)
    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("analyze_stack expects a grayscale stack shaped as (z, y, x)")

    frame_offset = 0
    if z_range is not None:
        frame_offset = max(0, min(arr.shape[0], z_range.zmin))
        arr = apply_z_range(arr, zmin=z_range.zmin, zmax=z_range.zmax)

    if roi is not None:
        arr = apply_rect_roi(
            arr,
            xmin=roi.xmin,
            xmax=roi.xmax,
            ymin=roi.ymin,
            ymax=roi.ymax,
        )

    per_frame_thresholds = normalize_thresholds(thresholds, frame_count=arr.shape[0])
    frames = tuple(
        analyze_frame(
            frame,
            frame_index=idx + frame_offset,
            threshold=per_frame_thresholds[idx],
            voxel_size=voxel_size,
            profile=analysis_profile,
            prefer_opencv=prefer_opencv,
        )
        for idx, frame in enumerate(arr)
    )
    mesh = None
    if include_mesh:
        mesh = measure_contour_stack(
            tuple(frame.contour for frame in frames),
            shape=arr.shape,
            voxel=voxel_size,
        )
    return StackAnalysis(voxel_size=voxel_size, profile=analysis_profile, frames=frames, mesh=mesh, z_range=z_range)


def normalize_thresholds(thresholds: float | Sequence[float], *, frame_count: int) -> tuple[float, ...]:
    if np.isscalar(thresholds):
        return tuple(float(thresholds) for _ in range(frame_count))

    values = tuple(float(value) for value in thresholds)
    if len(values) != frame_count:
        raise ValueError("threshold sequence length must match number of frames")
    return values
