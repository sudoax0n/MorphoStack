"""Image stack standardization and intensity normalization."""

from __future__ import annotations

import numpy as np


def as_grayscale_stack(image: np.ndarray) -> np.ndarray:
    """Return image data as a grayscale stack with shape (z, y, x)."""

    arr = np.asarray(image)
    if arr.ndim == 2:
        return arr[np.newaxis, ...]

    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return arr[np.newaxis, ...]

    if arr.ndim == 3:
        if arr.shape[-1] in (3, 4):
            return rgb_to_gray(arr[..., :3])[np.newaxis, ...]
        return arr

    if arr.ndim == 4:
        if arr.shape[-1] in (3, 4):
            return np.stack([rgb_to_gray(frame[..., :3]) for frame in arr], axis=0)
        if arr.shape[1] in (3, 4):
            channel_last = np.moveaxis(arr[:, :3, :, :], 1, -1)
            return np.stack([rgb_to_gray(frame) for frame in channel_last], axis=0)

    raise ValueError(f"Unsupported image stack shape: {arr.shape}")


def as_color_stack(image: np.ndarray) -> np.ndarray:
    """Return image data as an RGB/RGBA stack with shape (z, y, x, c)."""

    arr = np.asarray(image)
    if arr.ndim == 2:
        return np.repeat(arr[np.newaxis, ..., np.newaxis], 3, axis=-1)

    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return np.repeat(arr[np.newaxis, ..., np.newaxis], 3, axis=-1)

    if arr.ndim == 3:
        if arr.shape[-1] in (3, 4):
            return arr[np.newaxis, ...]
        return np.repeat(arr[..., np.newaxis], 3, axis=-1)

    if arr.ndim == 4:
        if arr.shape[-1] in (3, 4):
            return arr
        if arr.shape[1] in (3, 4):
            return np.moveaxis(arr, 1, -1)

    raise ValueError(f"Unsupported image stack shape: {arr.shape}")


def rgb_to_gray(rgb: np.ndarray) -> np.ndarray:
    """Convert RGB data to luminance grayscale without requiring OpenCV."""

    arr = np.asarray(rgb)
    if arr.shape[-1] < 3:
        raise ValueError("RGB input must have at least three channels")
    gray = (
        0.299 * arr[..., 0].astype(np.float64)
        + 0.587 * arr[..., 1].astype(np.float64)
        + 0.114 * arr[..., 2].astype(np.float64)
    )
    return gray.astype(arr.dtype, copy=False)


def stretch_to_uint8(stack: np.ndarray) -> np.ndarray:
    """Min-max stretch each z-slice to uint8, preserving constant slices as zero."""

    gray = as_grayscale_stack(stack)
    stretched: list[np.ndarray] = []
    for frame in gray:
        frame_float = frame.astype(np.float64)
        min_val = float(np.min(frame_float))
        max_val = float(np.max(frame_float))
        if max_val <= min_val:
            stretched.append(np.zeros_like(frame, dtype=np.uint8))
            continue
        scaled = (frame_float - min_val) / (max_val - min_val) * 255.0
        stretched.append(scaled.astype(np.uint8))
    return np.stack(stretched, axis=0)

