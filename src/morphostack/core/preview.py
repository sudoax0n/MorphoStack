"""Preview image rendering for segmentation checks."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np

from morphostack.core.contours import SegmentationPreview, segmentation_preview
from morphostack.core.images import stretch_to_uint8
from morphostack.core.pipeline import ObjectSeed


@dataclass(frozen=True)
class PreviewImage:
    frame_index: int
    width: int
    height: int
    preview: SegmentationPreview
    png_bytes: bytes


def resolve_seed_xy_from_object_seed(
    frame: np.ndarray,
    threshold: float,
    object_seed: ObjectSeed | None
) -> tuple[int, int] | None:
    if object_seed is None:
        return None
        
    h, w = frame.shape
    
    if getattr(object_seed, "type", "circle") == "polygon" and getattr(object_seed, "points", None):
        xs = [pt.x for pt in object_seed.points]
        ys = [pt.y for pt in object_seed.points]
        centroid_x = sum(xs) / len(xs) if xs else 0.0
        centroid_y = sum(ys) / len(ys) if ys else 0.0
    else:
        centroid_x = object_seed.x
        centroid_y = object_seed.y

    sx = max(0, min(w - 1, int(round(centroid_x))))
    sy = max(0, min(h - 1, int(round(centroid_y))))

    mask = frame >= threshold
    from morphostack.core.pipeline import get_connected_components
    components = get_connected_components(mask)
    if not components:
        return (sx, sy)

    chosen_comp = None

    for comp in components:
        ymin, ymax, xmin, xmax = comp["bbox"]
        if ymin <= sy < ymax and xmin <= sx < xmax:
            if comp["sub_mask"][sy - ymin, sx - xmin]:
                chosen_comp = comp
                break

    if chosen_comp is None:
        if getattr(object_seed, "type", "circle") == "polygon" and getattr(object_seed, "points", None):
            from PIL import Image, ImageDraw
            poly_points = [(pt.x, pt.y) for pt in object_seed.points]
            poly_img = Image.new("1", (w, h), 0)
            draw = ImageDraw.Draw(poly_img)
            draw.polygon(poly_points, fill=1)
            poly_mask = np.asarray(poly_img, dtype=bool)

            max_overlap = 0
            for comp in components:
                ymin, ymax, xmin, xmax = comp["bbox"]
                comp_mask = np.zeros_like(poly_mask)
                comp_mask[ymin:ymax, xmin:xmax] = comp["sub_mask"]
                overlap = np.sum(comp_mask & poly_mask)
                if overlap > max_overlap:
                    max_overlap = overlap
                    chosen_comp = comp

    if chosen_comp is not None:
        ymin, ymax, xmin, xmax = chosen_comp["bbox"]
        cy, cx = np.argwhere(chosen_comp["sub_mask"])[0]
        return (int(cx + xmin), int(cy + ymin))

    return (sx, sy)


def render_segmentation_preview_png(
    stack: np.ndarray,
    *,
    frame_index: int,
    threshold: float,
    prefer_opencv: bool = True,
    object_seed: ObjectSeed | tuple[int, int, float] | tuple[int, int] | None = None,
) -> PreviewImage:
    """Render a PNG overlay for one thresholded stack frame."""

    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("preview rendering expects a grayscale stack shaped as (z, y, x)")
    if frame_index < 0 or frame_index >= arr.shape[0]:
        raise ValueError(f"frame_index must be between 0 and {arr.shape[0] - 1}")

    frame = arr[frame_index]
    
    if object_seed is None:
        seed_xy = None
    elif isinstance(object_seed, tuple):
        seed_xy = (object_seed[0], object_seed[1])
    else:
        seed_xy = resolve_seed_xy_from_object_seed(frame, threshold, object_seed)

    preview = segmentation_preview(frame, threshold, prefer_opencv=prefer_opencv, object_seed=seed_xy)
    image = overlay_preview(frame, threshold=threshold, preview=preview, object_seed=object_seed)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return PreviewImage(
        frame_index=frame_index,
        width=int(frame.shape[1]),
        height=int(frame.shape[0]),
        preview=preview,
        png_bytes=buffer.getvalue(),
    )


def overlay_preview(
    frame: np.ndarray,
    *,
    threshold: float,
    preview: SegmentationPreview,
    object_seed: ObjectSeed | tuple[int, int, float] | tuple[int, int] | None = None,
):
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
    draw = ImageDraw.Draw(image)
    if preview.contour is not None and len(preview.contour) >= 2:
        points = [(float(x), float(y)) for x, y in preview.contour]
        draw.line(points + [points[0]], fill=(31, 230, 137), width=2)
        
    if object_seed is not None:
        if isinstance(object_seed, tuple):
            sx, sy = object_seed[0], object_seed[1]
            r = int(round(object_seed[2])) if len(object_seed) > 2 else 6
            draw.ellipse([sx - r, sy - r, sx + r, sy + r], outline=(255, 220, 0), width=2)
            draw.line([sx - r - 3, sy, sx + r + 3, sy], fill=(255, 220, 0), width=1)
            draw.line([sx, sy - r - 3, sx, sy + r + 3], fill=(255, 220, 0), width=1)
        else:
            # ObjectSeed object
            if getattr(object_seed, "type", "circle") == "polygon" and getattr(object_seed, "points", None):
                points = [(float(pt.x), float(pt.y)) for pt in object_seed.points]
                draw.line(points + [points[0]], fill=(255, 220, 0), width=2)
                for pt in points:
                    draw.ellipse([pt[0] - 2, pt[1] - 2, pt[0] + 2, pt[1] + 2], fill=(255, 220, 0))
            else:
                sx, sy = object_seed.x, object_seed.y
                r = object_seed.radius
                draw.ellipse([sx - r, sy - r, sx + r, sy + r], outline=(255, 220, 0), width=2)
                draw.line([sx - r - 3, sy, sx + r + 3, sy], fill=(255, 220, 0), width=1)
                draw.line([sx, sy - r - 3, sx, sy + r + 3], fill=(255, 220, 0), width=1)
    return image
