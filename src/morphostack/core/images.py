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


def color_stub_for_grayscale(grayscale: np.ndarray) -> np.ndarray:
    """Zero-allocation RGB shape stub matching a (z, y, x) grayscale stack.

    Analysis/preview/mesh only use grayscale. Building a full color copy via
    ``as_color_stack`` triples RAM on large CZI/TIFF stacks. This broadcast view
    satisfies ``ImageStack`` shape checks for API metadata without owning pixels.
    """

    arr = np.asarray(grayscale)
    if arr.ndim != 3:
        raise ValueError("color_stub_for_grayscale expects grayscale shape (z, y, x)")
    z, y, x = (int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2]))
    return np.broadcast_to(np.array(0, dtype=np.uint8), (z, y, x, 3))


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


def stretch_frame_to_uint8(frame: np.ndarray) -> np.ndarray:
    """Min-max stretch a single 2D plane to uint8 (float32 path; no 3D stack)."""

    arr = np.asarray(frame)
    if arr.ndim != 2:
        raise ValueError("stretch_frame_to_uint8 expects a 2D frame shaped as (y, x)")

    # Integer min/max avoids a full float cast when the plane is already constant
    # or spans the full uint8 range.
    if arr.dtype == np.uint8:
        min_val = int(arr.min())
        max_val = int(arr.max())
        if max_val <= min_val:
            return np.zeros(arr.shape, dtype=np.uint8)
        if min_val == 0 and max_val == 255:
            return np.ascontiguousarray(arr)
        scale = np.float32(255.0 / (max_val - min_val))
        return ((arr.astype(np.float32) - np.float32(min_val)) * scale).astype(np.uint8)

    frame_f = arr.astype(np.float32, copy=False)
    min_val = float(frame_f.min())
    max_val = float(frame_f.max())
    if max_val <= min_val:
        return np.zeros(arr.shape, dtype=np.uint8)
    scale = np.float32(255.0 / (max_val - min_val))
    return ((frame_f - np.float32(min_val)) * scale).astype(np.uint8)


def stretch_to_uint8(stack: np.ndarray) -> np.ndarray:
    """Min-max stretch each z-slice to uint8, preserving constant slices as zero."""

    gray = as_grayscale_stack(stack)
    stretched = [stretch_frame_to_uint8(frame) for frame in gray]
    return np.stack(stretched, axis=0)

