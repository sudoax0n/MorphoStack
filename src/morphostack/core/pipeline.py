"""Headless analysis pipeline primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Any

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
class SeedPoint:
    x: float
    y: float


@dataclass(frozen=True)
class ObjectSeed:
    x: float
    y: float
    frame_index: int
    radius: float = 10.0
    max_tracking_dist_um: float | None = None
    type: str = "circle"
    points: list[SeedPoint] | None = None


@dataclass(frozen=True)
class StackViewTransform:
    x_offset: int
    y_offset: int
    z_offset: int
    x_limit: int | None = None
    y_limit: int | None = None
    z_limit: int | None = None
    roi: RectROI | None = None
    z_range: ZRange | None = None

    @classmethod
    def create(
        cls,
        *,
        roi: RectROI | None = None,
        z_range: ZRange | None = None,
        raw_shape: tuple[int, int, int] | None = None,
    ) -> StackViewTransform:
        x_offset = roi.xmin if roi is not None else 0
        y_offset = roi.ymin if roi is not None else 0
        z_offset = z_range.zmin if z_range is not None else 0
        
        z_limit = raw_shape[0] if raw_shape is not None else None
        y_limit = raw_shape[1] if raw_shape is not None else None
        x_limit = raw_shape[2] if raw_shape is not None else None
        
        return cls(
            x_offset=x_offset,
            y_offset=y_offset,
            z_offset=z_offset,
            x_limit=x_limit,
            y_limit=y_limit,
            z_limit=z_limit,
            roi=roi,
            z_range=z_range,
        )

    def to_local_seed(self, seed: ObjectSeed) -> tuple[int, int, int]:
        """Convert global (x, y, z) seed to local (x, y, z) coords.
        Raises ValueError if seed falls outside the ROI, selected Z-range, or stack limits.
        """
        # Validate against original stack limits if available
        if self.x_limit is not None and (seed.x < 0 or seed.x >= self.x_limit):
            raise ValueError(f"Seed X coordinate {seed.x} is outside full image bounds (0-{self.x_limit - 1})")
        if self.y_limit is not None and (seed.y < 0 or seed.y >= self.y_limit):
            raise ValueError(f"Seed Y coordinate {seed.y} is outside full image bounds (0-{self.y_limit - 1})")
        if self.z_limit is not None and (seed.frame_index < 0 or seed.frame_index >= self.z_limit):
            raise ValueError(f"Seed frame index {seed.frame_index} is outside full image bounds (0-{self.z_limit - 1})")

        # Validate against ROI
        if self.roi is not None:
            if seed.x < self.roi.xmin or seed.x >= self.roi.xmax:
                raise ValueError(f"Seed X coordinate {seed.x} is outside ROI bounds [{self.roi.xmin}, {self.roi.xmax})")
            if seed.y < self.roi.ymin or seed.y >= self.roi.ymax:
                raise ValueError(f"Seed Y coordinate {seed.y} is outside ROI bounds [{self.roi.ymin}, {self.roi.ymax})")

        # Validate against Z-range
        if self.z_range is not None:
            if seed.frame_index < self.z_range.zmin or seed.frame_index >= self.z_range.zmax:
                raise ValueError(f"Seed frame index {seed.frame_index} is outside Z-range [{self.z_range.zmin}, {self.z_range.zmax})")

        local_x = int(round(seed.x)) - self.x_offset
        local_y = int(round(seed.y)) - self.y_offset
        local_z = seed.frame_index - self.z_offset
        return (local_x, local_y, local_z)

    def to_local_seed_object(self, seed: ObjectSeed) -> ObjectSeed:
        """Convert global ObjectSeed object to a local ObjectSeed object, translating points if type is polygon."""
        if getattr(seed, "type", "circle") == "polygon":
            if not seed.points:
                raise ValueError("Polygon seed must have a non-empty list of points")
            # Validate all points
            for pt in seed.points:
                if self.x_limit is not None and (pt.x < 0 or pt.x >= self.x_limit):
                    raise ValueError(f"Polygon vertex X coordinate {pt.x} is outside full image bounds")
                if self.y_limit is not None and (pt.y < 0 or pt.y >= self.y_limit):
                    raise ValueError(f"Polygon vertex Y coordinate {pt.y} is outside full image bounds")
                if self.roi is not None:
                    if pt.x < self.roi.xmin or pt.x >= self.roi.xmax or pt.y < self.roi.ymin or pt.y >= self.roi.ymax:
                        raise ValueError(f"Polygon vertex ({pt.x}, {pt.y}) is outside ROI bounds")

            if self.z_limit is not None and (seed.frame_index < 0 or seed.frame_index >= self.z_limit):
                raise ValueError(f"Seed frame index {seed.frame_index} is outside full image bounds")
            if self.z_range is not None:
                if seed.frame_index < self.z_range.zmin or seed.frame_index >= self.z_range.zmax:
                    raise ValueError(f"Seed frame index {seed.frame_index} is outside Z-range")

            local_points = [SeedPoint(x=pt.x - self.x_offset, y=pt.y - self.y_offset) for pt in seed.points]
            xs = [pt.x for pt in local_points]
            ys = [pt.y for pt in local_points]
            local_x = sum(xs) / len(xs)
            local_y = sum(ys) / len(ys)
            local_z = seed.frame_index - self.z_offset

            return ObjectSeed(
                x=local_x,
                y=local_y,
                frame_index=local_z,
                radius=seed.radius,
                max_tracking_dist_um=seed.max_tracking_dist_um,
                type="polygon",
                points=local_points
            )
        else:
            lx, ly, lz = self.to_local_seed(seed)
            return ObjectSeed(
                x=lx,
                y=ly,
                frame_index=lz,
                radius=seed.radius,
                max_tracking_dist_um=seed.max_tracking_dist_um,
                type=getattr(seed, "type", "circle"),
                points=None
            )

    def to_global_contour(self, local_contour: np.ndarray | None) -> np.ndarray | None:
        """Convert local contour coordinates back to global full-image coordinates."""
        if local_contour is None:
            return None
        global_contour = local_contour.copy()
        global_contour[:, 0] += self.x_offset
        global_contour[:, 1] += self.y_offset
        return global_contour



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
    object_seed: tuple[int, int] | None = None,
) -> FrameAnalysis:
    analysis_profile = normalize_profile(profile)
    preview = segmentation_preview(image, threshold, prefer_opencv=prefer_opencv, object_seed=object_seed)
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
    object_seed: ObjectSeed | None = None,
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

    transform = StackViewTransform.create(roi=roi, z_range=z_range, raw_shape=stack.shape)
    local_seed = None
    if object_seed is not None:
        local_seed = transform.to_local_seed_object(object_seed)

    if analysis_profile == "limeseg":
        if local_seed is None:
            raise ValueError("LimeSeg active surfaces profile requires an object seed")

        from morphostack.core.limeseg import run_limeseg_optimization, surfels_to_mask_stack
        voxel_x = voxel_size.x_um if voxel_size is not None else 1.0
        voxel_z = voxel_size.z_um if voxel_size is not None else 1.0

        poly_points = None
        if local_seed.type == "polygon" and local_seed.points is not None:
            poly_points = [(pt.x, pt.y) for pt in local_seed.points]

        # Run LimeSeg active surfaces optimization
        surfels = run_limeseg_optimization(
            arr=arr,
            seed_x=local_seed.x,
            seed_y=local_seed.y,
            seed_z=local_seed.frame_index,
            seed_radius=local_seed.radius,
            voxel_size_x=voxel_x,
            voxel_size_z=voxel_z,
            d_0=2.0,
            f_pressure=0.015,
            k_grad=0.03,
            relaxation_steps=100,
            optimization_steps=200,
            polygon_points=poly_points,
        )

        ZScale = voxel_z / voxel_x if voxel_x > 0.0 else 1.0
        limeseg_mask = surfels_to_mask_stack(surfels, arr.shape, ZScale)

        from morphostack.core.contours import SegmentationPreview, contour_circularity
        from morphostack.core.metrics import contour_metrics
        from morphostack.core.contours import largest_opencv_contour, largest_component_boundary

        frames_list = []
        for idx in range(arr.shape[0]):
            frame_mask = limeseg_mask[idx]
            contour = largest_opencv_contour(frame_mask)
            if contour is None and np.sum(frame_mask) > 0:
                contour = largest_component_boundary(frame_mask)

            global_contour = transform.to_global_contour(contour)

            if contour is not None and len(contour) >= 3:
                metrics = contour_metrics(contour, voxel_size)
                circ = contour_circularity(contour)
                area_px = float(np.sum(frame_mask))
                perimeter_px = float(np.sum(np.linalg.norm(np.diff(np.vstack([contour, contour[0]]), axis=0), axis=1)))
                preview = SegmentationPreview(
                    threshold=per_frame_thresholds[idx],
                    contour=global_contour,
                    area_px2=area_px,
                    perimeter_px=perimeter_px,
                    circularity=circ,
                    method="limeseg"
                )
            else:
                metrics = None
                preview = SegmentationPreview(
                    threshold=per_frame_thresholds[idx],
                    contour=None,
                    area_px2=0.0,
                    perimeter_px=0.0,
                    circularity=0.0,
                    method="limeseg_empty"
                )

            fa = FrameAnalysis(
                frame_index=idx + frame_offset,
                threshold=per_frame_thresholds[idx],
                profile=analysis_profile,
                contour=global_contour,
                metrics=metrics,
                preview=preview
            )
            frames_list.append(fa)

        frames = tuple(frames_list)
    else:
        # Build per-frame seeds via connected component tracking when local_seed is provided.
        # Note: frame_offset is 0 because local_seed is already in local coordinates.
        per_frame_seeds = _build_per_frame_seeds(arr, per_frame_thresholds, local_seed, 0, voxel_size=voxel_size)

        frames_list = []
        for idx, frame in enumerate(arr):
            if object_seed is not None and per_frame_seeds[idx] is None:
                # Seed was lost or not reached; do not fall back.
                from morphostack.core.contours import SegmentationPreview
                preview = SegmentationPreview(
                    threshold=per_frame_thresholds[idx],
                    contour=None,
                    area_px2=0.0,
                    perimeter_px=0.0,
                    circularity=0.0,
                    method="seed_lost"
                )
                fa = FrameAnalysis(
                    frame_index=idx + frame_offset,
                    threshold=per_frame_thresholds[idx],
                    profile=analysis_profile,
                    contour=None,
                    metrics=None,
                    preview=preview,
                )
                frames_list.append(fa)
            else:
                fa = analyze_frame(
                    frame,
                    frame_index=idx + frame_offset,
                    threshold=per_frame_thresholds[idx],
                    voxel_size=voxel_size,
                    profile=analysis_profile,
                    prefer_opencv=prefer_opencv,
                    object_seed=per_frame_seeds[idx],
                )
                frames_list.append(fa)
        frames = tuple(frames_list)

    mesh = None
    if include_mesh:
        mesh = measure_contour_stack(
            tuple(frame.contour for frame in frames),
            shape=stack.shape,
            voxel=voxel_size,
        )
    return StackAnalysis(voxel_size=voxel_size, profile=analysis_profile, frames=frames, mesh=mesh, z_range=z_range)


def get_connected_components(mask: np.ndarray, min_area_px: int = 16) -> list[dict[str, Any]]:
    """Find connected components in a 2D boolean mask.

    Returns a list of dicts with keys: 'bbox' (ymin, ymax, xmin, xmax), 'sub_mask' (bool array cropped to bbox), 'centroid' (x, y), 'area' (int).
    """
    arr = np.asarray(mask, dtype=bool)
    h, w = arr.shape
    components = []

    try:
        import cv2
        binary = arr.astype(np.uint8) * 255
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        for i in range(1, n_labels):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_area_px:
                continue
            xmin = int(stats[i, cv2.CC_STAT_LEFT])
            ymin = int(stats[i, cv2.CC_STAT_TOP])
            w_comp = int(stats[i, cv2.CC_STAT_WIDTH])
            h_comp = int(stats[i, cv2.CC_STAT_HEIGHT])
            xmax = xmin + w_comp
            ymax = ymin + h_comp

            # Extract sub-mask
            sub_mask = labels[ymin:ymax, xmin:xmax] == i
            cx, cy = centroids[i]
            components.append({
                "bbox": (ymin, ymax, xmin, xmax),
                "sub_mask": sub_mask,
                "centroid": (float(cx), float(cy)),
                "area": area
            })
    except Exception:
        try:
            from scipy.ndimage import label, find_objects
            labeled, num_features = label(arr)
            slices = find_objects(labeled)
            for i, slc in enumerate(slices):
                if slc is None:
                    continue
                comp_mask = labeled[slc] == (i + 1)
                area = int(np.sum(comp_mask))
                if area < min_area_px:
                    continue
                ymin, ymax = slc[0].start, slc[0].stop
                xmin, xmax = slc[1].start, slc[1].stop
                # Centroid
                ys, xs = np.nonzero(comp_mask)
                cx = float(xs.mean()) + xmin
                cy = float(ys.mean()) + ymin
                components.append({
                    "bbox": (ymin, ymax, xmin, xmax),
                    "sub_mask": comp_mask,
                    "centroid": (cx, cy),
                    "area": area
                })
        except Exception:
            # Fallback simple flood fill
            visited = np.zeros_like(arr, dtype=bool)
            for y in range(h):
                for x in range(w):
                    if arr[y, x] and not visited[y, x]:
                        pts = []
                        queue = [(y, x)]
                        visited[y, x] = True
                        while queue:
                            cy, cx = queue.pop(0)
                            pts.append((cy, cx))
                            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                                ny, nx = cy + dy, cx + dx
                                if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] and not visited[ny, nx]:
                                    visited[ny, nx] = True
                                    queue.append((ny, nx))
                        if len(pts) >= min_area_px:
                            ys_pts = [p[0] for p in pts]
                            xs_pts = [p[1] for p in pts]
                            ymin, ymax = min(ys_pts), max(ys_pts) + 1
                            xmin, xmax = min(xs_pts), max(xs_pts) + 1
                            sub_mask = np.zeros((ymax - ymin, xmax - xmin), dtype=bool)
                            ys_offset = [y - ymin for y in ys_pts]
                            xs_offset = [x - xmin for x in xs_pts]
                            sub_mask[ys_offset, xs_offset] = True
                            cx = sum(xs_pts) / len(xs_pts)
                            cy = sum(ys_pts) / len(ys_pts)
                            components.append({
                                "bbox": (ymin, ymax, xmin, xmax),
                                "sub_mask": sub_mask,
                                "centroid": (cx, cy),
                                "area": len(pts)
                            })
    return components


def _build_per_frame_seeds(
    arr: np.ndarray,
    thresholds: tuple[float, ...],
    object_seed: ObjectSeed | None,
    frame_offset: int,
    voxel_size: VoxelSize | None = None,
) -> list[tuple[int, int] | None]:
    """Build a per-frame (x, y) seed list from a single ObjectSeed using overlap-first connected component tracking."""
    n = arr.shape[0]
    seeds: list[tuple[int, int] | None] = [None] * n
    if object_seed is None:
        return seeds

    local_seed_idx = object_seed.frame_index - frame_offset
    if local_seed_idx < 0 or local_seed_idx >= n:
        return seeds

    # Determine max tracking distance in pixels (voxel-aware and user-configurable)
    if object_seed.max_tracking_dist_um is not None and voxel_size is not None:
        max_dist_px = object_seed.max_tracking_dist_um / voxel_size.x_um
    else:
        # Dynamic default: max of 3x seed radius or 15um scaled by voxel size
        if voxel_size is not None:
            max_dist_px = max(3.0 * object_seed.radius, 15.0 / voxel_size.x_um)
        else:
            max_dist_px = max(3.0 * object_seed.radius, 50.0)

    # Initialize at the seed frame
    mask = arr[local_seed_idx] >= thresholds[local_seed_idx]
    components = get_connected_components(mask)
    if not components:
        return seeds

    chosen_comp = None
    h, w = mask.shape
    sx = max(0, min(w - 1, int(round(object_seed.x))))
    sy = max(0, min(h - 1, int(round(object_seed.y))))

    # 1. Look for foreground component landing directly on center coordinate
    for comp in components:
        ymin, ymax, xmin, xmax = comp["bbox"]
        if ymin <= sy < ymax and xmin <= sx < xmax:
            if comp["sub_mask"][sy - ymin, sx - xmin]:
                chosen_comp = comp
                break

    # 2. Overlap-first selection with seed region
    if chosen_comp is None:
        if getattr(object_seed, "type", "circle") == "polygon" and getattr(object_seed, "points", None):
            xs_poly = [pt.x for pt in object_seed.points]
            ys_poly = [pt.y for pt in object_seed.points]
            ymin_p = int(np.floor(min(ys_poly)))
            ymax_p = int(np.ceil(max(ys_poly)))
            xmin_p = int(np.floor(min(xs_poly)))
            xmax_p = int(np.ceil(max(xs_poly)))

            from PIL import Image, ImageDraw
            w_poly = max(1, xmax_p - xmin_p)
            h_poly = max(1, ymax_p - ymin_p)
            poly_img = Image.new("1", (w_poly, h_poly), 0)
            draw = ImageDraw.Draw(poly_img)
            local_verts = [(pt.x - xmin_p, pt.y - ymin_p) for pt in object_seed.points]
            draw.polygon(local_verts, outline=1, fill=1)
            poly_sub_mask = np.array(poly_img, dtype=bool)

            best_overlap = 0
            for comp in components:
                comp_ymin, comp_ymax, comp_xmin, comp_xmax = comp["bbox"]
                ymin_int = max(ymin_p, comp_ymin)
                ymax_int = min(ymax_p, comp_ymax)
                xmin_int = max(xmin_p, comp_xmin)
                xmax_int = min(xmax_p, comp_xmax)

                if ymin_int < ymax_int and xmin_int < xmax_int:
                    poly_slice = poly_sub_mask[ymin_int - ymin_p : ymax_int - ymin_p, xmin_int - xmin_p : xmax_int - xmin_p]
                    comp_slice = comp["sub_mask"][ymin_int - comp_ymin : ymax_int - comp_ymin, xmin_int - comp_xmin : xmax_int - comp_xmin]
                    overlap = np.sum(np.logical_and(poly_slice, comp_slice))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        chosen_comp = comp
        else:
            radius = object_seed.radius
            best_overlap = 0
            c_ymin = int(np.floor(sy - radius))
            c_ymax = int(np.ceil(sy + radius))
            c_xmin = int(np.floor(sx - radius))
            c_xmax = int(np.ceil(sx + radius))

            for comp in components:
                ymin, ymax, xmin, xmax = comp["bbox"]
                ymin_int = max(ymin, c_ymin)
                ymax_int = min(ymax, c_ymax)
                xmin_int = max(xmin, c_xmin)
                xmax_int = min(xmax, c_xmax)

                if ymin_int < ymax_int and xmin_int < xmax_int:
                    ys, xs = np.ogrid[ymin_int:ymax_int, xmin_int:xmax_int]
                    circle_sub = (xs - sx)**2 + (ys - sy)**2 <= radius**2
                    comp_sub = comp["sub_mask"][ymin_int - ymin : ymax_int - ymin, xmin_int - xmin : xmax_int - xmin]
                    overlap = np.sum(np.logical_and(comp_sub, circle_sub))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        chosen_comp = comp

    # 3. Nearest centroid fallback
    if chosen_comp is None:
        best_dist = float("inf")
        for comp in components:
            cx, cy = comp["centroid"]
            dist = (cx - sx) ** 2 + (cy - sy) ** 2
            if dist < best_dist:
                best_dist = dist
                chosen_comp = comp
        if best_dist > max_dist_px ** 2:
            chosen_comp = None

    if chosen_comp is None:
        return seeds

    cx, cy = chosen_comp["centroid"]
    seeds[local_seed_idx] = (int(round(cx)), int(round(cy)))
    seed_comp = chosen_comp

    # Track forward
    curr_comp = seed_comp
    for idx in range(local_seed_idx + 1, n):
        frame_mask = arr[idx] >= thresholds[idx]
        frame_comps = get_connected_components(frame_mask)
        if not frame_comps:
            break

        best_overlap = 0
        overlap_comp = None
        ymin1, ymax1, xmin1, xmax1 = curr_comp["bbox"]
        sub_mask1 = curr_comp["sub_mask"]

        for comp in frame_comps:
            ymin2, ymax2, xmin2, xmax2 = comp["bbox"]
            ymin_int = max(ymin1, ymin2)
            ymax_int = min(ymax1, ymax2)
            xmin_int = max(xmin1, xmin2)
            xmax_int = min(xmax1, xmax2)

            if ymin_int < ymax_int and xmin_int < xmax_int:
                sub_mask1_slice = sub_mask1[ymin_int - ymin1 : ymax_int - ymin1, xmin_int - xmin1 : xmax_int - xmin1]
                sub_mask2_slice = comp["sub_mask"][ymin_int - ymin2 : ymax_int - ymin2, xmin_int - xmin2 : xmax_int - xmin2]
                overlap = np.sum(np.logical_and(sub_mask1_slice, sub_mask2_slice))
                if overlap > best_overlap:
                    best_overlap = overlap
                    overlap_comp = comp

        chosen_comp = None
        if overlap_comp is not None:
            chosen_comp = overlap_comp
        else:
            best_dist = float("inf")
            curr_cx, curr_cy = curr_comp["centroid"]
            for comp in frame_comps:
                ccx, ccy = comp["centroid"]
                dist = (ccx - curr_cx) ** 2 + (ccy - curr_cy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    chosen_comp = comp
            if best_dist > max_dist_px ** 2:
                chosen_comp = None

        if chosen_comp is None:
            break

        curr_cx, curr_cy = chosen_comp["centroid"]
        seeds[idx] = (int(round(curr_cx)), int(round(curr_cy)))
        curr_comp = chosen_comp

    # Track backward
    curr_comp = seed_comp
    for idx in range(local_seed_idx - 1, -1, -1):
        frame_mask = arr[idx] >= thresholds[idx]
        frame_comps = get_connected_components(frame_mask)
        if not frame_comps:
            break

        best_overlap = 0
        overlap_comp = None
        ymin1, ymax1, xmin1, xmax1 = curr_comp["bbox"]
        sub_mask1 = curr_comp["sub_mask"]

        for comp in frame_comps:
            ymin2, ymax2, xmin2, xmax2 = comp["bbox"]
            ymin_int = max(ymin1, ymin2)
            ymax_int = min(ymax1, ymax2)
            xmin_int = max(xmin1, xmin2)
            xmax_int = min(xmax1, xmax2)

            if ymin_int < ymax_int and xmin_int < xmax_int:
                sub_mask1_slice = sub_mask1[ymin_int - ymin1 : ymax_int - ymin1, xmin_int - xmin1 : xmax_int - xmin1]
                sub_mask2_slice = comp["sub_mask"][ymin_int - ymin2 : ymax_int - ymin2, xmin_int - xmin2 : xmax_int - xmin2]
                overlap = np.sum(np.logical_and(sub_mask1_slice, sub_mask2_slice))
                if overlap > best_overlap:
                    best_overlap = overlap
                    overlap_comp = comp

        chosen_comp = None
        if overlap_comp is not None:
            chosen_comp = overlap_comp
        else:
            best_dist = float("inf")
            curr_cx, curr_cy = curr_comp["centroid"]
            for comp in frame_comps:
                ccx, ccy = comp["centroid"]
                dist = (ccx - curr_cx) ** 2 + (ccy - curr_cy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    chosen_comp = comp
            if best_dist > max_dist_px ** 2:
                chosen_comp = None

        if chosen_comp is None:
            break

        curr_cx, curr_cy = chosen_comp["centroid"]
        seeds[idx] = (int(round(curr_cx)), int(round(curr_cy)))
        curr_comp = chosen_comp

    return seeds


def normalize_thresholds(thresholds: float | Sequence[float], *, frame_count: int) -> tuple[float, ...]:
    if np.isscalar(thresholds):
        return tuple(float(thresholds) for _ in range(frame_count))

    values = tuple(float(value) for value in thresholds)
    if len(values) != frame_count:
        raise ValueError("threshold sequence length must match number of frames")
    return values

