"""Preview image rendering for segmentation checks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO

import numpy as np

from morphostack.core.contours import SegmentationPreview, segmentation_preview
from morphostack.core.images import stretch_frame_to_uint8
from morphostack.core.pipeline import ObjectSeed, RectROI, StackViewTransform, ZRange
from morphostack.core.segmentation import crop_rect_roi_2d


@dataclass(frozen=True)
class PreviewImage:
    frame_index: int
    width: int
    height: int
    preview: SegmentationPreview
    png_bytes: bytes
    skel_perimeter_px: float | None = None
    skel_perimeter_um: float | None = None
    skel_ok: bool = False


def extract_preview_frame(
    stack: np.ndarray,
    frame_index: int,
    *,
    roi: RectROI | None = None,
    z_range: ZRange | None = None,
) -> tuple[np.ndarray, StackViewTransform]:
    """Extract one plane for preview without copying the full Z-stack.

    ``frame_index`` is the global source-stack index. Optional ``z_range`` is
    validated only (the selected plane is taken directly from the full stack).
    Optional ``roi`` is applied as a **2D crop** so local XY coords match
    :class:`StackViewTransform` offsets used by the web UI.

    Returns ``(frame_2d, transform)``.
    """

    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("preview frame extract expects a grayscale stack shaped as (z, y, x)")

    frame_count = arr.shape[0]
    _validate_preview_z(frame_index, frame_count, z_range=z_range)
    transform = StackViewTransform.create(roi=roi, z_range=z_range, raw_shape=arr.shape)

    # View of one plane — no full-stack copy. Crop/copy only the needed XY region.
    frame = arr[frame_index]
    if roi is not None:
        frame = crop_rect_roi_2d(
            frame,
            xmin=roi.xmin,
            xmax=roi.xmax,
            ymin=roi.ymin,
            ymax=roi.ymax,
        )
    else:
        # Contiguous plane for downstream encode/OpenCV without aliasing cache.
        frame = np.ascontiguousarray(frame)

    return frame, transform


def _validate_preview_z(
    frame_index: int,
    frame_count: int,
    *,
    z_range: ZRange | None,
) -> None:
    if z_range is not None:
        z0 = max(0, min(frame_count, z_range.zmin))
        z1 = max(0, min(frame_count, z_range.zmax))
        if z1 <= z0:
            raise ValueError("Z range bounds must define at least one frame")
        if frame_index < z_range.zmin or frame_index >= z_range.zmax:
            raise ValueError(
                f"Requested frame_index {frame_index} is outside selected Z-range "
                f"[{z_range.zmin}, {z_range.zmax})"
            )
    if frame_index < 0 or frame_index >= frame_count:
        raise ValueError(f"frame_index must be between 0 and {frame_count - 1}")


def extract_preview_frame_from_volume(
    source: object,
    frame_index: int,
    *,
    roi: RectROI | None = None,
    z_range: ZRange | None = None,
) -> tuple[np.ndarray, StackViewTransform]:
    """Extract one display plane via :class:`~morphostack.core.volume_source.VolumeSource`.

    Same geometry contract as :func:`extract_preview_frame` (global Z index,
    optional ROI crop, transform offsets). Uses ``read_plane`` so TIFF sources
    can avoid full-stack materialization; science paths are unchanged.
    """

    from morphostack.core.volume_source import VolumeSource

    if not isinstance(source, VolumeSource):
        raise TypeError("extract_preview_frame_from_volume requires a VolumeSource")

    meta = source.metadata()
    shape = meta.shape
    _validate_preview_z(frame_index, shape[0], z_range=z_range)
    transform = StackViewTransform.create(roi=roi, z_range=z_range, raw_shape=shape)
    frame = source.read_plane(int(frame_index))
    if roi is not None:
        frame = crop_rect_roi_2d(
            frame,
            xmin=roi.xmin,
            xmax=roi.xmax,
            ymin=roi.ymin,
            ymax=roi.ymax,
        )
    else:
        frame = np.ascontiguousarray(frame)
    return frame, transform


def resolve_seed_xy_from_object_seed(
    frame: np.ndarray,
    threshold: float,
    object_seed: ObjectSeed | None,
    *,
    ref_area: float | None = None,
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
    from morphostack.core.object_select import pick_component_from_mask

    chosen_comp = pick_component_from_mask(
        mask,
        seed_x=float(sx),
        seed_y=float(sy),
        seed_radius=float(getattr(object_seed, "radius", 10.0) or 10.0),
        ref_area=ref_area,
    )
    if chosen_comp is None:
        return (sx, sy)

    cx, cy = chosen_comp["centroid"]
    return (int(round(cx)), int(round(cy)))


def render_segmentation_preview_png(
    stack: np.ndarray,
    *,
    frame_index: int,
    threshold: float,
    prefer_opencv: bool = True,
    object_seed: ObjectSeed | tuple[int, int, float] | tuple[int, int] | None = None,
    enable_skeleton: bool = False,
    skeleton_prune_pix: float = 1.0,
    voxel_x_um: float = 1.0,
    ref_area: float | None = None,
    seed_radius: float = 10.0,
) -> PreviewImage:
    """Render a PNG overlay for one thresholded stack frame."""

    arr = np.asarray(stack)
    if arr.ndim == 2:
        arr = arr[np.newaxis, ...]
        frame_index = 0
    if arr.ndim != 3:
        raise ValueError("preview rendering expects a grayscale stack shaped as (z, y, x)")
    if frame_index < 0 or frame_index >= arr.shape[0]:
        raise ValueError(f"frame_index must be between 0 and {arr.shape[0] - 1}")

    frame = arr[frame_index]
    highlight_mask = None

    if object_seed is None:
        seed_xy = None
        radius = seed_radius
    elif isinstance(object_seed, tuple):
        seed_xy = (object_seed[0], object_seed[1])
        radius = float(object_seed[2]) if len(object_seed) > 2 else seed_radius
    else:
        radius = float(getattr(object_seed, "radius", seed_radius) or seed_radius)
        seed_xy = resolve_seed_xy_from_object_seed(
            frame, threshold, object_seed, ref_area=ref_area
        )

    preview = segmentation_preview(
        frame,
        threshold,
        prefer_opencv=prefer_opencv,
        object_seed=seed_xy,
        seed_radius=radius,
        ref_area=ref_area,
    )

    if seed_xy is not None:
        from morphostack.core.object_select import component_mask_full, pick_component_from_mask

        comp = pick_component_from_mask(
            np.asarray(frame) >= threshold,
            seed_x=float(seed_xy[0]),
            seed_y=float(seed_xy[1]),
            seed_radius=radius,
            ref_area=ref_area,
        )
        if comp is not None:
            highlight_mask = component_mask_full(comp, frame.shape)

    skel_mask = None
    skel_perimeter_px: float | None = None
    skel_perimeter_um: float | None = None
    skel_ok = False
    if enable_skeleton:
        try:
            from morphostack.core.skeleton import measure_skeleton

            binary = highlight_mask if highlight_mask is not None else (np.asarray(frame) >= threshold)
            skel_mask, skel_metrics = measure_skeleton(
                binary,
                object_seed=seed_xy,
                prune_threshold_pix=skeleton_prune_pix,
                voxel_x_um=voxel_x_um,
            )
            if skel_metrics.ok and np.any(skel_mask):
                skel_perimeter_px = skel_metrics.perimeter_px
                skel_perimeter_um = skel_metrics.perimeter_um
                skel_ok = True
            else:
                skel_mask = None
                skel_perimeter_px = 0.0
                skel_perimeter_um = 0.0
                skel_ok = False
        except Exception:
            skel_mask = None
            skel_perimeter_px = None
            skel_perimeter_um = None
            skel_ok = False

    image = overlay_preview(
        frame,
        threshold=threshold,
        preview=preview,
        object_seed=object_seed if seed_xy is None else seed_xy,
        skeleton_mask=skel_mask,
        highlight_mask=highlight_mask,
    )
    buffer = BytesIO()
    # compress_level=0 is much faster than Pillow's default (6) for scrubbing;
    # optimize=False skips a second pass that adds latency for little size win.
    image.save(buffer, format="PNG", compress_level=0, optimize=False)
    return PreviewImage(
        frame_index=frame_index,
        width=int(frame.shape[1]),
        height=int(frame.shape[0]),
        preview=preview,
        png_bytes=buffer.getvalue(),
        skel_perimeter_px=skel_perimeter_px,
        skel_perimeter_um=skel_perimeter_um,
        skel_ok=skel_ok,
    )


def exterior_highlight_edge(highlight_mask: np.ndarray) -> np.ndarray:
    """Return a thin exterior-only edge band from a solid/ring mask.

    Hole-fills first so hollow membrane rings do not paint an inner lumen rim.
    Display-only; does not alter scientific masks or contours.
    """
    solid = np.asarray(highlight_mask, dtype=bool)
    if not np.any(solid):
        return solid
    try:
        from scipy.ndimage import binary_erosion, binary_fill_holes

        filled = binary_fill_holes(solid)
    except Exception:
        filled = solid
    try:
        from scipy.ndimage import binary_erosion

        edge = filled & ~binary_erosion(filled, iterations=2)
        if not np.any(edge):
            return filled
        return edge
    except Exception:
        return filled


def overlay_preview(
    frame: np.ndarray,
    *,
    threshold: float,
    preview: SegmentationPreview,
    object_seed: ObjectSeed | tuple[int, int, float] | tuple[int, int] | None = None,
    skeleton_mask: np.ndarray | None = None,
    highlight_mask: np.ndarray | None = None,
):
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise RuntimeError("Pillow is required to render preview images") from exc

    gray = stretch_frame_to_uint8(np.asarray(frame))
    # Never paint a solid filled disk — only a thin membrane/edge band (or threshold edge).
    # Solid red fill made GUVs look like opaque blobs and hid the membrane.
    has_contour = preview.contour is not None and len(preview.contour) >= 2
    mask = None
    # When a closed exterior contour is already drawn (seeded Standard path),
    # suppress red highlight_mask paint — dual red/green rings look like a
    # bilayer and the red band is not scientific. Non-seeded global threshold
    # preview keeps its light threshold tint when no contour.
    if has_contour:
        mask = None
    elif highlight_mask is not None:
        mask = exterior_highlight_edge(highlight_mask)
    else:
        thr_mask = np.asarray(frame) >= threshold
        # Light full threshold tint only when no seed selection / no contour
        mask = thr_mask

    rgb = np.empty((*gray.shape, 3), dtype=np.uint8)
    rgb[..., 0] = gray
    rgb[..., 1] = gray
    rgb[..., 2] = gray
    if mask is not None and np.any(mask):
        # Subtle red edge tint (not opaque fill)
        dim = (gray.astype(np.uint16) * 70 // 100).astype(np.uint8)
        boosted = np.maximum(gray, np.uint8(160))
        rgb[..., 0] = np.where(mask, boosted, gray)
        rgb[..., 1] = np.where(mask, dim, gray)
        rgb[..., 2] = np.where(mask, dim, gray)

    # Cyan skeleton pixels (drawn before contour so green outline remains visible).
    if skeleton_mask is not None:
        skel = np.asarray(skeleton_mask, dtype=bool)
        if skel.shape == rgb.shape[:2] and np.any(skel):
            rgb[skel, 0] = 0
            rgb[skel, 1] = 255
            rgb[skel, 2] = 255

    image = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(image)
    if has_contour:
        points = [(float(x), float(y)) for x, y in preview.contour]
        draw.line(points + [points[0]], fill=(31, 230, 137), width=3)

    # Seed marker: center crosshair only. Full Fiji circle is the HTML overlay
    # (drawing full R here + a second CSS circle caused huge double rings).
    # Exact seeded preview may omit this and draw tracked center in the UI.
    if object_seed is not None:
        if isinstance(object_seed, tuple):
            sx, sy = float(object_seed[0]), float(object_seed[1])
            r = 8
            draw.ellipse([sx - r, sy - r, sx + r, sy + r], outline=(255, 220, 0), width=2)
            draw.line([sx - r - 3, sy, sx + r + 3, sy], fill=(255, 220, 0), width=1)
            draw.line([sx, sy - r - 3, sx, sy + r + 3], fill=(255, 220, 0), width=1)
        else:
            if getattr(object_seed, "type", "circle") == "polygon" and getattr(object_seed, "points", None):
                points = [(float(pt.x), float(pt.y)) for pt in object_seed.points]
                draw.line(points + [points[0]], fill=(255, 220, 0), width=2)
                for pt in points:
                    draw.ellipse([pt[0] - 2, pt[1] - 2, pt[0] + 2, pt[1] + 2], fill=(255, 220, 0))
            else:
                sx, sy = float(object_seed.x), float(object_seed.y)
                r = 8
                draw.ellipse([sx - r, sy - r, sx + r, sy + r], outline=(255, 220, 0), width=2)
                draw.line([sx - r - 3, sy, sx + r + 3, sy], fill=(255, 220, 0), width=1)
                draw.line([sx, sy - r - 3, sx, sy + r + 3], fill=(255, 220, 0), width=1)
    return image


def with_global_frame_index(preview_image: PreviewImage, frame_index: int) -> PreviewImage:
    """Return a copy of ``preview_image`` reporting the global source frame index."""

    if preview_image.frame_index == frame_index:
        return preview_image
    return replace(preview_image, frame_index=frame_index)
