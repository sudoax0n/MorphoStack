"""Headless analysis pipeline primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from morphostack.core.contours import SegmentationPreview, segmentation_preview
from morphostack.core.metrics import ContourMetrics, contour_metrics
from morphostack.core.models import VoxelSize
from morphostack.core.segmentation import apply_rect_roi


@dataclass(frozen=True)
class RectROI:
    xmin: int
    xmax: int
    ymin: int
    ymax: int


@dataclass(frozen=True)
class FrameAnalysis:
    frame_index: int
    threshold: float
    contour: np.ndarray | None
    metrics: ContourMetrics | None
    preview: SegmentationPreview


@dataclass(frozen=True)
class StackAnalysis:
    voxel_size: VoxelSize
    frames: tuple[FrameAnalysis, ...]

    @property
    def valid_frames(self) -> tuple[FrameAnalysis, ...]:
        return tuple(frame for frame in self.frames if frame.metrics is not None)


def analyze_frame(
    image: np.ndarray,
    *,
    frame_index: int,
    threshold: float,
    voxel_size: VoxelSize,
    prefer_opencv: bool = True,
) -> FrameAnalysis:
    preview = segmentation_preview(image, threshold, prefer_opencv=prefer_opencv)
    metrics = None
    if preview.contour is not None:
        metrics = contour_metrics(preview.contour, voxel_size)
    return FrameAnalysis(
        frame_index=frame_index,
        threshold=threshold,
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
    prefer_opencv: bool = True,
) -> StackAnalysis:
    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("analyze_stack expects a grayscale stack shaped as (z, y, x)")

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
            frame_index=idx,
            threshold=per_frame_thresholds[idx],
            voxel_size=voxel_size,
            prefer_opencv=prefer_opencv,
        )
        for idx, frame in enumerate(arr)
    )
    return StackAnalysis(voxel_size=voxel_size, frames=frames)


def normalize_thresholds(thresholds: float | Sequence[float], *, frame_count: int) -> tuple[float, ...]:
    if np.isscalar(thresholds):
        return tuple(float(thresholds) for _ in range(frame_count))

    values = tuple(float(value) for value in thresholds)
    if len(values) != frame_count:
        raise ValueError("threshold sequence length must match number of frames")
    return values
