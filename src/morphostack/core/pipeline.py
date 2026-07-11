"""Headless analysis pipeline primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence, Any

import numpy as np

from morphostack.core.contours import SegmentationPreview, segmentation_preview
from morphostack.core.mesh import MeshMeasurement, SliceVolumeMeasurement, measure_contour_stack, measure_slice_integrated_volume
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
class FrameTrackingRecord:
    """Per-frame tracking diagnostics (seeded and legacy paths).

    New reason flags are additive for backwards compatibility. Existing
    consumers may keep using ``tracked``, ``touches_roi_boundary``, and
    ``likely_neighbor_merge`` only.
    """

    frame_index: int
    tracked: bool
    centroid_x: float | None = None
    centroid_y: float | None = None
    area_px: int = 0
    # True when the solid mask reaches the ROI crop or full-FOV edge.
    touches_roi_boundary: bool = False
    # Accepted contour with area-jump and/or QC merge suspicion (compat flag).
    likely_neighbor_merge: bool = False
    # Explicit reason taxonomy (optional; None when not applicable / legacy).
    # tracked: None | "ok"
    # untracked: "merge_rejected" | "signal_loss" | "gap" | "cap" | "unreached"
    loss_reason: str | None = None
    # Accepted contour still carries QC merge/contact suspicion.
    merge_suspect: bool = False
    # Frame failed closed because a merge/contact was suspected and rejected.
    merge_rejected: bool = False
    # Solid mask reaches the hard seed/search disk used by seeded isolation.
    touches_seed_disk: bool = False
    # Source method string from seeded path when available (debug/provenance).
    method: str | None = None


@dataclass(frozen=True)
class TrackingDiagnostics:
    records: tuple[FrameTrackingRecord, ...]
    seed_frame_area_px: int = 0

    @property
    def lost_frame_count(self) -> int:
        return sum(1 for record in self.records if not record.tracked)

    @property
    def lost_fraction(self) -> float:
        if not self.records:
            return 0.0
        return self.lost_frame_count / len(self.records)


@dataclass(frozen=True)
class ObjectTrackingResult:
    seeds: list[tuple[int, int] | None]
    tracked_components: list[dict[str, Any] | None]


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



# Public threshold provenance vocabulary (JSON-safe; never use NaN).
THRESHOLD_SEMANTICS = (
    "global_intensity",  # non-seeded / global gate; request == effective
    "seeded_adaptive_local",  # intensity gate inside seed disk
    "polar_ridge",  # polar-DP ridge path; no intensity gate
    "seeded_unavailable",  # lost/gap/reject; no usable intensity gate
    "provisional_global",  # fast one-plane preview using UI/global thr
)


def json_safe_float(value: float | None) -> float | None:
    """Return a finite float or None (never NaN/Inf for JSON)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return v


def threshold_provenance(
    *,
    requested: float,
    method: str = "",
    effective: float | None = None,
    ok: bool = True,
    provisional: bool = False,
    seeded: bool = False,
) -> dict[str, object]:
    """Build explicit threshold fields for one contour/preview result.

    Legacy ``threshold`` is the best numeric value for old clients:
    - intensity-gate methods: the effective gate when known;
    - polar / unavailable: ``None`` (JSON null) — never the unused UI slider.
    """
    req = json_safe_float(requested)
    if req is None:
        req = 0.0
    eff = json_safe_float(effective)
    meth = (method or "").lower()

    if provisional and not seeded:
        sem = "provisional_global"
        return {
            "requested_threshold": req,
            "effective_threshold": req,
            "threshold_semantics": sem,
            "threshold": req,
        }
    if not seeded:
        sem = "global_intensity"
        gate = eff if eff is not None else req
        return {
            "requested_threshold": req,
            "effective_threshold": gate,
            "threshold_semantics": sem,
            "threshold": gate,
        }

    # Seeded path
    if "polar" in meth:
        return {
            "requested_threshold": req,
            "effective_threshold": None,
            "threshold_semantics": "polar_ridge",
            "threshold": None,
        }
    if ok and eff is not None:
        return {
            "requested_threshold": req,
            "effective_threshold": eff,
            "threshold_semantics": "seeded_adaptive_local",
            "threshold": eff,
        }
    # Failed / gap / reject / ok without intensity gate
    return {
        "requested_threshold": req,
        "effective_threshold": None,
        "threshold_semantics": "seeded_unavailable",
        "threshold": None,
    }


@dataclass(frozen=True)
class FrameAnalysis:
    frame_index: int
    # Legacy numeric field: effective intensity gate when applicable; None if N/A.
    threshold: float | None
    profile: AnalysisProfile
    contour: np.ndarray | None
    metrics: ContourMetrics | None
    preview: SegmentationPreview
    skel_perimeter_um: float | None = None
    skel_perimeter_px: float | None = None
    skel_ok: bool = False
    requested_threshold: float | None = None
    effective_threshold: float | None = None
    threshold_semantics: str = "global_intensity"


def normalize_excluded_frames(excluded_frames: Sequence[int] | None) -> frozenset[int]:
    if not excluded_frames:
        return frozenset()
    return frozenset(int(frame_index) for frame_index in excluded_frames)


def mesh_contours_from_analysis(analysis: StackAnalysis) -> tuple[np.ndarray | None, ...]:
    return tuple(
        None if frame.frame_index in analysis.excluded_frames else frame.contour
        for frame in analysis.frames
    )


# Tight XY crop around a seed so active_surfaces / tracking never process a full
# multi-vesicle field. half-extent = max(min_pad_px, pad_scale * radius).
SEED_ISOLATION_PAD_SCALE = 2.0
SEED_ISOLATION_MIN_PAD_PX = 32


