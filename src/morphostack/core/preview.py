"""Preview image rendering for segmentation checks."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np

from morphostack.core.contours import SegmentationPreview, segmentation_preview
from morphostack.core.images import stretch_to_uint8


@dataclass(frozen=True)
class PreviewImage:
    frame_index: int
    width: int
    height: int
    preview: SegmentationPreview
    png_bytes: bytes


def render_segmentation_preview_png(
    stack: np.ndarray,
    *,
    frame_index: int,
    threshold: float,
    prefer_opencv: bool = True,
) -> PreviewImage:
    """Render a PNG overlay for one thresholded stack frame."""

    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("preview rendering expects a grayscale stack shaped as (z, y, x)")
    if frame_index < 0 or frame_index >= arr.shape[0]:
        raise ValueError(f"frame_index must be between 0 and {arr.shape[0] - 1}")

    frame = arr[frame_index]
    preview = segmentation_preview(frame, threshold, prefer_opencv=prefer_opencv)
    image = overlay_preview(frame, threshold=threshold, preview=preview)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return PreviewImage(
        frame_index=frame_index,
        width=int(frame.shape[1]),
        height=int(frame.shape[0]),
        preview=preview,
        png_bytes=buffer.getvalue(),
    )


def overlay_preview(frame: np.ndarray, *, threshold: float, preview: SegmentationPreview):
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise RuntimeError("Pillow is required to render preview images") from exc

    gray = stretch_to_uint8(np.asarray(frame)[np.newaxis, ...])[0]
    rgb = np.repeat(gray[..., np.newaxis], 3, axis=-1).astype(np.uint8)
    mask = np.asarray(frame) >= threshold
    rgb[mask, 0] = np.maximum(rgb[mask, 0], 180)
    rgb[mask, 1] = (rgb[mask, 1] * 0.55).astype(np.uint8)
    rgb[mask, 2] = (rgb[mask, 2] * 0.55).astype(np.uint8)

    image = Image.fromarray(rgb, mode="RGB")
    if preview.contour is not None and len(preview.contour) >= 2:
        draw = ImageDraw.Draw(image)
        points = [(float(x), float(y)) for x, y in preview.contour]
        draw.line(points + [points[0]], fill=(31, 230, 137), width=2)
    return image