def seed_isolation_roi(
    seed: ObjectSeed,
    *,
    width: int,
    height: int,
    pad_scale: float = SEED_ISOLATION_PAD_SCALE,
    min_pad_px: int = SEED_ISOLATION_MIN_PAD_PX,
) -> RectROI:
    """Build a tight XY crop around an object seed (circle or polygon).

    Coordinates are full-image / stack-plane pixels (same frame as ``seed``).
    Z is not clipped — full selected Z range is kept for mesh height.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    if getattr(seed, "type", "circle") == "polygon" and seed.points:
        xs = [float(pt.x) for pt in seed.points]
        ys = [float(pt.y) for pt in seed.points]
        if not xs:
            raise ValueError("Polygon seed must have a non-empty list of points")
        span = max(max(xs) - min(xs), max(ys) - min(ys), float(seed.radius), 1.0)
        pad = max(float(min_pad_px), float(pad_scale) * span * 0.5)
        x_min_f = min(xs) - pad
        x_max_f = max(xs) + pad
        y_min_f = min(ys) - pad
        y_max_f = max(ys) + pad
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
    else:
        half = max(float(min_pad_px), float(pad_scale) * max(float(seed.radius), 1.0))
        cx = float(seed.x)
        cy = float(seed.y)
        x_min_f = cx - half
        x_max_f = cx + half
        y_min_f = cy - half
        y_max_f = cy + half

    x0 = max(0, int(np.floor(x_min_f)))
    x1 = min(width, int(np.ceil(x_max_f)))
    y0 = max(0, int(np.floor(y_min_f)))
    y1 = min(height, int(np.ceil(y_max_f)))

    if x1 <= x0:
        x0 = max(0, min(width - 1, int(round(cx))))
        x1 = min(width, x0 + 1)
    if y1 <= y0:
        y0 = max(0, min(height - 1, int(round(cy))))
        y1 = min(height, y0 + 1)

    return RectROI(xmin=x0, xmax=x1, ymin=y0, ymax=y1)


def intersect_rect_roi(a: RectROI, b: RectROI) -> RectROI:
    """Return the intersection of two axis-aligned ROIs; raise if empty."""
    x0 = max(a.xmin, b.xmin)
    x1 = min(a.xmax, b.xmax)
    y0 = max(a.ymin, b.ymin)
    y1 = min(a.ymax, b.ymax)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("ROI intersection is empty; seed isolation does not overlap user ROI")
    return RectROI(xmin=x0, xmax=x1, ymin=y0, ymax=y1)


def crop_stack_xy(stack: np.ndarray, roi: RectROI) -> np.ndarray:
    """Crop a (z, y, x) stack to ``roi`` bounds (actual slice, not zero-mask)."""
    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("crop_stack_xy expects a stack shaped as (z, y, x)")
    height, width = arr.shape[1], arr.shape[2]
    x0 = max(0, min(width, roi.xmin))
    x1 = max(0, min(width, roi.xmax))
    y0 = max(0, min(height, roi.ymin))
    y1 = max(0, min(height, roi.ymax))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("ROI bounds must define a non-empty rectangle")
    return np.ascontiguousarray(arr[:, y0:y1, x0:x1])


def _offset_tracking_diagnostics(
    diagnostics: TrackingDiagnostics | None,
    *,
    x_offset: int,
    y_offset: int,
) -> TrackingDiagnostics | None:
    """Map tracking centroids from crop-local to full-image coordinates."""
    if diagnostics is None or (x_offset == 0 and y_offset == 0):
        return diagnostics
    records = []
    for record in diagnostics.records:
        if not record.tracked or record.centroid_x is None or record.centroid_y is None:
            records.append(record)
            continue
        records.append(
            FrameTrackingRecord(
                frame_index=record.frame_index,
                tracked=record.tracked,
                centroid_x=record.centroid_x + x_offset,
                centroid_y=record.centroid_y + y_offset,
                area_px=record.area_px,
                touches_roi_boundary=record.touches_roi_boundary,
                likely_neighbor_merge=record.likely_neighbor_merge,
                loss_reason=record.loss_reason,
                merge_suspect=record.merge_suspect,
                merge_rejected=record.merge_rejected,
                touches_seed_disk=record.touches_seed_disk,
                method=record.method,
            )
        )
    return TrackingDiagnostics(records=tuple(records), seed_frame_area_px=diagnostics.seed_frame_area_px)


def _frame_with_global_contour(frame: FrameAnalysis, transform: StackViewTransform) -> FrameAnalysis:
    """Return a copy of ``frame`` with contour coordinates mapped to full image."""
    global_contour = transform.to_global_contour(frame.contour)
    if global_contour is frame.contour:
        return frame
    preview = frame.preview
    if preview.contour is not None or frame.contour is not None:
        preview = SegmentationPreview(
            threshold=preview.threshold,
            contour=global_contour,
            area_px2=preview.area_px2,
            perimeter_px=preview.perimeter_px,
            circularity=preview.circularity,
            method=preview.method,
        )
    return FrameAnalysis(
        frame_index=frame.frame_index,
        threshold=frame.threshold,
        profile=frame.profile,
        contour=global_contour,
        metrics=frame.metrics,
        preview=preview,
        skel_perimeter_um=frame.skel_perimeter_um,
        skel_perimeter_px=frame.skel_perimeter_px,
        skel_ok=frame.skel_ok,
        requested_threshold=frame.requested_threshold,
        effective_threshold=frame.effective_threshold,
        threshold_semantics=frame.threshold_semantics,
    )


@dataclass(frozen=True)
class StackAnalysis:
    voxel_size: VoxelSize
    profile: AnalysisProfile
    frames: tuple[FrameAnalysis, ...]
    mesh: MeshMeasurement | None = None
    slice_volume: SliceVolumeMeasurement | None = None
    z_range: ZRange | None = None
    tracking: TrackingDiagnostics | None = None
    excluded_frames: frozenset[int] = field(default_factory=frozenset)

    @property
    def valid_frames(self) -> tuple[FrameAnalysis, ...]:
        return tuple(
            frame
            for frame in self.frames
            if frame.metrics is not None and frame.frame_index not in self.excluded_frames
        )


def analyze_frame(
    image: np.ndarray,
    *,
    frame_index: int,
    threshold: float,
    voxel_size: VoxelSize,
    profile: str | None = DEFAULT_PROFILE,
    prefer_opencv: bool = True,
    object_seed: tuple[int, int] | None = None,
    enable_skeleton: bool = False,
    skeleton_prune_pix: float = 1.0,
) -> FrameAnalysis:
    analysis_profile = normalize_profile(profile)
    preview = segmentation_preview(image, threshold, prefer_opencv=prefer_opencv, object_seed=object_seed)
    metrics = None
    if preview.contour is not None:
        metrics = contour_metrics(preview.contour, voxel_size)

    skel_perimeter_um: float | None = None
    skel_perimeter_px: float | None = None
    skel_ok = False
    if enable_skeleton and preview.contour is not None:
        skel_perimeter_um, skel_perimeter_px, skel_ok = _skeleton_fields_for_frame(
            image,
            threshold=threshold,
            object_seed=object_seed,
            prune_pix=skeleton_prune_pix,
            voxel_x_um=voxel_size.x_um,
        )

    thr_meta = threshold_provenance(
        requested=float(threshold),
        method=str(preview.method or ""),
        effective=float(threshold),
        ok=preview.contour is not None,
        seeded=False,
    )
    return FrameAnalysis(
        frame_index=frame_index,
        threshold=thr_meta["threshold"],  # type: ignore[arg-type]
        profile=analysis_profile,
        contour=preview.contour,
        metrics=metrics,
        preview=preview,
        skel_perimeter_um=skel_perimeter_um,
        skel_perimeter_px=skel_perimeter_px,
        skel_ok=skel_ok,
        requested_threshold=thr_meta["requested_threshold"],  # type: ignore[arg-type]
        effective_threshold=thr_meta["effective_threshold"],  # type: ignore[arg-type]
        threshold_semantics=str(thr_meta["threshold_semantics"]),
    )


def _skeleton_fields_for_frame(
    image: np.ndarray,
    *,
    threshold: float,
    object_seed: tuple[int, int] | None,
    prune_pix: float,
    voxel_x_um: float,
) -> tuple[float | None, float | None, bool]:
    """Return (skel_perimeter_um, skel_perimeter_px, skel_ok) for one frame."""
    try:
        from morphostack.core.skeleton import measure_skeleton

        mask = np.asarray(image) >= threshold
        _, skel = measure_skeleton(
            mask,
            object_seed=object_seed,
            prune_threshold_pix=prune_pix,
            voxel_x_um=voxel_x_um,
        )
        if not skel.ok:
            return 0.0, 0.0, False
        return skel.perimeter_um, skel.perimeter_px, True
    except Exception:
        return None, None, False


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
    active_surfaces_watershed_pre_split: bool = True,
    active_surfaces_fast: bool = False,
    active_surfaces_relaxation_steps: int | None = None,
    active_surfaces_optimization_steps: int | None = None,
    excluded_frames: Sequence[int] | None = None,
    enable_skeleton: bool = False,
    skeleton_prune_pix: float = 1.0,
) -> StackAnalysis:
    """Analyze a grayscale Z-stack.

    When ``object_seed`` is set, a tight XY crop is taken around the seed so
    watershed / active-surfaces / tracking never process neighboring vesicles in
    a crowded field. Contours are returned in full-image coordinates.

    ``active_surfaces_fast`` selects reduced relaxation/optimization steps
    (mesh preview). Full Analyze keeps the quality defaults unless step
    overrides are provided.
    """
    analysis_profile = normalize_profile(profile)
    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("analyze_stack expects a grayscale stack shaped as (z, y, x)")

    raw_shape = (int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2]))
    frame_offset = 0
    if z_range is not None:
        frame_offset = max(0, min(arr.shape[0], z_range.zmin))
        arr = apply_z_range(arr, zmin=z_range.zmin, zmax=z_range.zmax)

    # Full-plane size after Z crop (XY still full). Used for mesh rasterization
    # when contours are mapped back to global coordinates after seed isolation.
    full_yx_shape = (int(arr.shape[1]), int(arr.shape[2]))

    # Validate seed against the *user* ROI / Z / stack bounds before isolation.
    user_transform = StackViewTransform.create(roi=roi, z_range=z_range, raw_shape=raw_shape)
    if object_seed is not None:
        user_transform.to_local_seed_object(object_seed)

    # Actual XY crop (slice) vs legacy zero-mask ROI.
    # - Seed + AS: always isolate (intersect user ROI if present).
    # - Seed + non-AS without user ROI: isolate (crowded vesicle fields).
    # - Seed + non-AS with user ROI: crop to user ROI so local seed coords match.
    # - No seed + user ROI: zero-mask only (legacy; contours stay full-index).
    crop_roi: RectROI | None = None
    if object_seed is not None:
        if analysis_profile == "active_surfaces":
            isolation = seed_isolation_roi(
                object_seed,
                width=full_yx_shape[1],
                height=full_yx_shape[0],
            )
            crop_roi = intersect_rect_roi(roi, isolation) if roi is not None else isolation
        else:
            crop_roi = roi
        if crop_roi is not None:
            arr = crop_stack_xy(arr, crop_roi)
            transform = StackViewTransform.create(roi=crop_roi, z_range=z_range, raw_shape=raw_shape)
        else:
            transform = StackViewTransform.create(roi=None, z_range=z_range, raw_shape=raw_shape)
    else:
        if roi is not None:
            arr = apply_rect_roi(
                arr,
                xmin=roi.xmin,
                xmax=roi.xmax,
                ymin=roi.ymin,
                ymax=roi.ymax,
            )
        transform = StackViewTransform.create(roi=roi, z_range=z_range, raw_shape=raw_shape)

    per_frame_thresholds = normalize_thresholds(thresholds, frame_count=arr.shape[0])

    local_seed = None
    if object_seed is not None:
        local_seed = transform.to_local_seed_object(object_seed)

    tracking: TrackingDiagnostics | None = None

    if analysis_profile == "active_surfaces":
        if local_seed is None:
            raise ValueError("Active surfaces profile requires an object seed")

        from morphostack.core.active_surfaces import (
            ACTIVE_SURFACES_DEFAULTS,
            ACTIVE_SURFACES_FAST_DEFAULTS,
            apply_watershed_pre_split_stack,
            run_active_surfaces_optimization,
            surfels_to_mask_stack,
            watershed_split_stack,
        )
        voxel_x = voxel_size.x_um if voxel_size is not None else 1.0
        voxel_z = voxel_size.z_um if voxel_size is not None else 1.0

        poly_points = None
        if local_seed.type == "polygon" and local_seed.points is not None:
            poly_points = [(pt.x, pt.y) for pt in local_seed.points]

        step_defaults = ACTIVE_SURFACES_FAST_DEFAULTS if active_surfaces_fast else ACTIVE_SURFACES_DEFAULTS
        relaxation_steps = (
            int(active_surfaces_relaxation_steps)
            if active_surfaces_relaxation_steps is not None
            else int(step_defaults["relaxation_steps"])
        )
        optimization_steps = (
            int(active_surfaces_optimization_steps)
            if active_surfaces_optimization_steps is not None
            else int(step_defaults["optimization_steps"])
        )
        if relaxation_steps < 0 or optimization_steps < 0:
            raise ValueError("active surfaces step counts must be non-negative")

        watershed_splits = (
            watershed_split_stack(
                arr,
                per_frame_thresholds,
                seed_x=local_seed.x,
                seed_y=local_seed.y,
                seed_radius=local_seed.radius,
                polygon_points=poly_points,
            )
            if active_surfaces_watershed_pre_split
            else None
        )
        arr_for_active_surfaces = apply_watershed_pre_split_stack(
            arr,
            per_frame_thresholds,
            seed_x=local_seed.x,
            seed_y=local_seed.y,
            seed_radius=local_seed.radius,
            polygon_points=poly_points,
            enabled=active_surfaces_watershed_pre_split,
            splits=watershed_splits,
        )

        surfels = run_active_surfaces_optimization(
            arr=arr_for_active_surfaces,
            seed_x=local_seed.x,
            seed_y=local_seed.y,
            seed_z=local_seed.frame_index,
            seed_radius=local_seed.radius,
            voxel_size_x=voxel_x,
            voxel_size_z=voxel_z,
            d_0=float(ACTIVE_SURFACES_DEFAULTS["d_0"]),
            f_pressure=float(ACTIVE_SURFACES_DEFAULTS["f_pressure"]),
            k_grad=float(ACTIVE_SURFACES_DEFAULTS["k_grad"]),
            relaxation_steps=relaxation_steps,
            optimization_steps=optimization_steps,
            polygon_points=poly_points,
        )

        ZScale = voxel_z / voxel_x if voxel_x > 0.0 else 1.0
        active_surfaces_mask = surfels_to_mask_stack(
            surfels,
            arr.shape,
            ZScale,
            seed_x=local_seed.x,
            seed_y=local_seed.y,
            seed_radius=local_seed.radius,
            polygon_points=poly_points,
            d_0=2.0,
            slice_fallback=watershed_splits,
        )

        from morphostack.core.contours import SegmentationPreview, contour_circularity
        from morphostack.core.metrics import contour_metrics
        from morphostack.core.contours import largest_opencv_contour, largest_component_boundary

        frames_list = []
        for idx in range(arr.shape[0]):
            frame_mask = active_surfaces_mask[idx]
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
                    method="active_surfaces"
                )
            else:
                metrics = None
                preview = SegmentationPreview(
                    threshold=per_frame_thresholds[idx],
                    contour=None,
                    area_px2=0.0,
                    perimeter_px=0.0,
                    circularity=0.0,
                    method="active_surfaces_empty"
                )

            skel_perimeter_um: float | None = None
            skel_perimeter_px: float | None = None
            skel_ok = False
            if enable_skeleton and metrics is not None:
                seed_xy = (int(round(local_seed.x)), int(round(local_seed.y))) if local_seed is not None else None
                skel_perimeter_um, skel_perimeter_px, skel_ok = _skeleton_fields_for_frame(
                    frame_mask.astype(np.float32),
                    threshold=0.5,
                    object_seed=seed_xy,
                    prune_pix=skeleton_prune_pix,
                    voxel_x_um=voxel_size.x_um,
                )

            thr_meta = threshold_provenance(
                requested=float(per_frame_thresholds[idx]),
                method=str(preview.method),
                effective=None,  # active surfaces does not use the UI intensity gate
                ok=metrics is not None,
                seeded=True,
            )
            fa = FrameAnalysis(
                frame_index=idx + frame_offset,
                threshold=thr_meta["threshold"],  # type: ignore[arg-type]
                profile=analysis_profile,
                contour=global_contour,
                metrics=metrics,
                preview=preview,
                skel_perimeter_um=skel_perimeter_um,
                skel_perimeter_px=skel_perimeter_px,
                skel_ok=skel_ok,
                requested_threshold=thr_meta["requested_threshold"],  # type: ignore[arg-type]
                effective_threshold=thr_meta["effective_threshold"],  # type: ignore[arg-type]
                threshold_semantics=str(thr_meta["threshold_semantics"]),
            )
            frames_list.append(fa)

        frames = tuple(frames_list)
    else:
        from morphostack.core.contours import SegmentationPreview
        from morphostack.core.metrics import contour_metrics as _contour_metrics
        from morphostack.core.contours import contour_circularity

        use_seeded_vesicle = (
            local_seed is not None
            and analysis_profile in ("vesicle", "rbc")
        )

        if use_seeded_vesicle:
            # Circle-constrained path (LimeSeg OvalRoi model): user R is law.
            from morphostack.core.seeded_vesicle import effective_seed_radius, track_seeded_vesicle_stack

            jump_px = None
            if local_seed.max_tracking_dist_um is not None and voxel_size is not None:
                jump_px = float(local_seed.max_tracking_dist_um) / max(voxel_size.x_um, 1e-9)
            seed_r = effective_seed_radius(float(local_seed.radius) if local_seed.radius else None)
            seeded_results = track_seeded_vesicle_stack(
                arr,
                seed_x=float(local_seed.x),
                seed_y=float(local_seed.y),
                seed_frame=int(local_seed.frame_index),
                seed_radius=seed_r,
                max_centroid_jump_px=jump_px,
            )
            frames_list = []
            track_records: list[FrameTrackingRecord] = []
            # Resolve seed-frame area first so pre-seed Z frames can still get merge flags.
            seed_area_px = 0
            seed_local_idx = int(local_seed.frame_index)
            if 0 <= seed_local_idx < len(seeded_results):
                seed_res = seeded_results[seed_local_idx]
                if seed_res.ok and seed_res.area_px > 0:
                    seed_area_px = int(round(seed_res.area_px))
            height_local = int(arr.shape[1])
            width_local = int(arr.shape[2])
            for idx, sres in enumerate(seeded_results):
                ui_thr = float(per_frame_thresholds[idx])
                thr_meta = threshold_provenance(
                    requested=ui_thr,
                    method=str(sres.method or ""),
                    effective=getattr(sres, "effective_threshold", None),
                    ok=bool(sres.ok and sres.contour_xy is not None),
                    seeded=True,
                )
                # SegmentationPreview keeps a finite float for drawing only.
                preview_thr = (
                    float(thr_meta["effective_threshold"])
                    if thr_meta["effective_threshold"] is not None
                    else float(ui_thr)
                )
                if sres.ok and sres.contour_xy is not None:
                    global_contour = transform.to_global_contour(sres.contour_xy)
                    metrics = _contour_metrics(sres.contour_xy, voxel_size)
                    circ = contour_circularity(sres.contour_xy)
                    preview = SegmentationPreview(
                        threshold=preview_thr,
                        contour=global_contour,
                        area_px2=float(sres.area_px),
                        perimeter_px=float(sres.perimeter_px),
                        circularity=circ,
                        method=sres.method,
                    )
                    skel_um, skel_px, skel_ok = None, None, False
                    if enable_skeleton and sres.solid_mask is not None:
                        skel_um, skel_px, skel_ok = _skeleton_fields_for_frame(
                            sres.solid_mask.astype(np.float32),
                            threshold=0.5,
                            object_seed=(int(round(sres.center_xy[0])), int(round(sres.center_xy[1]))),
                            prune_pix=skeleton_prune_pix,
                            voxel_x_um=voxel_size.x_um,
                        )
                    fa = FrameAnalysis(
                        frame_index=idx + frame_offset,
                        threshold=thr_meta["threshold"],  # type: ignore[arg-type]
                        profile=analysis_profile,
                        contour=global_contour,
                        metrics=metrics,
                        preview=preview,
                        skel_perimeter_um=skel_um,
                        skel_perimeter_px=skel_px,
                        skel_ok=skel_ok,
                        requested_threshold=thr_meta["requested_threshold"],  # type: ignore[arg-type]
                        effective_threshold=thr_meta["effective_threshold"],  # type: ignore[arg-type]
                        threshold_semantics=str(thr_meta["threshold_semantics"]),
                    )
                    gx = sres.center_xy[0] + transform.x_offset
                    gy = sres.center_xy[1] + transform.y_offset
                    area_px = int(round(sres.area_px))
                    # ``arr`` is already Z/ROI-cropped; solid_mask is in that local frame.
                    touches_boundary = _solid_mask_touches_boundary(
                        sres.solid_mask, height=height_local, width=width_local
                    )
                    touches_disk = _solid_mask_touches_seed_disk(
                        sres.solid_mask,
                        seed_x=float(sres.center_xy[0]),
                        seed_y=float(sres.center_xy[1]),
                        seed_radius=seed_r,
                    )
                    # Match legacy area-jump rule, plus seeded QC merge suspicion when present.
                    area_merge = seed_area_px > 0 and area_px > seed_area_px * 2.5
                    qc_merge = bool(getattr(sres, "merge_suspect", False))
                    merge_suspect = bool(area_merge or qc_merge)
                    track_records.append(
                        FrameTrackingRecord(
                            frame_index=idx + frame_offset,
                            tracked=True,
                            centroid_x=gx,
                            centroid_y=gy,
                            area_px=area_px,
                            touches_roi_boundary=touches_boundary,
                            likely_neighbor_merge=merge_suspect,
                            loss_reason=None,
                            merge_suspect=merge_suspect,
                            merge_rejected=False,
                            touches_seed_disk=touches_disk,
                            method=str(sres.method) if sres.method else None,
                        )
                    )
                else:
                    method_name = sres.method if sres else "seeded_lost"
                    thr_meta = threshold_provenance(
                        requested=ui_thr,
                        method=str(method_name),
                        effective=getattr(sres, "effective_threshold", None) if sres else None,
                        ok=False,
                        seeded=True,
                    )
                    preview = SegmentationPreview(
                        threshold=float(ui_thr),
                        contour=None,
                        area_px2=0.0,
                        perimeter_px=0.0,
                        circularity=0.0,
                        method=method_name,
                    )
                    fa = FrameAnalysis(
                        frame_index=idx + frame_offset,
                        threshold=thr_meta["threshold"],  # type: ignore[arg-type]
                        profile=analysis_profile,
                        contour=None,
                        metrics=None,
                        preview=preview,
                        requested_threshold=thr_meta["requested_threshold"],  # type: ignore[arg-type]
                        effective_threshold=thr_meta["effective_threshold"],  # type: ignore[arg-type]
                        threshold_semantics=str(thr_meta["threshold_semantics"]),
                    )
                    # Untracked: still propagate why (merge reject vs ordinary loss).
                    merge_rejected = (
                        method_name == "circle_seed_merge_reject"
                        or (
                            bool(getattr(sres, "merge_suspect", False))
                            and "merge" in str(method_name).lower()
                        )
                    )
                    track_records.append(
                        FrameTrackingRecord(
                            frame_index=idx + frame_offset,
                            tracked=False,
                            loss_reason=_seeded_loss_reason(
                                method_name, merge_rejected=merge_rejected
                            ),
                            merge_suspect=bool(getattr(sres, "merge_suspect", False))
                            if sres is not None
                            else False,
                            merge_rejected=merge_rejected,
                            # Compat: rejected merges are not "likely_neighbor_merge" on
                            # accepted contours; they get merge_rejected instead.
                            likely_neighbor_merge=False,
                            method=str(method_name) if method_name else None,
                        )
                    )
                frames_list.append(fa)
            frames = tuple(frames_list)
            tracking = TrackingDiagnostics(
                records=tuple(track_records),
                seed_frame_area_px=seed_area_px,
            )
        else:
            # Legacy threshold + CC tracking (no seed, or non-vesicle profile).
            tracking_result = _track_object(arr, per_frame_thresholds, local_seed, 0, voxel_size=voxel_size)
            per_frame_seeds = tracking_result.seeds
            tracking = (
                build_tracking_diagnostics(tracking_result, frame_offset=frame_offset, image_shape=arr.shape[1:])
                if object_seed is not None
                else None
            )
            tracking = _offset_tracking_diagnostics(
                tracking,
                x_offset=transform.x_offset,
                y_offset=transform.y_offset,
            )

            frames_list = []
            for idx, frame in enumerate(arr):
                if object_seed is not None and per_frame_seeds[idx] is None:
                    thr_meta = threshold_provenance(
                        requested=float(per_frame_thresholds[idx]),
                        method="seed_lost",
                        effective=None,
                        ok=False,
                        seeded=True,
                    )
                    preview = SegmentationPreview(
                        threshold=float(per_frame_thresholds[idx]),
                        contour=None,
                        area_px2=0.0,
                        perimeter_px=0.0,
                        circularity=0.0,
                        method="seed_lost",
                    )
                    fa = FrameAnalysis(
                        frame_index=idx + frame_offset,
                        threshold=thr_meta["threshold"],  # type: ignore[arg-type]
                        profile=analysis_profile,
                        contour=None,
                        metrics=None,
                        preview=preview,
                        requested_threshold=thr_meta["requested_threshold"],  # type: ignore[arg-type]
                        effective_threshold=thr_meta["effective_threshold"],  # type: ignore[arg-type]
                        threshold_semantics=str(thr_meta["threshold_semantics"]),
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
                        enable_skeleton=enable_skeleton,
                        skeleton_prune_pix=skeleton_prune_pix,
                    )
                    if crop_roi is not None:
                        fa = _frame_with_global_contour(fa, transform)
                    frames_list.append(fa)
            frames = tuple(frames_list)

    excluded_set = normalize_excluded_frames(excluded_frames)
    if excluded_set:
        frame_indices = {frame.frame_index for frame in frames}
        invalid = sorted(excluded_set - frame_indices)
        if invalid:
            raise ValueError(f"excluded frame index(es) not in analyzed stack: {invalid}")
    mesh = None
    slice_volume = None
    if include_mesh:
        mesh_contours = tuple(
            None if frame.frame_index in excluded_set else frame.contour for frame in frames
        )
        # Contours are full-image XY after isolation; rasterize into full YX plane.
        mesh_shape = (len(frames), full_yx_shape[0], full_yx_shape[1])
        mesh = measure_contour_stack(
            mesh_contours,
            shape=mesh_shape,
            voxel=voxel_size,
        )
        slice_volume = measure_slice_integrated_volume(mesh_contours, voxel=voxel_size)
    return StackAnalysis(
        voxel_size=voxel_size,
        profile=analysis_profile,
        frames=frames,
        mesh=mesh,
        slice_volume=slice_volume,
        z_range=z_range,
        tracking=tracking,
        excluded_frames=excluded_set,
    )


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


def _component_touches_boundary(comp: dict[str, Any], *, height: int, width: int) -> bool:
    ymin, ymax, xmin, xmax = comp["bbox"]
    return ymin <= 0 or xmin <= 0 or ymax >= height or xmax >= width


def _solid_mask_touches_boundary(
    mask: np.ndarray | None,
    *,
    height: int,
    width: int,
) -> bool:
    """True if a solid mask reaches the local crop / FOV edge (clipped component)."""
    if mask is None:
        return False
    solid = np.asarray(mask, dtype=bool)
    if solid.ndim != 2 or not np.any(solid):
        return False
    # Mask may be full-stack size or already local; compare to provided crop shape.
    h = min(int(height), int(solid.shape[0]))
    w = min(int(width), int(solid.shape[1]))
    if h <= 0 or w <= 0:
        return False
    view = solid[:h, :w]
    return bool(
        np.any(view[0, :])
        or np.any(view[h - 1, :])
        or np.any(view[:, 0])
        or np.any(view[:, w - 1])
    )


def _solid_mask_touches_seed_disk(
    mask: np.ndarray | None,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    disk_scale: float = 1.15,
    edge_band_px: float = 1.5,
) -> bool:
    """True if solid mask reaches the hard seed/search disk boundary.

    Seeded isolation restricts FG to a disk of radius ``seed_radius * disk_scale``
    (see ``segment_slice_seeded``). Contact with that circle is **search-disk
    clipping**, distinct from ROI/FOV edge contact.
    """
    if mask is None:
        return False
    solid = np.asarray(mask, dtype=bool)
    if solid.ndim != 2 or not np.any(solid):
        return False
    r_disk = max(float(seed_radius) * float(disk_scale), 1.0)
    ys, xs = np.nonzero(solid)
    if ys.size == 0:
        return False
    dist = np.hypot(xs.astype(np.float64) - float(seed_x), ys.astype(np.float64) - float(seed_y))
    # Any solid pixel within ``edge_band_px`` of the disk rim counts as clipping.
    return bool(np.any(dist >= (r_disk - float(edge_band_px))))


def _seeded_loss_reason(method: str | None, *, merge_rejected: bool) -> str | None:
    """Map seeded method / flags to a stable loss_reason string."""
    if merge_rejected:
        return "merge_rejected"
    m = (method or "").lower()
    if "gap" in m:
        return "gap"
    if "unreached" in m:
        return "unreached"
    if "cap" in m:
        return "cap"
    if "fail" in m or "lost" in m:
        return "signal_loss"
    return "signal_loss"


def build_tracking_diagnostics(
    result: ObjectTrackingResult,
    *,
    frame_offset: int,
    image_shape: tuple[int, int],
) -> TrackingDiagnostics:
    height, width = image_shape
    seed_area = 0
    records: list[FrameTrackingRecord] = []
    for idx, comp in enumerate(result.tracked_components):
        if comp is None:
            records.append(FrameTrackingRecord(frame_index=idx + frame_offset, tracked=False))
            continue
        area_px = int(comp.get("area", 0))
        if seed_area == 0:
            seed_area = area_px
        cx, cy = comp["centroid"]
        records.append(
            FrameTrackingRecord(
                frame_index=idx + frame_offset,
                tracked=True,
                centroid_x=float(cx),
                centroid_y=float(cy),
                area_px=area_px,
                touches_roi_boundary=_component_touches_boundary(comp, height=height, width=width),
                likely_neighbor_merge=seed_area > 0 and area_px > seed_area * 2.5,
            )
        )
    return TrackingDiagnostics(records=tuple(records), seed_frame_area_px=seed_area)


def tracking_diagnostics_payload(diagnostics: TrackingDiagnostics | None) -> list[dict[str, object]] | None:
    if diagnostics is None:
        return None
    return [
        {
            "frame_index": record.frame_index,
            "tracked": record.tracked,
            "centroid_x": record.centroid_x,
            "centroid_y": record.centroid_y,
            "area_px": record.area_px,
            "touches_roi_boundary": record.touches_roi_boundary,
            "likely_neighbor_merge": record.likely_neighbor_merge,
            # Additive reason fields (backwards-compatible for old consumers).
            "loss_reason": record.loss_reason,
            "merge_suspect": record.merge_suspect,
            "merge_rejected": record.merge_rejected,
            "touches_seed_disk": record.touches_seed_disk,
            "method": record.method,
        }
        for record in diagnostics.records
    ]


def object_seed_payload(seed: ObjectSeed | None) -> dict[str, object] | None:
    if seed is None:
        return None
    payload: dict[str, object] = {
        "x": seed.x,
        "y": seed.y,
        "frame_index": seed.frame_index,
        "radius": seed.radius,
        "type": seed.type,
        "max_tracking_dist_um": seed.max_tracking_dist_um,
    }
    if seed.points is not None:
        payload["points"] = [{"x": point.x, "y": point.y} for point in seed.points]
    return payload


def _track_object(
    arr: np.ndarray,
    thresholds: tuple[float, ...],
    object_seed: ObjectSeed | None,
    frame_offset: int,
    voxel_size: VoxelSize | None = None,
) -> ObjectTrackingResult:
    """Track one object across frames and return per-frame seeds plus component metadata."""
    n = arr.shape[0]
    seeds: list[tuple[int, int] | None] = [None] * n
    tracked_components: list[dict[str, Any] | None] = [None] * n
    if object_seed is None:
        return ObjectTrackingResult(seeds=seeds, tracked_components=tracked_components)

    local_seed_idx = object_seed.frame_index - frame_offset
    if local_seed_idx < 0 or local_seed_idx >= n:
        return ObjectTrackingResult(seeds=seeds, tracked_components=tracked_components)

    # Max lateral drift (GUVs float in solvent across Z). Generous default.
    if object_seed.max_tracking_dist_um is not None and voxel_size is not None:
        max_dist_px = object_seed.max_tracking_dist_um / voxel_size.x_um
    else:
        if voxel_size is not None:
            max_dist_px = max(6.0 * object_seed.radius, 40.0 / max(voxel_size.x_um, 1e-6), 80.0)
        else:
            max_dist_px = max(6.0 * object_seed.radius, 80.0)

    from morphostack.core.object_select import pick_component, refine_component_near_point

    # Initialize at the seed frame
    mask = arr[local_seed_idx] >= thresholds[local_seed_idx]
    components = get_connected_components(mask)
    if not components:
        return ObjectTrackingResult(seeds=seeds, tracked_components=tracked_components)

    h, w = mask.shape
    sx = max(0, min(w - 1, int(round(object_seed.x))))
    sy = max(0, min(h - 1, int(round(object_seed.y))))
    select_r = float(object_seed.radius)

    chosen_comp = pick_component(
        components,
        seed_x=float(sx),
        seed_y=float(sy),
        seed_radius=select_r,
        ref_area=None,
    )
    if chosen_comp is None:
        return ObjectTrackingResult(seeds=seeds, tracked_components=tracked_components)

    # Clip multi-lobe merges on the seed frame (touching GUVs).
    chosen_comp = refine_component_near_point(
        chosen_comp,
        seed_x=float(sx),
        seed_y=float(sy),
        max_radius=select_r * 1.35,
        ref_area=None,
    )
    ref_area = float(chosen_comp["area"])
    cx, cy = chosen_comp["centroid"]
    seeds[local_seed_idx] = (int(round(cx)), int(round(cy)))
    tracked_components[local_seed_idx] = chosen_comp
    seed_comp = chosen_comp

    def _step_track(curr_comp: dict[str, Any], idx: int) -> dict[str, Any] | None:
        frame_mask = arr[idx] >= thresholds[idx]
        frame_comps = get_connected_components(frame_mask)
        if not frame_comps:
            return None

        curr_area = float(curr_comp["area"])
        ymin1, ymax1, xmin1, xmax1 = curr_comp["bbox"]
        sub_mask1 = curr_comp["sub_mask"]
        curr_cx, curr_cy = curr_comp["centroid"]
        # Predict position: objects drift slowly; use last centroid as search center.
        search_r = max(select_r, np.sqrt(max(curr_area, 1.0) / np.pi) * 1.5)

        ranked: list[tuple[float, float, dict[str, Any]]] = []
        for comp in frame_comps:
            area = float(comp["area"])
            # Do not hard-reject large merges — refine them near the predicted center.
            if curr_area > 0 and area < curr_area * 0.12:
                continue  # dust

            ymin2, ymax2, xmin2, xmax2 = comp["bbox"]
            ymin_int = max(ymin1, ymin2)
            ymax_int = min(ymax1, ymax2)
            xmin_int = max(xmin1, xmin2)
            xmax_int = min(xmax1, xmax2)
            overlap = 0
            if ymin_int < ymax_int and xmin_int < xmax_int:
                sub_mask1_slice = sub_mask1[ymin_int - ymin1 : ymax_int - ymin1, xmin_int - xmin1 : xmax_int - xmin1]
                sub_mask2_slice = comp["sub_mask"][ymin_int - ymin2 : ymax_int - ymin2, xmin_int - xmin2 : xmax_int - xmin2]
                overlap = int(np.sum(np.logical_and(sub_mask1_slice, sub_mask2_slice)))

            ccx, ccy = comp["centroid"]
            dist2 = (ccx - curr_cx) ** 2 + (ccy - curr_cy) ** 2
            if overlap == 0 and dist2 > max_dist_px ** 2:
                continue
            ranked.append((-float(overlap), float(dist2), comp))

        candidate: dict[str, Any] | None = None
        if ranked:
            ranked.sort(key=lambda t: (t[0], t[1]))
            candidate = ranked[0][2]
        else:
            soft = pick_component(
                frame_comps,
                seed_x=curr_cx,
                seed_y=curr_cy,
                seed_radius=select_r,
                ref_area=curr_area,
            )
            if soft is None:
                return None
            scx, scy = soft["centroid"]
            if (scx - curr_cx) ** 2 + (scy - curr_cy) ** 2 > max_dist_px ** 2:
                return None
            candidate = soft

        # Always refine near predicted float position (handles 2–3 lobe merges).
        refined = refine_component_near_point(
            candidate,
            seed_x=curr_cx,
            seed_y=curr_cy,
            max_radius=float(search_r),
            ref_area=curr_area,
        )
        rcx, rcy = refined["centroid"]
        if (rcx - curr_cx) ** 2 + (rcy - curr_cy) ** 2 > max_dist_px ** 2:
            # Refined lobe drifted too far — lost track
            return None
        return refined

    # Track forward
    curr_comp = seed_comp
    for idx in range(local_seed_idx + 1, n):
        chosen_comp = _step_track(curr_comp, idx)
        if chosen_comp is None:
            break
        curr_cx, curr_cy = chosen_comp["centroid"]
        seeds[idx] = (int(round(curr_cx)), int(round(curr_cy)))
        tracked_components[idx] = chosen_comp
        curr_comp = chosen_comp

    # Track backward
    curr_comp = seed_comp
    for idx in range(local_seed_idx - 1, -1, -1):
        chosen_comp = _step_track(curr_comp, idx)
        if chosen_comp is None:
            break
        curr_cx, curr_cy = chosen_comp["centroid"]
        seeds[idx] = (int(round(curr_cx)), int(round(curr_cy)))
        tracked_components[idx] = chosen_comp
        curr_comp = chosen_comp

    return ObjectTrackingResult(seeds=seeds, tracked_components=tracked_components)


def resolve_seed_xy_for_preview_frame(
    stack: np.ndarray,
    *,
    frame_index: int,
    object_seed: ObjectSeed,
    threshold: float,
    voxel_size: VoxelSize | None = None,
) -> tuple[tuple[int, int] | None, float | None]:
    """Track seed from ``object_seed.frame_index`` to ``frame_index`` on a (z,y,x) stack.

    Coordinates are in the same frame as ``stack`` (already ROI-cropped if any).
    Returns ``(seed_xy, ref_area)``; seed_xy is None if tracking is lost.
    """
    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("resolve_seed_xy_for_preview_frame expects (z, y, x)")
    n = arr.shape[0]
    if frame_index < 0 or frame_index >= n:
        return None, None

    thresholds = tuple(float(threshold) for _ in range(n))
    # object_seed.frame_index is local to this stack when caller remapped it.
    result = _track_object(arr, thresholds, object_seed, frame_offset=0, voxel_size=voxel_size)
    seed_xy = result.seeds[frame_index]
    ref_area = None
    if result.tracked_components[frame_index] is not None:
        ref_area = float(result.tracked_components[frame_index]["area"])
    elif result.tracked_components[object_seed.frame_index] is not None:
        ref_area = float(result.tracked_components[object_seed.frame_index]["area"])
    return seed_xy, ref_area


def normalize_thresholds(thresholds: float | Sequence[float], *, frame_count: int) -> tuple[float, ...]:
    if np.isscalar(thresholds):
        return tuple(float(thresholds) for _ in range(frame_count))

    values = tuple(float(value) for value in thresholds)
    if len(values) != frame_count:
        raise ValueError("threshold sequence length must match number of frames")
    return values

