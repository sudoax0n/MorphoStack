"""FastAPI application for the local MorphoStack backend."""

from __future__ import annotations

import shutil
import tempfile
from base64 import b64encode
from contextlib import asynccontextmanager
from pathlib import Path
from collections import OrderedDict
from threading import Lock
from typing import Annotated, AsyncIterator, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from morphostack import __version__
from morphostack.core import (
    DEFAULT_PROFILE,
    ObjectSeed,
    SeedPoint,
    PROFILE_CHOICES,
    RectROI,
    SWEEP_COLUMNS,
    VoxelSize,
    StackAnalysis,
    ZRange,
    analyze_stack,
    analysis_manifest,
    analysis_run_warnings,
    analysis_summary,
    analysis_summary_row,
    best_sweep_result,
    cached_load_image_stack,
    compare_metric_csv,
    default_session_store,
    failed_analysis_summary_row,
    file_sha256,
    inspect_image_stack,
    load_image_stack,
    suggest_threshold,
    threshold_sweep,
    threshold_sweep_rows,
    threshold_values,
)
from morphostack.core.models import (
    DisplayMesh,
    DisplayVolumeSpec,
    ImageStack,
    ResultAuthorityError,
    SegmentationCandidate,
    reject_non_scientific_input,
    result_role_of,
)
from morphostack.core.stack_cache import SessionStackEntry
from morphostack.core.export import BATCH_SUMMARY_COLUMNS, analysis_rows, slice_volume_payload
from morphostack.core.mesh import MeshGeometry, contour_stack_mesh_geometry, write_mask_stack_tiff, write_mesh_file
from morphostack.core.pipeline import (
    StackViewTransform,
    mesh_contours_from_analysis,
    object_seed_payload,
    tracking_diagnostics_payload,
)
from morphostack.core.preview import (
    PreviewImage,
    extract_preview_frame,
    extract_preview_frame_from_volume,
    render_segmentation_preview_png,
    with_global_frame_index,
)
from morphostack.core.segmentation import apply_rect_roi, apply_z_range


_PREVIEW_IMAGE_MAX_ENTRIES = 32
_PREVIEW_IMAGE_MAX_BYTES = 128 * 1024 * 1024
_preview_image_lock = Lock()
_preview_images: OrderedDict[str, bytes] = OrderedDict()
_preview_image_total_bytes = 0

# Display-plane VolumeSource for provisional path-based previews (packet 10).
# Exact analysis / full resolve_stack path remains the science reference.
_VOLUME_SOURCE_PREVIEW_ENV = "MORPHOSTACK_VOLUME_SOURCE_PREVIEW"


def volume_source_preview_enabled() -> bool:
    import os

    raw = os.environ.get(_VOLUME_SOURCE_PREVIEW_ENV, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _store_preview_image(png_bytes: bytes) -> str:
    global _preview_image_total_bytes
    image = bytes(png_bytes)
    if len(image) > _PREVIEW_IMAGE_MAX_BYTES:
        raise ValueError("Preview image exceeds cache limit")
    image_id = str(uuid4())
    with _preview_image_lock:
        _preview_images[image_id] = image
        _preview_image_total_bytes += len(image)
        while len(_preview_images) > _PREVIEW_IMAGE_MAX_ENTRIES or _preview_image_total_bytes > _PREVIEW_IMAGE_MAX_BYTES:
            _, evicted = _preview_images.popitem(last=False)
            _preview_image_total_bytes -= len(evicted)
    return image_id


def _get_preview_image(image_id: str) -> bytes:
    with _preview_image_lock:
        image = _preview_images.get(image_id)
        if image is None:
            raise KeyError(image_id)
        _preview_images.move_to_end(image_id)
        return image


class VoxelOverride(BaseModel):
    x_um: float = Field(gt=0)
    y_um: float = Field(gt=0)
    z_um: float = Field(gt=0)


class ROIRequest(BaseModel):
    xmin: int
    xmax: int
    ymin: int
    ymax: int


class ZRangeRequest(BaseModel):
    zmin: int
    zmax: int


class SeedPointRequest(BaseModel):
    x: float
    y: float


class ObjectSeedRequest(BaseModel):
    x: float = 0.0
    y: float = 0.0
    frame_index: int
    radius: float = 10.0
    max_tracking_dist_um: float | None = None
    type: str = "circle"
    points: list[SeedPointRequest] | None = None
    # Packet 13: optional display→source provenance (tracking key ignores these).
    source_revision: str | None = None
    seed_origin: str | None = None  # ui_2d | viewer_3d
    radius_unit: str | None = None  # must be "px" when set (ObjectSeed contract)


class InspectRequest(BaseModel):
    path: str
    voxel: VoxelOverride | None = None


class DisplayPyramidBuildRequest(BaseModel):
    """Start or attach a derived display-pyramid build (display only)."""

    path: str | None = None
    stack_id: str | None = None
    voxel: VoxelOverride | None = None
    max_levels: int = Field(default=4, ge=1, le=8)
    max_level_bytes: int = Field(default=8 * 1024 * 1024, ge=1024)
    max_source_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    background: bool = True


class DisplayPyramidStatusRequest(BaseModel):
    cache_key: str | None = None
    path: str | None = None
    stack_id: str | None = None
    voxel: VoxelOverride | None = None


class DisplayPyramidLevelRequest(BaseModel):
    cache_key: str
    level: int | None = None
    max_bytes: int | None = Field(default=None, ge=1024)
    include_binary: bool = True


class AnalyzeRequest(BaseModel):
    path: str | None = None
    stack_id: str | None = None
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    include_mesh: bool = False
    prefer_opencv: bool = True
    object_seed: ObjectSeedRequest | None = None
    excluded_frames: list[int] = Field(default_factory=list)
    enable_skeleton: bool = False
    skeleton_prune_pix: float = Field(default=1.0, ge=0)


class MeshPreviewRequest(BaseModel):
    path: str | None = None
    stack_id: str | None = None
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    prefer_opencv: bool = True
    downsample: int = Field(default=1, ge=1, le=8)
    max_faces: int = Field(default=12000, ge=1000, le=50000)
    object_seed: ObjectSeedRequest | None = None
    excluded_frames: list[int] = Field(default_factory=list)


class MeshExportRequest(BaseModel):
    path: str | None = None
    stack_id: str | None = None
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    prefer_opencv: bool = True
    downsample: int = Field(default=1, ge=1, le=8)
    max_faces: int = Field(default=50000, ge=1000, le=100000)
    object_seed: ObjectSeedRequest | None = None
    excluded_frames: list[int] = Field(default_factory=list)
    destination: str


class MaskExportRequest(BaseModel):
    path: str | None = None
    stack_id: str | None = None
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    prefer_opencv: bool = True
    object_seed: ObjectSeedRequest | None = None
    excluded_frames: list[int] = Field(default_factory=list)
    destination: str


class PreviewRequest(BaseModel):
    path: str | None = None
    stack_id: str | None = None
    threshold: float
    frame_index: int = Field(default=0, ge=0)
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    prefer_opencv: bool = True
    object_seed: ObjectSeedRequest | None = None
    enable_skeleton: bool = False
    skeleton_prune_pix: float = Field(default=1.0, ge=0)
    # When false: grayscale only (no contour/tint/seed drawn on PNG) so user can QC membrane.
    show_selection: bool = True
    image_transport: Literal["inline", "url"] = "inline"
    fast_preview: bool = False
    # Diagnostic rollback: run synchronous seed-to-target walk (pre-packet-04 policy).
    # Default False: exact path reads cache / single-flight job only (no sync walk).
    force_sync_exact: bool = False


class ThresholdRequest(BaseModel):
    path: str | None = None
    stack_id: str | None = None
    method: str = "auto"
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    # Threshold contract (Milestone A): scope/sample metadata only; numeric algorithm frozen.
    suggestion_scope: str = "stack_sample"
    max_samples: int | None = None
    sample_seed: int | None = None
    frame: int | None = Field(default=None, ge=0)


class SweepRequest(BaseModel):
    path: str | None = None
    stack_id: str | None = None
    start: float
    stop: float
    step: float = Field(gt=0)
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    include_mesh: bool = False
    prefer_opencv: bool = True


class TrackingJobStartRequest(BaseModel):
    """Start or attach a process-local single-flight exact tracking job.

    Exact /preview remains the synchronous diagnostic path until packet 04.
    Do not run both writers for one tracking key concurrently.
    """

    path: str | None = None
    stack_id: str | None = None
    object_seed: ObjectSeedRequest
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    target_z: int | None = None
    direction_priority: int | None = None  # +1 / -1 for full bidirectional only


class TrackingJobReprioritizeRequest(BaseModel):
    target_z: int | None = None
    direction_priority: int | None = None


def create_app(*, static_dir: Path | None = None) -> FastAPI:
    from morphostack.api.tracking_jobs import (
        TrackingJobService,
        set_tracking_job_service,
        shutdown_tracking_job_service,
    )
    from morphostack.core.stack_cache import default_tracking_cache

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Process-local single-flight tracking service (packet 03).
        # Not shared across multi-worker processes — document, do not pretend.
        from morphostack.core.display_pyramid import (
            default_display_pyramid_store,
            shutdown_default_display_pyramid_store,
        )

        service = TrackingJobService(result_cache=default_tracking_cache)
        app.state.tracking_jobs = service
        set_tracking_job_service(service)
        # Display pyramid store: ensure singleton exists; shutdown cancels builds.
        app.state.display_pyramid = default_display_pyramid_store()
        try:
            yield
        finally:
            service.shutdown(timeout=30.0)
            shutdown_tracking_job_service(timeout=0.0)
            app.state.tracking_jobs = None
            try:
                shutdown_default_display_pyramid_store(timeout=30.0)
            except Exception:
                pass
            app.state.display_pyramid = None

    app = FastAPI(title="MorphoStack API", version=__version__, lifespan=lifespan)

    # Local tool: allow browser UI on another port (e.g. Vite :5173) without proxy misconfig.
    try:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception:
        pass

    def _tracking_service() -> TrackingJobService:
        # Prefer app lifespan instance; fall back to process default so TestClient
        # without context manager and multi-worker docs stay process-local honest.
        svc = getattr(app.state, "tracking_jobs", None)
        if svc is not None:
            return svc
        from morphostack.api.tracking_jobs import get_tracking_job_service

        return get_tracking_job_service()

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "version": __version__,
            "profiles": list(PROFILE_CHOICES),
            "tracking_jobs_process_local": True,
        }

    @app.post("/display-pyramid/build")
    def display_pyramid_build(request: DisplayPyramidBuildRequest) -> dict[str, object]:
        """Build or resume a revisioned display pyramid (does not block 2D preview)."""

        from morphostack.core.display_pyramid import (
            PyramidConfig,
            default_display_pyramid_store,
            storage_decision_record,
        )
        from morphostack.core.volume_source import (
            open_volume_source,
            stack_revision_from_session,
            volume_source_from_array,
        )

        try:
            cfg = PyramidConfig(
                max_levels=int(request.max_levels),
                max_level_bytes=int(request.max_level_bytes),
                max_source_bytes=int(request.max_source_bytes),
            )
            store = default_display_pyramid_store()
            sid = (request.stack_id or "").strip() or None
            disk = (request.path or "").strip() or None
            if sid is not None:
                stack, _ = resolve_stack(
                    path=None, stack_id=sid, voxel=request.voxel, compute_sha=False
                )
                source = volume_source_from_array(
                    stack.grayscale,
                    voxel_size=stack.voxel_size,
                    voxel_source=stack.voxel_source,
                    source_path=str(stack.source_path),
                    revision=stack_revision_from_session(sid),
                    use_cache=False,
                )
            elif disk is not None:
                source = open_volume_source(
                    disk, voxel_override=to_voxel_size(request.voxel), register=True
                )
            else:
                raise ValueError("Either path or stack_id is required")
            key = store.start_build_from_volume_source(
                source, config=cfg, background=bool(request.background)
            )
            status = store.read_status(key)
            payload = status.to_dict() if status is not None else {"cache_key": key, "state": "queued"}
            payload["storage_decision"] = storage_decision_record()
            payload["display_only"] = True
            payload["active_builds"] = store.active_build_count()
            payload["retention"] = store.retention.to_dict()
            return payload
        except Exception as exc:
            from morphostack.core.display_pyramid import ActiveBuildLimitError

            if isinstance(exc, ActiveBuildLimitError):
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/display-pyramid/status")
    def display_pyramid_status(request: DisplayPyramidStatusRequest) -> dict[str, object]:
        from morphostack.core.display_pyramid import (
            PyramidConfig,
            default_display_pyramid_store,
            pyramid_cache_key,
            storage_decision_record,
        )
        from morphostack.core.volume_source import open_volume_source, stack_revision_from_session

        try:
            store = default_display_pyramid_store()
            key = (request.cache_key or "").strip() or None
            if key is None:
                sid = (request.stack_id or "").strip() or None
                disk = (request.path or "").strip() or None
                cfg = PyramidConfig()
                if sid is not None:
                    stack, _ = resolve_stack(
                        path=None, stack_id=sid, voxel=request.voxel, compute_sha=False
                    )
                    rev = stack_revision_from_session(sid)
                    key = pyramid_cache_key(
                        rev,
                        source_axes="ZYX",
                        source_dtype=str(stack.grayscale.dtype),
                        voxel_size=stack.voxel_size,
                        voxel_source=stack.voxel_source,
                        config=cfg,
                    )
                elif disk is not None:
                    src = open_volume_source(
                        disk, voxel_override=to_voxel_size(request.voxel), register=True
                    )
                    meta = src.metadata()
                    key = pyramid_cache_key(
                        src.revision,
                        source_axes=meta.axes,
                        source_dtype=str(meta.dtype),
                        voxel_size=meta.voxel_size,
                        voxel_source=meta.voxel_source,
                        config=cfg,
                    )
                else:
                    raise ValueError("cache_key or path/stack_id required")
            status = store.read_status(key)
            if status is None:
                return {
                    "cache_key": key,
                    "state": "missing",
                    "display_only": True,
                    "storage_decision": storage_decision_record(),
                }
            payload = status.to_dict()
            payload["display_only"] = True
            payload["storage_decision"] = storage_decision_record()
            return payload
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/display-pyramid/level")
    def display_pyramid_level(request: DisplayPyramidLevelRequest) -> dict[str, object]:
        """Return level metadata (+ optional base64 binary). Display-only."""

        from base64 import b64encode

        import numpy as np

        from morphostack.core.display_pyramid import default_display_pyramid_store
        from morphostack.core.models import ResultAuthorityError, reject_non_scientific_input

        try:
            store = default_display_pyramid_store()
            desc, arr, spec = store.select_and_load_level(
                request.cache_key,
                level=request.level,
                max_bytes=request.max_bytes,
            )
            # Prove science isolation at the endpoint boundary.
            try:
                reject_non_scientific_input(spec, context="display-pyramid/level")
                raise HTTPException(
                    status_code=500,
                    detail="internal: display level failed authority reject",
                )
            except ResultAuthorityError:
                pass
            budget = int(request.max_bytes) if request.max_bytes is not None else 8 * 1024 * 1024
            payload: dict[str, object] = {
                "cache_key": request.cache_key,
                "display_only": True,
                "level": desc.to_dict(),
                "display_volume_spec": spec.to_dict(),
                "transfer_nbytes": int(arr.nbytes),
                "within_budget": bool(arr.nbytes <= budget),
            }
            if request.include_binary:
                cont = np.ascontiguousarray(arr)
                payload["dtype"] = str(cont.dtype)
                payload["shape"] = list(cont.shape)
                payload["byteorder"] = "little" if cont.dtype.byteorder != ">" else "big"
                payload["data_b64"] = b64encode(cont.tobytes()).decode("ascii")
            return payload
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/tracking/jobs/start")
    def tracking_job_start(request: TrackingJobStartRequest) -> dict[str, object]:
        """Start or attach a single-flight exact tracking job (process-local)."""
        from morphostack.core.pipeline import crop_stack_xy
        from morphostack.core.seeded_vesicle import effective_seed_radius
        from morphostack.core.stack_cache import (
            make_tracking_cache_key,
            path_source_identity,
            tracking_key_revision,
        )

        try:
            stack, _sha = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
                compute_sha=False,
            )
            roi = to_rect_roi(request.roi)
            z_range = to_z_range(request.z_range)
            seed = to_object_seed(request.object_seed)
            if seed is None:
                raise ValueError("object_seed is required")
            if request.stack_id:
                stack_identity = f"session:{(request.stack_id or '').strip()}"
            else:
                stack_identity = path_source_identity(stack.source_path)
            validate_object_seed_against_stack(
                seed,
                gray_shape=tuple(int(v) for v in stack.grayscale.shape),
                current_source_revision=stack_identity,
            )
            gray = stack.grayscale
            if z_range is not None:
                z0 = max(0, min(gray.shape[0], z_range.zmin))
                z1 = max(0, min(gray.shape[0], z_range.zmax))
                gray = gray[z0:z1]
            if roi is not None:
                gray = crop_stack_xy(gray, roi)
            transform = StackViewTransform.create(
                roi=roi, z_range=z_range, raw_shape=stack.grayscale.shape
            )
            local_seed = transform.to_local_seed_object(seed)
            seed_r = effective_seed_radius(float(local_seed.radius) if local_seed.radius else None)
            cache_key = make_tracking_cache_key(
                stack_identity=stack_identity,
                seed_x=float(local_seed.x),
                seed_y=float(local_seed.y),
                seed_frame=int(local_seed.frame_index),
                seed_radius=seed_r,
                gray_shape=tuple(int(v) for v in gray.shape),
                roi=roi,
                z_range=z_range,
                profile=request.profile,
            )
            snap = _tracking_service().start(
                key=cache_key,
                stack=gray,
                seed_x=float(local_seed.x),
                seed_y=float(local_seed.y),
                seed_frame=int(local_seed.frame_index),
                seed_radius=seed_r,
                target_z=request.target_z,
                direction_priority=request.direction_priority,
            )
            payload = snap.to_json_dict()
            payload["tracking_key_revision"] = tracking_key_revision(cache_key)
            payload["process_local"] = True
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/tracking/jobs/{job_id}")
    def tracking_job_status(job_id: str) -> dict[str, object]:
        try:
            snap = _tracking_service().status(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = snap.to_json_dict()
        payload["process_local"] = True
        return payload

    @app.post("/tracking/jobs/{job_id}/cancel")
    def tracking_job_cancel(job_id: str) -> dict[str, object]:
        try:
            snap = _tracking_service().cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = snap.to_json_dict()
        payload["process_local"] = True
        return payload

    @app.post("/tracking/jobs/{job_id}/reprioritize")
    def tracking_job_reprioritize(
        job_id: str, request: TrackingJobReprioritizeRequest
    ) -> dict[str, object]:
        try:
            snap = _tracking_service().reprioritize(
                job_id,
                target_z=request.target_z,
                direction_priority=request.direction_priority,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = snap.to_json_dict()
        payload["process_local"] = True
        return payload

    @app.post("/inspect")
    def inspect_stack(request: InspectRequest) -> dict[str, object]:
        try:
            info = inspect_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "source_path": str(info["source_path"]),
            "grayscale_shape": list(info["grayscale_shape"]),
            "color_shape": list(info["color_shape"]),
            "voxel_size": voxel_payload(info["voxel_size"]),
            "voxel_source": info["voxel_source"],
        }

    @app.post("/analyze")
    def analyze(request: AnalyzeRequest) -> dict[str, object]:
        try:
            stack, source_sha256 = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
            )
            print("=== DEBUG ANALYZE REQUEST ===")
            print(f"  Path: {request.path}")
            print(f"  Stack ID: {request.stack_id}")
            print(f"  Threshold: {request.threshold}")
            print(f"  Profile: {request.profile}")
            print(f"  ROI: {request.roi}")
            print(f"  Z Range: {request.z_range}")
            print(f"  Object Seed: {request.object_seed}")
            
            analyze_seed = to_object_seed(request.object_seed)
            validate_object_seed_against_stack(
                analyze_seed,
                gray_shape=tuple(int(v) for v in stack.grayscale.shape),
                current_source_revision=_stack_source_revision(
                    path=request.path, stack_id=request.stack_id, stack=stack
                ),
            )
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=request.threshold,
                voxel_size=stack.voxel_size,
                roi=to_rect_roi(request.roi),
                z_range=to_z_range(request.z_range),
                profile=request.profile,
                prefer_opencv=request.prefer_opencv,
                include_mesh=request.include_mesh,
                object_seed=analyze_seed,
                excluded_frames=request.excluded_frames,
                enable_skeleton=request.enable_skeleton,
                skeleton_prune_pix=request.skeleton_prune_pix,
            )
            
            print(f"=== DEBUG ANALYZE RESULT ===")
            print(f"  Total frames: {len(analysis.frames)}")
            print(f"  Valid frames count: {len(analysis.valid_frames)}")
            print(f"  Valid frames: {[f.frame_index for f in analysis.frames if f.contour is not None]}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        mesh = None
        if analysis.mesh:
            mesh = {
                "surface_area_um2": analysis.mesh.surface_area_um2,
                "volume_um3": analysis.mesh.volume_um3,
                "equivalent_sphere_diameter_um": analysis.mesh.equivalent_sphere_diameter_um,
                "sphericity": analysis.mesh.sphericity,
            }
        return {
            "source_path": str(stack.source_path),
            "profile": analysis.profile,
            "frame_count": len(analysis.frames),
            "valid_frame_count": len(analysis.valid_frames),
            "excluded_frames": sorted(analysis.excluded_frames),
            "voxel_size": voxel_payload(stack.voxel_size),
            "voxel_source": stack.voxel_source,
            "mesh": mesh,
            "slice_volume": slice_volume_payload(analysis),
            "summary": analysis_summary(analysis),
            "warnings": analysis_run_warnings(analysis, voxel_source=stack.voxel_source),
            "object_seed": object_seed_payload(analyze_seed),
            "tracking": tracking_diagnostics_payload(analysis.tracking),
            "manifest": analysis_manifest(
                analysis,
                source_path=str(stack.source_path),
                source_sha256=source_sha256,
                threshold=request.threshold,
                roi=roi_payload(to_rect_roi(request.roi)),
                z_range=z_range_payload(to_z_range(request.z_range)),
                include_mesh=request.include_mesh,
                prefer_opencv=request.prefer_opencv,
                voxel_source=stack.voxel_source,
                object_seed=analyze_seed,
            ),
            "rows": analysis_rows(analysis),
        }

    @app.post("/threshold")
    def threshold(request: ThresholdRequest) -> dict[str, object]:
        try:
            from morphostack.core.segmentation import suggest_threshold_report

            stack, _ = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
            )
            grayscale = apply_preview_filters(stack.grayscale, to_rect_roi(request.roi), to_z_range(request.z_range))
            sample_kwargs: dict[str, object] = {"method": request.method}
            if request.max_samples is not None:
                sample_kwargs["max_samples"] = int(request.max_samples)
            if request.sample_seed is not None:
                sample_kwargs["seed"] = int(request.sample_seed)
            revision, id_kind = resolve_suggestion_source_identity(
                path=request.path,
                stack_id=request.stack_id,
                resolved_source_path=str(stack.source_path),
                ephemeral_upload=False,
            )
            _value, _method, meta = suggest_threshold_report(
                grayscale,
                suggestion_scope=request.suggestion_scope or "stack_sample",
                source_path=str(stack.source_path),
                source_revision=revision,
                source_identity_kind=id_kind,
                z_range=z_range_payload(to_z_range(request.z_range)),
                roi=roi_payload(to_rect_roi(request.roi)),
                frame=request.frame,
                **sample_kwargs,  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return threshold_payload_from_report(meta)

    @app.get("/preview-image/{image_id}")
    @app.get("/api/preview-image/{image_id}", include_in_schema=False)
    def preview_image(image_id: str) -> Response:
        try:
            png = _get_preview_image(image_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Preview image has expired or is unavailable") from exc
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})

    @app.post("/preview")
    def preview(request: PreviewRequest) -> dict[str, object]:
        try:
            from morphostack.core.pipeline import crop_stack_xy
            from morphostack.core.seeded_vesicle import track_seeded_vesicle_stack
            from morphostack.core.preview import overlay_preview, PreviewImage
            from morphostack.core.contours import SegmentationPreview
            from io import BytesIO

            roi = to_rect_roi(request.roi)
            z_range = to_z_range(request.z_range)
            seed = to_object_seed(request.object_seed)
            # Bounds/revision check once stack is resolved below; for plane-only
            # provisional path, validate when full stack materializes / is known.

            # Provisional / unseeded path-based preview: prefer VolumeSource plane
            # reads (TIFF native) without full-stack materialization. Exact seeded
            # tracking still uses resolve_stack + science path.
            disk_path = (request.path or "").strip() or None
            sid = (request.stack_id or "").strip() or None
            provisional_like = seed is None or request.fast_preview
            if (
                provisional_like
                and volume_source_preview_enabled()
                and disk_path
                and not sid
            ):
                vs_payload = try_provisional_preview_via_volume_source(
                    path=disk_path,
                    voxel=request.voxel,
                    frame_index=request.frame_index,
                    threshold=request.threshold,
                    roi=roi,
                    z_range=z_range,
                    seed=seed,
                    prefer_opencv=request.prefer_opencv,
                    enable_skeleton=request.enable_skeleton,
                    skeleton_prune_pix=request.skeleton_prune_pix,
                    image_transport=request.image_transport,
                    fast_preview=bool(request.fast_preview),
                )
                if vs_payload is not None:
                    return vs_payload

            # Preview must not pay full-file SHA on every slider event.
            stack, _ = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
                compute_sha=False,
            )
            validate_object_seed_against_stack(
                seed,
                gray_shape=tuple(int(v) for v in stack.grayscale.shape),
                current_source_revision=_stack_source_revision(
                    path=request.path, stack_id=request.stack_id, stack=stack
                ),
            )
            preview_source_revision, _ = resolve_suggestion_source_identity(
                path=request.path,
                stack_id=request.stack_id,
                resolved_source_path=str(stack.source_path),
                ephemeral_upload=False,
            )
            # Full field (or user ROI only) — never seed-isolation zoom.
            transform = StackViewTransform.create(
                roi=roi, z_range=z_range, raw_shape=stack.grayscale.shape
            )
            local_seed = transform.to_local_seed_object(seed) if seed is not None else None
            tracked_cx: float | None = None
            tracked_cy: float | None = None
            # Provisional fast path: one-plane extract only. Never claim this is
            # the authoritative tracked contour when a seed is present.
            if seed is None or (request.fast_preview and local_seed is not None):
                frame, _ = extract_preview_frame(
                    stack.grayscale,
                    request.frame_index,
                    roi=roi,
                    z_range=z_range,
                )
                preview_image = render_segmentation_preview_png(
                    frame,
                    frame_index=0,
                    threshold=request.threshold,
                    prefer_opencv=request.prefer_opencv,
                    object_seed=local_seed,
                    enable_skeleton=request.enable_skeleton,
                    skeleton_prune_pix=request.skeleton_prune_pix,
                    voxel_x_um=stack.voxel_size.x_um,
                )
                preview_image = with_global_frame_index(preview_image, request.frame_index)
                quality = (
                    "provisional"
                    if (request.fast_preview and local_seed is not None)
                    else "exact"
                )
                return preview_payload(
                    str(stack.source_path),
                    preview_image,
                    image_transport=request.image_transport,
                    preview_quality=quality,
                    cache_hit=False,
                    source_revision=preview_source_revision,
                    requested_threshold=float(request.threshold),
                    effective_threshold=float(request.threshold),
                    threshold_semantics=(
                        "provisional_global"
                        if quality == "provisional"
                        else "global_intensity"
                    ),
                    seeded=False,
                    result_ok=True,
                    tracked_center_x=None,
                    tracked_center_y=None,
                )

            gray = stack.grayscale
            if z_range is not None:
                z0 = max(0, min(gray.shape[0], z_range.zmin))
                z1 = max(0, min(gray.shape[0], z_range.zmax))
                gray = gray[z0:z1]
            if roi is not None:
                gray = crop_stack_xy(gray, roi)

            transform = StackViewTransform.create(
                roi=roi, z_range=z_range, raw_shape=stack.grayscale.shape
            )
            local_frame = request.frame_index - transform.z_offset
            if local_frame < 0 or local_frame >= gray.shape[0]:
                raise ValueError(
                    f"frame_index {request.frame_index} is outside the selected Z range / stack"
                )

            frame = gray[local_frame]
            local_seed = transform.to_local_seed_object(seed) if seed is not None else None
            preview_quality: Literal["provisional", "exact"] = "exact"
            track_cache_hit = False
            thr_meta: dict[str, object] = {
                "requested_threshold": float(request.threshold),
                "effective_threshold": float(request.threshold),
                "threshold_semantics": "global_intensity",
                "threshold": float(request.threshold),
            }

            # Exact-tracking identity fields (populated on seeded exact path).
            tracking_profile: str | None = None
            tracking_mode: str | None = None
            tracking_algorithm_version: str | None = None
            tracking_key_rev: str | None = None

            # Job lifecycle fields for exact subscription path (packet 04).
            tracking_job_payload: dict[str, object] | None = None
            exact_available = True
            exact_pending = False

            if local_seed is not None:
                # Exact seeded path: cache/job subscription (packet 04). Shared with /upload/preview.
                from morphostack.core.seeded_vesicle import SeededSliceResult
                from morphostack.core.stack_cache import (
                    default_tracking_cache,
                    path_source_identity,
                )

                if request.stack_id:
                    stack_identity = f"session:{(request.stack_id or '').strip()}"
                else:
                    # Path + mtime/size revision (cheap). Full SHA is for manifests only.
                    stack_identity = path_source_identity(stack.source_path)

                job_svc = None if request.force_sync_exact else _tracking_service()
                (
                    sres,
                    track_cache_hit,
                    tracking_job_payload,
                    exact_available,
                    exact_pending,
                    tracking_profile,
                    tracking_mode,
                    tracking_algorithm_version,
                    tracking_key_rev,
                ) = obtain_exact_seeded_slice(
                    gray=gray,
                    local_seed=local_seed,
                    local_frame=int(local_frame),
                    stack_identity=stack_identity,
                    profile=request.profile,
                    roi=roi,
                    z_range=z_range,
                    force_sync_exact=bool(request.force_sync_exact),
                    tracking_service=job_svc,
                    tracking_cache=default_tracking_cache,
                )
                if not exact_available:
                    preview_quality = "provisional"

                from morphostack.core.pipeline import threshold_provenance

                if sres is None:
                    # Waiting for background job: current-plane image only (not exact).
                    thr_meta = {
                        "requested_threshold": float(request.threshold),
                        "effective_threshold": float(request.threshold),
                        "threshold_semantics": "provisional_global",
                        "threshold": float(request.threshold),
                    }
                    empty = SegmentationPreview(
                        threshold=float(request.threshold),
                        contour=None,
                        area_px2=0.0,
                        perimeter_px=0.0,
                        circularity=0.0,
                        method="exact_pending",
                    )
                    tracked_cx, tracked_cy = None, None
                    image = overlay_preview(
                        frame,
                        threshold=float(request.threshold),
                        preview=empty,
                        object_seed=None,
                        highlight_mask=__import__("numpy").zeros(frame.shape, dtype=bool),
                    )
                    buf = BytesIO()
                    image.save(buf, format="PNG", compress_level=0, optimize=False)
                    preview_image = PreviewImage(
                        frame_index=request.frame_index,
                        width=int(frame.shape[1]),
                        height=int(frame.shape[0]),
                        preview=empty,
                        png_bytes=buf.getvalue(),
                    )
                    # Skip the contour paint branch below.
                    sres = SeededSliceResult(
                        None, None, (float(local_seed.x), float(local_seed.y)),
                        0.0, 0.0, "exact_pending", False,
                    )

                thr_meta = threshold_provenance(
                    requested=float(request.threshold),
                    method=str(sres.method or ""),
                    effective=getattr(sres, "effective_threshold", None),
                    ok=bool(sres.ok and sres.contour_xy is not None),
                    seeded=True,
                )
                if sres.method == "exact_pending":
                    thr_meta = {
                        "requested_threshold": float(request.threshold),
                        "effective_threshold": float(request.threshold),
                        "threshold_semantics": "provisional_global",
                        "threshold": float(request.threshold),
                    }
                draw_thr = (
                    float(thr_meta["effective_threshold"])
                    if thr_meta.get("effective_threshold") is not None
                    else float(request.threshold)
                )
                if (
                    sres.method != "exact_pending"
                    and sres.ok
                    and sres.contour_xy is not None
                    and sres.solid_mask is not None
                ):
                    import numpy as np
                    from morphostack.core.contours import contour_circularity

                    circ = contour_circularity(sres.contour_xy)
                    seg = SegmentationPreview(
                        threshold=draw_thr,
                        contour=sres.contour_xy,
                        area_px2=float(sres.area_px),
                        perimeter_px=float(sres.perimeter_px),
                        circularity=circ,
                        method=sres.method,
                    )
                    skel_mask = None
                    skel_px = skel_um = None
                    skel_ok = False
                    if request.enable_skeleton:
                        try:
                            from morphostack.core.skeleton import measure_skeleton

                            skel_mask, sm = measure_skeleton(
                                sres.solid_mask,
                                object_seed=(int(round(sres.center_xy[0])), int(round(sres.center_xy[1]))),
                                prune_threshold_pix=request.skeleton_prune_pix,
                                voxel_x_um=stack.voxel_size.x_um,
                            )
                            if sm.ok:
                                skel_px, skel_um, skel_ok = sm.perimeter_px, sm.perimeter_um, True
                            else:
                                skel_mask = None
                        except Exception:
                            skel_mask = None
                    tracked_cx: float | None = float(sres.center_xy[0])
                    tracked_cy: float | None = float(sres.center_xy[1])
                    if request.show_selection:
                        # Green exterior contour only; HTML draws seed ROI + tracked center.
                        # No yellow PNG seed (would be confused with immutable user seed).
                        image = overlay_preview(
                            frame,
                            threshold=draw_thr,
                            preview=seg,
                            object_seed=None,
                            skeleton_mask=skel_mask,
                            highlight_mask=sres.solid_mask,
                        )
                    else:
                        # Raw grayscale so user can compare membrane vs selection.
                        empty_prev = SegmentationPreview(
                            threshold=draw_thr,
                            contour=None,
                            area_px2=float(sres.area_px),
                            perimeter_px=float(sres.perimeter_px),
                            circularity=circ,
                            method=sres.method + "_hidden",
                        )
                        image = overlay_preview(
                            frame,
                            threshold=draw_thr,
                            preview=empty_prev,
                            object_seed=None,
                            skeleton_mask=None,
                            highlight_mask=np.zeros(frame.shape, dtype=bool),
                        )
                        seg = empty_prev
                        tracked_cx, tracked_cy = None, None
                    buf = BytesIO()
                    image.save(buf, format="PNG", compress_level=0, optimize=False)
                    preview_image = PreviewImage(
                        frame_index=request.frame_index,
                        width=int(frame.shape[1]),
                        height=int(frame.shape[0]),
                        preview=seg,
                        png_bytes=buf.getvalue(),
                        skel_perimeter_px=skel_px if request.show_selection else None,
                        skel_perimeter_um=skel_um if request.show_selection else None,
                        skel_ok=skel_ok if request.show_selection else False,
                    )
                elif sres.method != "exact_pending":
                    # Track lost: full field, no false multi-lobe contour / no full-threshold paint
                    import numpy as np

                    empty = SegmentationPreview(
                        threshold=float(request.threshold),
                        contour=None,
                        area_px2=0.0,
                        perimeter_px=0.0,
                        circularity=0.0,
                        method=sres.method if sres else "circle_seed_lost",
                    )
                    # Do not report original seed as tracked_center (null).
                    tracked_cx, tracked_cy = None, None
                    image = overlay_preview(
                        frame,
                        threshold=float(request.threshold),
                        preview=empty,
                        object_seed=None,
                        highlight_mask=np.zeros(frame.shape, dtype=bool),
                    )
                    buf = BytesIO()
                    image.save(buf, format="PNG", compress_level=0, optimize=False)
                    preview_image = PreviewImage(
                        frame_index=request.frame_index,
                        width=int(frame.shape[1]),
                        height=int(frame.shape[0]),
                        preview=empty,
                        png_bytes=buf.getvalue(),
                    )
                # else: exact_pending already built provisional plane + job payload above
            else:
                tracked_cx, tracked_cy = None, None
                preview_image = render_segmentation_preview_png(
                    frame,
                    frame_index=0,
                    threshold=request.threshold,
                    prefer_opencv=request.prefer_opencv,
                    object_seed=None,
                    enable_skeleton=request.enable_skeleton,
                    skeleton_prune_pix=request.skeleton_prune_pix,
                    voxel_x_um=stack.voxel_size.x_um,
                )
                preview_image = with_global_frame_index(preview_image, request.frame_index)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payload = preview_payload(
            str(stack.source_path),
            preview_image,
            image_transport=request.image_transport,
            preview_quality=preview_quality,
            cache_hit=track_cache_hit,
            source_revision=preview_source_revision,
            requested_threshold=float(thr_meta["requested_threshold"]),  # type: ignore[arg-type]
            effective_threshold=thr_meta.get("effective_threshold"),  # type: ignore[arg-type]
            threshold_semantics=str(thr_meta["threshold_semantics"]),
            seeded=local_seed is not None,
            result_ok=bool(
                preview_image.preview.contour is not None
                or (
                    thr_meta.get("threshold_semantics") == "seeded_adaptive_local"
                    and thr_meta.get("effective_threshold") is not None
                )
            ),
            tracked_center_x=tracked_cx,
            tracked_center_y=tracked_cy,
            tracking_profile=tracking_profile,
            tracking_mode=tracking_mode,
            algorithm_version=tracking_algorithm_version,
            tracking_key_revision=tracking_key_rev,
        )
        # Packet 04 subscription fields (exact path without sync walk).
        payload["exact_available"] = bool(exact_available) if local_seed is not None else True
        payload["exact_pending"] = bool(exact_pending)
        payload["tracking_job"] = tracking_job_payload
        return payload

    @app.post("/mesh-preview")
    def mesh_preview(request: MeshPreviewRequest) -> dict[str, object]:
        try:
            stack, _ = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
            )
            roi = to_rect_roi(request.roi)
            z_range = to_z_range(request.z_range)
            seed = to_object_seed(request.object_seed)
            validate_object_seed_against_stack(
                seed,
                gray_shape=tuple(int(v) for v in stack.grayscale.shape),
                current_source_revision=_stack_source_revision(
                    path=request.path, stack_id=request.stack_id, stack=stack
                ),
            )
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=request.threshold,
                voxel_size=stack.voxel_size,
                roi=roi,
                z_range=z_range,
                profile=request.profile,
                prefer_opencv=request.prefer_opencv,
                include_mesh=False,
                object_seed=seed,
                excluded_frames=request.excluded_frames,
                active_surfaces_fast=True,
            )
            filtered = apply_preview_filters(stack.grayscale, roi, z_range)
            geometry = contour_stack_mesh_geometry(
                mesh_contours_from_analysis(analysis),
                shape=filtered.shape,
                voxel=stack.voxel_size,
                downsample=request.downsample,
                max_faces=request.max_faces,
            )
            if geometry is None:
                raise ValueError(
                    "No contour for seeded object; check seed/threshold/ROI"
                    if seed is not None
                    else "Mesh preview produced no geometry. Check threshold, seed, and ROI."
                )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return mesh_preview_payload(str(stack.source_path), geometry, downsample=request.downsample)

    @app.post("/mesh-export")
    def mesh_export(request: MeshExportRequest) -> dict[str, object]:
        try:
            stack, _ = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
            )
            roi = to_rect_roi(request.roi)
            z_range = to_z_range(request.z_range)
            seed = to_object_seed(request.object_seed)
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=request.threshold,
                voxel_size=stack.voxel_size,
                roi=roi,
                z_range=z_range,
                profile=request.profile,
                prefer_opencv=request.prefer_opencv,
                include_mesh=False,
                object_seed=seed,
                excluded_frames=request.excluded_frames,
                active_surfaces_fast=True,
            )
            filtered = apply_preview_filters(stack.grayscale, roi, z_range)
            # Full export defaults to complete scientific geometry (no face-stride,
            # no display weld). request.max_faces is ignored for completeness.
            geometry = contour_stack_mesh_geometry(
                mesh_contours_from_analysis(analysis),
                shape=filtered.shape,
                voxel=stack.voxel_size,
                downsample=request.downsample,
                max_faces=None,
            )
            if geometry is None:
                raise ValueError(
                    "No contour for seeded object; check seed/threshold/ROI"
                    if seed is not None
                    else "Mesh export produced no geometry. Check threshold, seed, and ROI."
                )
            export_format = write_mesh_file(geometry, request.destination)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "source_path": str(stack.source_path),
            "destination": request.destination,
            "format": export_format,
            "vertex_count": int(len(geometry.vertices_xyz)),
            "face_count": int(len(geometry.faces)),
            "voxel_source": stack.voxel_source,
            "export_role": "complete_scientific",
            "display_only": False,
            "object_seed": object_seed_payload(to_object_seed(request.object_seed)),
            "tracking": tracking_diagnostics_payload(analysis.tracking),
        }

    @app.post("/mask-export")
    def mask_export(request: MaskExportRequest) -> dict[str, object]:
        try:
            stack, _ = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
            )
            roi = to_rect_roi(request.roi)
            z_range = to_z_range(request.z_range)
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=request.threshold,
                voxel_size=stack.voxel_size,
                roi=roi,
                z_range=z_range,
                profile=request.profile,
                prefer_opencv=request.prefer_opencv,
                include_mesh=False,
                object_seed=to_object_seed(request.object_seed),
                excluded_frames=request.excluded_frames,
            )
            filtered = apply_preview_filters(stack.grayscale, roi, z_range)
            write_mask_stack_tiff(
                mesh_contours_from_analysis(analysis),
                shape=filtered.shape,
                destination=request.destination,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "source_path": str(stack.source_path),
            "destination": request.destination,
            "format": "tiff",
            "frame_count": len(analysis.frames),
            "voxel_source": stack.voxel_source,
            "excluded_frames": sorted(analysis.excluded_frames),
        }

    @app.post("/sweep")
    def sweep(request: SweepRequest) -> dict[str, object]:
        try:
            stack, _ = resolve_stack(
                path=request.path,
                stack_id=request.stack_id,
                voxel=request.voxel,
            )
            thresholds = threshold_values(request.start, request.stop, request.step)
            results = threshold_sweep(
                stack.grayscale,
                thresholds=thresholds,
                voxel_size=stack.voxel_size,
                roi=to_rect_roi(request.roi),
                z_range=to_z_range(request.z_range),
                profile=request.profile,
                prefer_opencv=request.prefer_opencv,
                include_mesh=request.include_mesh,
                voxel_source=stack.voxel_source,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return sweep_payload(
            source_path=str(stack.source_path),
            profile=request.profile,
            voxel_source=stack.voxel_source,
            results=results,
        )

    @app.post("/upload/session")
    def upload_session_open(
        file: Annotated[UploadFile, File()],
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
    ) -> dict[str, object]:
        """Upload once, decode into process memory, return ``stack_id`` for later JSON calls.

        Prefer Stack path + path-based APIs for huge files when the server can read the disk.
        """
        temp_path: Path | None = None
        try:
            temp_path = save_upload_to_temp(file)
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            source_sha256 = file_sha256(temp_path)
            stack = load_image_stack(temp_path, voxel_override=voxel_override)
            source_name = file.filename or str(temp_path.name)
            stack_id = default_session_store.put(
                stack,
                source_name=source_name,
                source_sha256=source_sha256,
            )
            entry = default_session_store.get(stack_id)
            return {
                "stack_id": stack_id,
                "source_path": entry.source_name,
                "grayscale_shape": list(entry.stack.grayscale.shape),
                "color_shape": list(entry.stack.color.shape),
                "voxel_size": voxel_payload(entry.stack.voxel_size),
                "voxel_source": entry.stack.voxel_source,
            }
        except HTTPException:
            raise
        except MemoryError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Upload session failed: out of memory while receiving or decoding the file. "
                    "For large stacks, put the full path in Stack path (no upload) instead of Choose File."
                ),
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Upload session failed (I/O): {exc}. "
                    "For large stacks, use a local path with /inspect instead of uploading."
                ),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Upload session failed: {exc}. "
                    "For large stacks, use a local path with /inspect instead of uploading."
                ),
            ) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @app.post("/upload/inspect")
    def upload_inspect_stack(
        file: Annotated[UploadFile, File()],
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
    ) -> dict[str, object]:
        """Inspect an uploaded stack. Prefer POST /inspect with a local path for large files.

        Also opens an upload session (``stack_id``) so later preview/mesh/analyze can skip re-upload.
        """
        temp_path: Path | None = None
        try:
            temp_path = save_upload_to_temp(file)
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            source_sha256 = file_sha256(temp_path)
            # Full load once: metadata inspect + session cache for subsequent ops.
            stack = load_image_stack(temp_path, voxel_override=voxel_override)
            source_name = file.filename or str(temp_path.name)
            stack_id = default_session_store.put(
                stack,
                source_name=source_name,
                source_sha256=source_sha256,
            )
            entry = default_session_store.get(stack_id)
            return {
                "stack_id": stack_id,
                "source_path": entry.source_name,
                "grayscale_shape": list(entry.stack.grayscale.shape),
                "color_shape": list(entry.stack.color.shape),
                "voxel_size": voxel_payload(entry.stack.voxel_size),
                "voxel_source": entry.stack.voxel_source,
            }
        except HTTPException:
            raise
        except MemoryError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Upload inspect failed: out of memory while receiving or reading the file. "
                    "For large stacks, put the full path in Stack path and use /inspect "
                    "(no upload) instead of Choose File."
                ),
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Upload inspect failed (I/O): {exc}. "
                    "For large stacks, use a local path with /inspect instead of uploading."
                ),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Upload inspect failed: {exc}. "
                    "For large stacks, use a local path with /inspect instead of uploading."
                ),
            ) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @app.post("/upload/analyze")
    def upload_analyze(
        file: Annotated[UploadFile, File()],
        threshold: Annotated[float, Form()],
        profile: Annotated[str, Form()] = DEFAULT_PROFILE,
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
        include_mesh: Annotated[bool, Form()] = False,
        prefer_opencv: Annotated[bool, Form()] = True,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
        z_min: Annotated[int | None, Form()] = None,
        z_max: Annotated[int | None, Form()] = None,
        object_seed_x: Annotated[float | None, Form()] = None,
        object_seed_y: Annotated[float | None, Form()] = None,
        object_seed_frame: Annotated[int | None, Form()] = None,
        object_seed_radius: Annotated[float, Form()] = 10.0,
        object_seed_max_dist_um: Annotated[float | None, Form()] = None,
        object_seed_type: Annotated[str, Form()] = "circle",
        object_seed_points: Annotated[str | None, Form()] = None,
        excluded_frames: Annotated[str | None, Form()] = None,
        enable_skeleton: Annotated[bool, Form()] = False,
        skeleton_prune_pix: Annotated[float, Form()] = 1.0,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            source_sha256 = file_sha256(temp_path)
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            stack = load_image_stack(
                temp_path,
                voxel_override=voxel_override,
            )
            seed = object_seed_from_optional_fields(
                object_seed_x,
                object_seed_y,
                object_seed_frame,
                radius=object_seed_radius,
                max_tracking_dist_um=object_seed_max_dist_um,
                type=object_seed_type,
                points_json=object_seed_points,
            )
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=threshold,
                voxel_size=stack.voxel_size,
                roi=roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax),
                z_range=z_range_from_optional_bounds(z_min, z_max),
                profile=profile,
                prefer_opencv=prefer_opencv,
                include_mesh=include_mesh,
                object_seed=seed,
                excluded_frames=parse_excluded_frames_text(excluded_frames),
                enable_skeleton=enable_skeleton,
                skeleton_prune_pix=skeleton_prune_pix,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        mesh = None
        if analysis.mesh:
            mesh = {
                "surface_area_um2": analysis.mesh.surface_area_um2,
                "volume_um3": analysis.mesh.volume_um3,
                "equivalent_sphere_diameter_um": analysis.mesh.equivalent_sphere_diameter_um,
                "sphericity": analysis.mesh.sphericity,
            }
        return {
            "source_path": file.filename or str(temp_path.name),
            "profile": analysis.profile,
            "frame_count": len(analysis.frames),
            "valid_frame_count": len(analysis.valid_frames),
            "excluded_frames": sorted(analysis.excluded_frames),
            "voxel_size": voxel_payload(stack.voxel_size),
            "voxel_source": stack.voxel_source,
            "mesh": mesh,
            "slice_volume": slice_volume_payload(analysis),
            "summary": analysis_summary(analysis),
            "warnings": analysis_run_warnings(analysis, voxel_source=stack.voxel_source),
            "manifest": analysis_manifest(
                analysis,
                source_path=file.filename or str(temp_path.name),
                source_sha256=source_sha256,
                threshold=threshold,
                roi=roi_payload(roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax)),
                z_range=z_range_payload(z_range_from_optional_bounds(z_min, z_max)),
                include_mesh=include_mesh,
                prefer_opencv=prefer_opencv,
                voxel_source=stack.voxel_source,
            ),
            "rows": analysis_rows(analysis),
        }

    @app.post("/upload/preview")
    def upload_preview(
        file: Annotated[UploadFile | None, File()] = None,  # optional when stack_id set
        stack_id: Annotated[str | None, Form()] = None,
        threshold: Annotated[float, Form()] = 0.0,
        frame_index: Annotated[int, Form(ge=0)] = 0,
        profile: Annotated[str, Form()] = DEFAULT_PROFILE,
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
        prefer_opencv: Annotated[bool, Form()] = True,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
        z_min: Annotated[int | None, Form()] = None,
        z_max: Annotated[int | None, Form()] = None,
        object_seed_x: Annotated[float | None, Form()] = None,
        object_seed_y: Annotated[float | None, Form()] = None,
        object_seed_frame: Annotated[int | None, Form()] = None,
        object_seed_radius: Annotated[float, Form()] = 10.0,
        object_seed_max_dist_um: Annotated[float | None, Form()] = None,
        object_seed_type: Annotated[str, Form()] = "circle",
        object_seed_points: Annotated[str | None, Form()] = None,
        enable_skeleton: Annotated[bool, Form()] = False,
        skeleton_prune_pix: Annotated[float, Form()] = 1.0,
        show_selection: Annotated[bool, Form()] = True,
        image_transport: Annotated[str, Form()] = "inline",
        fast_preview: Annotated[bool, Form()] = False,
        # Pure multipart (no stack_id) defaults to sync diagnostic so re-uploads
        # never share tracking cache. Session/stack_id uses subscription (packet 04).
        force_sync_exact: Annotated[bool | None, Form()] = None,
    ) -> dict[str, object]:
        """Multipart or session-backed preview.

        Browser scrub path: ``POST /upload/session`` once, then this endpoint (or
        JSON ``/preview``) with ``stack_id`` + seed. Exact uses cache/job
        subscription — not a request-thread seed-to-target walk.
        """
        from morphostack.core.pipeline import crop_stack_xy
        from morphostack.core.seeded_vesicle import SeededSliceResult
        from morphostack.core.preview import overlay_preview, PreviewImage
        from morphostack.core.contours import SegmentationPreview, contour_circularity
        from morphostack.core.stack_cache import default_tracking_cache
        from io import BytesIO
        import numpy as np

        sid = (stack_id or "").strip() or None
        temp_path: Path | None = None
        source_label = "upload"
        try:
            if sid is not None:
                stack, _ = resolve_stack(
                    path=None, stack_id=sid, voxel=None, compute_sha=False
                )
                source_label = f"session:{sid}"
                stack_identity = f"session:{sid}"
                # Session clients: subscription unless explicitly forced sync.
                use_force_sync = bool(force_sync_exact) if force_sync_exact is not None else False
            else:
                if file is None:
                    raise ValueError("file is required when stack_id is omitted")
                temp_path = save_upload_to_temp(file)
                voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
                stack = load_image_stack(temp_path, voxel_override=voxel_override)
                source_label = file.filename or str(temp_path.name)
                # No durable identity: do not use TrackingResultCache / job share.
                # Request-thread sync walk only for this ephemeral multipart case.
                stack_identity = ""
                use_force_sync = True if force_sync_exact is None else bool(force_sync_exact)

            roi = roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax)
            z_range = z_range_from_optional_bounds(z_min, z_max)
            seed = object_seed_from_optional_fields(
                object_seed_x,
                object_seed_y,
                object_seed_frame,
                radius=object_seed_radius,
                max_tracking_dist_um=object_seed_max_dist_um,
                type=object_seed_type,
                points_json=object_seed_points,
            )
            transport: Literal["inline", "url"] = (
                "url" if str(image_transport).strip().lower() == "url" else "inline"
            )

            # Fast provisional: one-plane only (matches JSON /preview).
            if seed is not None and fast_preview:
                frame, transform = extract_preview_frame(
                    stack.grayscale, frame_index, roi=roi, z_range=z_range
                )
                local_seed = transform.to_local_seed_object(seed)
                preview_image = render_segmentation_preview_png(
                    frame,
                    frame_index=0,
                    threshold=threshold,
                    prefer_opencv=prefer_opencv,
                    object_seed=local_seed,
                    enable_skeleton=enable_skeleton,
                    skeleton_prune_pix=skeleton_prune_pix,
                    voxel_x_um=stack.voxel_size.x_um,
                )
                preview_image = with_global_frame_index(preview_image, frame_index)
                payload = preview_payload(
                    source_label,
                    preview_image,
                    image_transport=transport,
                    preview_quality="provisional",
                    cache_hit=False,
                    requested_threshold=float(threshold),
                    effective_threshold=float(threshold),
                    threshold_semantics="provisional_global",
                    seeded=False,
                    result_ok=True,
                    tracked_center_x=None,
                    tracked_center_y=None,
                )
                payload["exact_available"] = False
                payload["exact_pending"] = False
                payload["tracking_job"] = None
                return payload

            gray = stack.grayscale
            if z_range is not None:
                z0 = max(0, min(gray.shape[0], z_range.zmin))
                z1 = max(0, min(gray.shape[0], z_range.zmax))
                gray = gray[z0:z1]
            if roi is not None:
                gray = crop_stack_xy(gray, roi)
            transform = StackViewTransform.create(
                roi=roi, z_range=z_range, raw_shape=stack.grayscale.shape
            )
            local_frame = frame_index - transform.z_offset
            if local_frame < 0 or local_frame >= gray.shape[0]:
                raise ValueError(f"frame_index {frame_index} is outside the selected Z range / stack")
            frame = gray[local_frame]
            local_seed = transform.to_local_seed_object(seed) if seed is not None else None
            seeded_flag = local_seed is not None

            preview_quality: Literal["provisional", "exact"] = "exact"
            track_cache_hit = False
            tracking_job_payload: dict[str, object] | None = None
            exact_available = True
            exact_pending = False
            tracking_profile = tracking_mode = tracking_algorithm_version = tracking_key_rev = None
            thr_meta: dict[str, object] = {
                "requested_threshold": float(threshold),
                "effective_threshold": float(threshold),
                "threshold_semantics": "global_intensity",
                "threshold": float(threshold),
            }
            tracked_cx: float | None = None
            tracked_cy: float | None = None

            if local_seed is not None:
                if sid is None:
                    # Pure multipart: sync diagnostic only; never write shared cache.
                    from morphostack.core.seeded_vesicle import (
                        effective_seed_radius,
                        track_seeded_vesicle_stack,
                    )
                    from morphostack.core.pipeline import threshold_provenance

                    seed_r = effective_seed_radius(
                        float(local_seed.radius) if local_seed.radius else None
                    )
                    tracked = track_seeded_vesicle_stack(
                        gray,
                        seed_x=float(local_seed.x),
                        seed_y=float(local_seed.y),
                        seed_frame=int(local_seed.frame_index),
                        seed_radius=seed_r,
                        target_frame=int(local_frame),
                    )
                    sres = tracked[local_frame]
                    thr_meta = threshold_provenance(
                        requested=float(threshold),
                        method=str(sres.method or ""),
                        effective=getattr(sres, "effective_threshold", None),
                        ok=bool(sres.ok and sres.contour_xy is not None),
                        seeded=True,
                    )
                else:
                    (
                        sres,
                        track_cache_hit,
                        tracking_job_payload,
                        exact_available,
                        exact_pending,
                        tracking_profile,
                        tracking_mode,
                        tracking_algorithm_version,
                        tracking_key_rev,
                    ) = obtain_exact_seeded_slice(
                        gray=gray,
                        local_seed=local_seed,
                        local_frame=int(local_frame),
                        stack_identity=stack_identity,
                        profile=profile,
                        roi=roi,
                        z_range=z_range,
                        force_sync_exact=use_force_sync,
                        tracking_service=None if use_force_sync else _tracking_service(),
                        tracking_cache=default_tracking_cache,
                    )
                    if not exact_available:
                        preview_quality = "provisional"
                    from morphostack.core.pipeline import threshold_provenance

                    if sres is None:
                        thr_meta = {
                            "requested_threshold": float(threshold),
                            "effective_threshold": float(threshold),
                            "threshold_semantics": "provisional_global",
                            "threshold": float(threshold),
                        }
                        sres = SeededSliceResult(
                            None,
                            None,
                            (float(local_seed.x), float(local_seed.y)),
                            0.0,
                            0.0,
                            "exact_pending",
                            False,
                        )
                    else:
                        thr_meta = threshold_provenance(
                            requested=float(threshold),
                            method=str(sres.method or ""),
                            effective=getattr(sres, "effective_threshold", None),
                            ok=bool(sres.ok and sres.contour_xy is not None),
                            seeded=True,
                        )
                    if sres.method == "exact_pending":
                        thr_meta = {
                            "requested_threshold": float(threshold),
                            "effective_threshold": float(threshold),
                            "threshold_semantics": "provisional_global",
                            "threshold": float(threshold),
                        }

                draw_thr = (
                    float(thr_meta["effective_threshold"])
                    if thr_meta.get("effective_threshold") is not None
                    else float(threshold)
                )
                if (
                    sres.method != "exact_pending"
                    and sres.ok
                    and sres.contour_xy is not None
                    and sres.solid_mask is not None
                ):
                    circ = contour_circularity(sres.contour_xy)
                    seg = SegmentationPreview(
                        threshold=draw_thr,
                        contour=sres.contour_xy,
                        area_px2=float(sres.area_px),
                        perimeter_px=float(sres.perimeter_px),
                        circularity=circ,
                        method=sres.method,
                    )
                    skel_mask = None
                    skel_px = skel_um = None
                    skel_ok = False
                    if enable_skeleton:
                        try:
                            from morphostack.core.skeleton import measure_skeleton

                            skel_mask, sm = measure_skeleton(
                                sres.solid_mask,
                                object_seed=(
                                    int(round(sres.center_xy[0])),
                                    int(round(sres.center_xy[1])),
                                ),
                                prune_threshold_pix=skeleton_prune_pix,
                                voxel_x_um=stack.voxel_size.x_um,
                            )
                            if sm.ok:
                                skel_px, skel_um, skel_ok = sm.perimeter_px, sm.perimeter_um, True
                            else:
                                skel_mask = None
                        except Exception:
                            skel_mask = None
                    tracked_cx = float(sres.center_xy[0])
                    tracked_cy = float(sres.center_xy[1])
                    if show_selection:
                        image = overlay_preview(
                            frame,
                            threshold=draw_thr,
                            preview=seg,
                            object_seed=None,
                            skeleton_mask=skel_mask,
                            highlight_mask=sres.solid_mask,
                        )
                    else:
                        empty_prev = SegmentationPreview(
                            threshold=draw_thr,
                            contour=None,
                            area_px2=float(sres.area_px),
                            perimeter_px=float(sres.perimeter_px),
                            circularity=circ,
                            method=sres.method + "_hidden",
                        )
                        image = overlay_preview(
                            frame,
                            threshold=draw_thr,
                            preview=empty_prev,
                            object_seed=None,
                            skeleton_mask=None,
                            highlight_mask=np.zeros(frame.shape, dtype=bool),
                        )
                        seg = empty_prev
                        tracked_cx, tracked_cy = None, None
                    buf = BytesIO()
                    image.save(buf, format="PNG", compress_level=0, optimize=False)
                    preview_image = PreviewImage(
                        frame_index=frame_index,
                        width=int(frame.shape[1]),
                        height=int(frame.shape[0]),
                        preview=seg,
                        png_bytes=buf.getvalue(),
                        skel_perimeter_px=skel_px if show_selection else None,
                        skel_perimeter_um=skel_um if show_selection else None,
                        skel_ok=skel_ok if show_selection else False,
                    )
                else:
                    empty = SegmentationPreview(
                        threshold=float(threshold),
                        contour=None,
                        area_px2=0.0,
                        perimeter_px=0.0,
                        circularity=0.0,
                        method=sres.method if sres else "circle_seed_lost",
                    )
                    tracked_cx, tracked_cy = None, None
                    image = overlay_preview(
                        frame,
                        threshold=float(threshold),
                        preview=empty,
                        object_seed=None,
                        highlight_mask=np.zeros(frame.shape, dtype=bool),
                    )
                    buf = BytesIO()
                    image.save(buf, format="PNG", compress_level=0, optimize=False)
                    preview_image = PreviewImage(
                        frame_index=frame_index,
                        width=int(frame.shape[1]),
                        height=int(frame.shape[0]),
                        preview=empty,
                        png_bytes=buf.getvalue(),
                    )
            else:
                preview_image = render_segmentation_preview_png(
                    frame,
                    frame_index=0,
                    threshold=threshold,
                    prefer_opencv=prefer_opencv,
                    object_seed=None,
                    enable_skeleton=enable_skeleton,
                    skeleton_prune_pix=skeleton_prune_pix,
                    voxel_x_um=stack.voxel_size.x_um,
                )
                preview_image = with_global_frame_index(preview_image, frame_index)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        payload = preview_payload(
            source_label,
            preview_image,
            image_transport=transport,
            preview_quality=preview_quality,
            cache_hit=track_cache_hit,
            requested_threshold=float(thr_meta["requested_threshold"]),  # type: ignore[arg-type]
            effective_threshold=thr_meta.get("effective_threshold"),  # type: ignore[arg-type]
            threshold_semantics=str(thr_meta["threshold_semantics"]),
            seeded=bool(seeded_flag),
            result_ok=preview_image.preview.contour is not None,
            tracked_center_x=tracked_cx,
            tracked_center_y=tracked_cy,
            tracking_profile=tracking_profile,
            tracking_mode=tracking_mode,
            algorithm_version=tracking_algorithm_version,
            tracking_key_revision=tracking_key_rev,
        )
        payload["exact_available"] = bool(exact_available) if seeded_flag else True
        payload["exact_pending"] = bool(exact_pending)
        payload["tracking_job"] = tracking_job_payload
        return payload

    @app.post("/upload/mesh-preview")
    def upload_mesh_preview(
        file: Annotated[UploadFile, File()],
        threshold: Annotated[float, Form()],
        profile: Annotated[str, Form()] = DEFAULT_PROFILE,
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
        prefer_opencv: Annotated[bool, Form()] = True,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
        z_min: Annotated[int | None, Form()] = None,
        z_max: Annotated[int | None, Form()] = None,
        downsample: Annotated[int, Form(ge=1, le=8)] = 1,
        max_faces: Annotated[int, Form(ge=1000, le=50000)] = 12000,
        object_seed_x: Annotated[float | None, Form()] = None,
        object_seed_y: Annotated[float | None, Form()] = None,
        object_seed_frame: Annotated[int | None, Form()] = None,
        object_seed_radius: Annotated[float, Form()] = 10.0,
        object_seed_max_dist_um: Annotated[float | None, Form()] = None,
        object_seed_type: Annotated[str, Form()] = "circle",
        object_seed_points: Annotated[str | None, Form()] = None,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            stack = load_image_stack(
                temp_path,
                voxel_override=voxel_override,
            )
            roi = roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax)
            z_range = z_range_from_optional_bounds(z_min, z_max)
            seed = object_seed_from_optional_fields(
                object_seed_x,
                object_seed_y,
                object_seed_frame,
                radius=object_seed_radius,
                max_tracking_dist_um=object_seed_max_dist_um,
                type=object_seed_type,
                points_json=object_seed_points,
            )
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=threshold,
                voxel_size=stack.voxel_size,
                roi=roi,
                z_range=z_range,
                profile=profile,
                prefer_opencv=prefer_opencv,
                include_mesh=False,
                object_seed=seed,
                active_surfaces_fast=True,
            )
            filtered = apply_preview_filters(stack.grayscale, roi, z_range)
            geometry = contour_stack_mesh_geometry(
                mesh_contours_from_analysis(analysis),
                shape=filtered.shape,
                voxel=stack.voxel_size,
                downsample=downsample,
                max_faces=max_faces,
            )
            if geometry is None:
                raise ValueError(
                    "No contour for seeded object; check seed/threshold/ROI"
                    if seed is not None
                    else "Mesh preview produced no geometry. Check threshold, seed, and ROI."
                )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return mesh_preview_payload(file.filename or str(temp_path.name), geometry, downsample=downsample)

    @app.post("/upload/batch")
    def upload_batch_analyze(
        files: Annotated[list[UploadFile], File()],
        threshold: Annotated[float, Form()],
        profile: Annotated[str, Form()] = DEFAULT_PROFILE,
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
        include_mesh: Annotated[bool, Form()] = False,
        prefer_opencv: Annotated[bool, Form()] = True,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
        z_min: Annotated[int | None, Form()] = None,
        z_max: Annotated[int | None, Form()] = None,
    ) -> dict[str, object]:
        if not files:
            raise HTTPException(status_code=400, detail="At least one stack file is required.")

        try:
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            roi = roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax)
            z_range = z_range_from_optional_bounds(z_min, z_max)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        rows: list[dict[str, object]] = []
        for file in files:
            temp_path = save_upload_to_temp(file)
            source_name = file.filename or str(temp_path.name)
            source_sha256 = ""
            try:
                source_sha256 = file_sha256(temp_path)
                stack = load_image_stack(
                    temp_path,
                    voxel_override=voxel_override,
                )
                analysis = analyze_stack(
                    stack.grayscale,
                    thresholds=threshold,
                    voxel_size=stack.voxel_size,
                    roi=roi,
                    z_range=z_range,
                    profile=profile,
                    prefer_opencv=prefer_opencv,
                    include_mesh=include_mesh,
                )
                rows.append(
                    analysis_summary_row(
                        analysis,
                        source_path=source_name,
                        threshold=threshold,
                        source_sha256=source_sha256,
                        voxel_source=stack.voxel_source,
                    )
                )
            except Exception as exc:
                rows.append(failed_analysis_summary_row(source_name, str(exc), source_sha256=source_sha256))
            finally:
                temp_path.unlink(missing_ok=True)

        failed_count = sum(1 for row in rows if row["status"] != "ok")
        return {
            "file_count": len(files),
            "succeeded_count": len(files) - failed_count,
            "failed_count": failed_count,
            "columns": list(BATCH_SUMMARY_COLUMNS),
            "rows": rows,
        }

    @app.post("/upload/validate")
    def upload_validate_csv(
        expected_file: Annotated[UploadFile, File()],
        actual_file: Annotated[UploadFile, File()],
        tolerance: Annotated[float, Form()] = 1e-6,
        columns: Annotated[str | None, Form()] = None,
        all_columns: Annotated[bool, Form()] = False,
        key_column: Annotated[str, Form()] = "frame_index",
    ) -> dict[str, object]:
        expected_path = save_upload_to_temp(expected_file)
        actual_path = save_upload_to_temp(actual_file)
        try:
            report = compare_metric_csv(
                expected_path,
                actual_path,
                tolerance=tolerance,
                columns=parse_columns(columns),
                all_columns=all_columns,
                key_column=key_column,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            expected_path.unlink(missing_ok=True)
            actual_path.unlink(missing_ok=True)

        return validation_payload(
            report,
            expected_name=expected_file.filename or "expected.csv",
            actual_name=actual_file.filename or "actual.csv",
        )

    @app.post("/upload/threshold")
    def upload_threshold(
        file: Annotated[UploadFile, File()],
        method: Annotated[str, Form()] = "auto",
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
        z_min: Annotated[int | None, Form()] = None,
        z_max: Annotated[int | None, Form()] = None,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            stack = load_image_stack(
                temp_path,
                voxel_override=voxel_override,
            )
            grayscale = apply_preview_filters(
                stack.grayscale,
                roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax),
                z_range_from_optional_bounds(z_min, z_max),
            )
            from morphostack.core.segmentation import suggest_threshold_report

            display_name = file.filename or "upload"
            revision, id_kind = resolve_suggestion_source_identity(
                ephemeral_upload=True,
            )
            _value, _used, meta = suggest_threshold_report(
                grayscale,
                method=method,
                suggestion_scope="stack_sample",
                source_path=display_name,
                source_revision=revision,
                source_identity_kind=id_kind,
                z_range=z_range_payload(
                    z_range_from_optional_bounds(z_min, z_max)
                ),
                roi=roi_payload(
                    roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax)
                ),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return threshold_payload_from_report(meta)

    @app.post("/upload/sweep")
    def upload_sweep(
        file: Annotated[UploadFile, File()],
        start: Annotated[float, Form()],
        stop: Annotated[float, Form()],
        step: Annotated[float, Form(gt=0)],
        profile: Annotated[str, Form()] = DEFAULT_PROFILE,
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
        include_mesh: Annotated[bool, Form()] = False,
        prefer_opencv: Annotated[bool, Form()] = True,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
        z_min: Annotated[int | None, Form()] = None,
        z_max: Annotated[int | None, Form()] = None,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            thresholds = threshold_values(start, stop, step)
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            stack = load_image_stack(
                temp_path,
                voxel_override=voxel_override,
            )
            results = threshold_sweep(
                stack.grayscale,
                thresholds=thresholds,
                voxel_size=stack.voxel_size,
                roi=roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax),
                z_range=z_range_from_optional_bounds(z_min, z_max),
                profile=profile,
                prefer_opencv=prefer_opencv,
                include_mesh=include_mesh,
                voxel_source=stack.voxel_source,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return sweep_payload(
            source_path=file.filename or str(temp_path.name),
            profile=profile,
            voxel_source=stack.voxel_source,
            results=results,
        )

    if static_dir is None:
        return app
    return mount_static_ui(app, Path(static_dir))


def to_voxel_size(voxel: VoxelOverride | None) -> VoxelSize | None:
    if voxel is None:
        return None
    return VoxelSize(voxel.x_um, voxel.y_um, voxel.z_um)


def try_provisional_preview_via_volume_source(
    *,
    path: str,
    voxel: VoxelOverride | None,
    frame_index: int,
    threshold: float,
    roi: RectROI | None,
    z_range: ZRange | None,
    seed: ObjectSeed | None,
    prefer_opencv: bool,
    enable_skeleton: bool,
    skeleton_prune_pix: float,
    image_transport: str,
    fast_preview: bool,
) -> dict[str, object] | None:
    """Path-based provisional plane preview via VolumeSource, or None to fall back.

    Failures return None so the caller can use full-stack resolve_stack.
    """

    try:
        from morphostack.core.volume_source import open_volume_source

        source = open_volume_source(path, voxel_override=to_voxel_size(voxel), register=True)
        meta = source.metadata()
        transform = StackViewTransform.create(
            roi=roi, z_range=z_range, raw_shape=meta.shape
        )
        local_seed = transform.to_local_seed_object(seed) if seed is not None else None
        # Match existing gate: unseeded always; seeded only when fast_preview.
        if seed is not None and not (fast_preview and local_seed is not None):
            return None
        frame, _ = extract_preview_frame_from_volume(
            source,
            frame_index,
            roi=roi,
            z_range=z_range,
        )
        preview_image = render_segmentation_preview_png(
            frame,
            frame_index=0,
            threshold=threshold,
            prefer_opencv=prefer_opencv,
            object_seed=local_seed,
            enable_skeleton=enable_skeleton,
            skeleton_prune_pix=skeleton_prune_pix,
            voxel_x_um=meta.voxel_size.x_um,
        )
        preview_image = with_global_frame_index(preview_image, frame_index)
        quality = "provisional" if (fast_preview and local_seed is not None) else "exact"
        preview_source_revision, _ = resolve_suggestion_source_identity(
            path=path,
            stack_id=None,
            resolved_source_path=meta.source_path or path,
            ephemeral_upload=False,
        )
        # Prefer volume revision identity when it is the path form.
        if source.revision.kind == "path":
            preview_source_revision = source.revision.identity
        payload = preview_payload(
            meta.source_path or path,
            preview_image,
            image_transport=image_transport,  # type: ignore[arg-type]
            preview_quality=quality,
            cache_hit=False,
            source_revision=preview_source_revision,
            requested_threshold=float(threshold),
            effective_threshold=float(threshold),
            threshold_semantics=(
                "provisional_global" if quality == "provisional" else "global_intensity"
            ),
            seeded=False,
            result_ok=True,
            tracked_center_x=None,
            tracked_center_y=None,
        )
        # Additive display-only diagnostics (non-authoritative).
        payload["volume_source"] = {
            "plane_access_mode": meta.plane_access_mode,
            "revision": source.revision.to_dict(),
            "axes": meta.axes,
            "voxel_source": meta.voxel_source,
        }
        return payload
    except Exception:
        return None


def resolve_stack(
    *,
    path: str | None,
    stack_id: str | None,
    voxel: VoxelOverride | None,
    compute_sha: bool = True,
) -> tuple[ImageStack, str]:
    """Load stack from ``stack_id`` session or disk path.

    Returns ``(stack, source_sha256)``. Session entries keep the SHA from open.
    Path loads only hash the file when ``compute_sha=True`` (analysis/manifests).
    Preview scrubbing should pass ``compute_sha=False`` so the fast path is not
    blocked by a full-file SHA.

    Raises ``ValueError`` for missing/expired sessions or missing identifiers
    (callers map to HTTP 400).
    """
    sid = (stack_id or "").strip() or None
    disk_path = (path or "").strip() or None

    if sid is not None:
        try:
            entry: SessionStackEntry = default_session_store.get(sid)
        except KeyError as exc:
            raise ValueError(
                f"Unknown or expired stack_id {sid!r}. "
                "Re-run Inspect (or open an upload session) to load the stack into server memory."
            ) from exc
        return entry.stack, entry.source_sha256

    if disk_path is not None:
        stack = cached_load_image_stack(disk_path, voxel_override=to_voxel_size(voxel))
        if not compute_sha:
            return stack, ""
        try:
            digest = file_sha256(stack.source_path)
        except OSError:
            digest = ""
        return stack, digest

    raise ValueError("Either path or stack_id is required.")


def get_voxel_override(x: float | None, y: float | None, z: float | None) -> VoxelSize | None:
    vals = [x, y, z]
    num_none = sum(1 for v in vals if v is None)
    if num_none == 3:
        return None
    if num_none == 0:
        # We know x, y, and z are not None here
        return VoxelSize(x_um=x, y_um=y, z_um=z)  # type: ignore[arg-type]
    raise ValueError(
        "Partial voxel override is not allowed; specify all of voxel_x_um, voxel_y_um, and voxel_z_um or none."
    )



def _frame_exact_published(results: list | None, idx: int) -> bool:
    """True when an exact-track slot has been committed (not merely unreached)."""
    if results is None or idx < 0 or idx >= len(results):
        return False
    r = results[idx]
    if r is None:
        return False
    return str(getattr(r, "method", "")) != "circle_seed_unreached"


def obtain_exact_seeded_slice(
    *,
    gray,
    local_seed,
    local_frame: int,
    stack_identity: str,
    profile: str,
    roi,
    z_range,
    force_sync_exact: bool,
    tracking_service,
    tracking_cache,
):
    """Resolve one exact seeded slice via cache/job (default) or diagnostic sync walk.

    Returns
    -------
    sres, track_cache_hit, tracking_job_payload, exact_available, exact_pending,
    tracking_profile, tracking_mode, algorithm_version, tracking_key_rev
    """
    from morphostack.core.seeded_vesicle import (
        effective_seed_radius,
        extend_track,
        track_seeded_vesicle_stack,
    )
    from morphostack.core.stack_cache import make_tracking_cache_key, tracking_key_revision

    seed_r = effective_seed_radius(float(local_seed.radius) if local_seed.radius else None)
    cache_key = make_tracking_cache_key(
        stack_identity=stack_identity,
        seed_x=float(local_seed.x),
        seed_y=float(local_seed.y),
        seed_frame=int(local_seed.frame_index),
        seed_radius=seed_r,
        gray_shape=tuple(int(v) for v in gray.shape),
        roi=roi,
        z_range=z_range,
        profile=profile,
    )
    tracking_profile = cache_key.profile
    tracking_mode = cache_key.tracking_mode
    algorithm_version = cache_key.algorithm_version
    tracking_key_rev = tracking_key_revision(cache_key)
    cached = tracking_cache.get(cache_key)
    sres = None
    track_cache_hit = False
    tracking_job_payload = None
    exact_available = True
    exact_pending = False

    if force_sync_exact:
        track_cache_hit = cached is not None
        if track_cache_hit:
            tracked = extend_track(
                gray,
                seed_x=float(local_seed.x),
                seed_y=float(local_seed.y),
                seed_frame=int(local_seed.frame_index),
                seed_radius=seed_r,
                target_frame=int(local_frame),
                cached_results=cached,
            )
        else:
            tracked = track_seeded_vesicle_stack(
                gray,
                seed_x=float(local_seed.x),
                seed_y=float(local_seed.y),
                seed_frame=int(local_seed.frame_index),
                seed_radius=seed_r,
                target_frame=int(local_frame),
            )
        tracking_cache.merge(cache_key, tracked)
        sres = tracked[local_frame]
        exact_available = True
        exact_pending = False
        return (
            sres,
            track_cache_hit,
            tracking_job_payload,
            exact_available,
            exact_pending,
            tracking_profile,
            tracking_mode,
            algorithm_version,
            tracking_key_rev,
        )

    if tracking_service is None:
        raise RuntimeError("tracking job service required for exact subscription path")

    # Subscription: paint only published exact frames; start/attach one job otherwise.
    if cached is not None and _frame_exact_published(cached, int(local_frame)):
        sres = cached[int(local_frame)]
        track_cache_hit = True
        exact_available = True
        exact_pending = False
        return (
            sres,
            track_cache_hit,
            tracking_job_payload,
            exact_available,
            exact_pending,
            tracking_profile,
            tracking_mode,
            algorithm_version,
            tracking_key_rev,
        )

    direction = None
    seed_f = int(local_seed.frame_index)
    if int(local_frame) > seed_f:
        direction = 1
    elif int(local_frame) < seed_f:
        direction = -1
    snap = tracking_service.start(
        key=cache_key,
        stack=gray,
        seed_x=float(local_seed.x),
        seed_y=float(local_seed.y),
        seed_frame=seed_f,
        seed_radius=seed_r,
        target_z=int(local_frame),
        direction_priority=direction,
    )
    if snap.attached:
        snap = tracking_service.reprioritize(
            snap.job_id,
            target_z=int(local_frame),
            direction_priority=direction,
        )
    tracking_job_payload = snap.to_json_dict()
    tracking_job_payload["process_local"] = True
    cached2 = tracking_cache.get(cache_key)
    if cached2 is not None and _frame_exact_published(cached2, int(local_frame)):
        sres = cached2[int(local_frame)]
        track_cache_hit = True
        exact_available = True
        exact_pending = False
    else:
        sres = None
        exact_available = False
        exact_pending = snap.state in ("queued", "running", "partial")
    return (
        sres,
        track_cache_hit,
        tracking_job_payload,
        exact_available,
        exact_pending,
        tracking_profile,
        tracking_mode,
        algorithm_version,
        tracking_key_rev,
    )


def to_rect_roi(roi: ROIRequest | None) -> RectROI | None:
    if roi is None:
        return None
    return RectROI(roi.xmin, roi.xmax, roi.ymin, roi.ymax)


def to_z_range(z_range: ZRangeRequest | None) -> ZRange | None:
    if z_range is None:
        return None
    return ZRange(z_range.zmin, z_range.zmax)


def _stack_source_revision(
    *,
    path: str | None,
    stack_id: str | None,
    stack: object,
) -> str:
    """Canonical stack identity matching display-pyramid / tracking keys."""

    from morphostack.core.stack_cache import path_source_identity

    sid = (stack_id or "").strip()
    if sid:
        return f"session:{sid}"
    source_path = getattr(stack, "source_path", None)
    if source_path is not None:
        return path_source_identity(source_path)
    disk = (path or "").strip()
    if disk:
        return path_source_identity(disk)
    raise ValueError("cannot resolve source_revision for seed validation")


def to_object_seed(seed: ObjectSeedRequest | None) -> ObjectSeed | None:
    if seed is None:
        return None
    pts = [SeedPoint(x=p.x, y=p.y) for p in seed.points] if seed.points is not None else None
    radius_unit = (seed.radius_unit or "px").strip().lower()
    if radius_unit != "px":
        raise ValueError(
            "object_seed.radius_unit must be 'px' (source-level pixels); "
            "convert micrometres client-side with known calibration"
        )
    origin = (seed.seed_origin or "ui_2d").strip() or "ui_2d"
    if origin not in {"ui_2d", "viewer_3d"}:
        raise ValueError("object_seed.seed_origin must be 'ui_2d' or 'viewer_3d'")
    return ObjectSeed(
        x=seed.x,
        y=seed.y,
        frame_index=seed.frame_index,
        radius=seed.radius,
        max_tracking_dist_um=seed.max_tracking_dist_um,
        type=seed.type,
        points=pts,
        source_revision=(seed.source_revision.strip() if seed.source_revision else None) or None,
        seed_origin=origin,
        radius_unit="px",
    )


def validate_object_seed_against_stack(
    seed: ObjectSeed | None,
    *,
    gray_shape: tuple[int, ...],
    current_source_revision: str | None,
) -> None:
    """Bounds + optional stale display revision check (packet 13)."""

    if seed is None:
        return
    if len(gray_shape) < 3:
        raise ValueError("stack shape must be (z, y, x)")
    z, y, x = int(gray_shape[0]), int(gray_shape[1]), int(gray_shape[2])
    if not (0 <= int(seed.frame_index) < z):
        raise ValueError(f"object_seed.frame_index {seed.frame_index} out of bounds for Z={z}")
    if not (0 <= float(seed.x) < x and 0 <= float(seed.y) < y):
        raise ValueError(
            f"object_seed (x,y)=({seed.x}, {seed.y}) out of bounds for XY=({x}, {y})"
        )
    if float(seed.radius) <= 0:
        raise ValueError("object_seed.radius must be positive (source pixels)")
    from morphostack.core.seed_mapping import SeedMappingError, validate_seed_revision

    try:
        validate_seed_revision(
            seed_revision=getattr(seed, "source_revision", None),
            current_revision=current_source_revision,
        )
    except SeedMappingError as exc:
        raise ValueError(str(exc)) from exc


def object_seed_from_optional_fields(
    x: float | None,
    y: float | None,
    frame_index: int | None,
    radius: float = 10.0,
    max_tracking_dist_um: float | None = None,
    type: str = "circle",
    points_json: str | None = None,
) -> ObjectSeed | None:
    if type == "polygon":
        if frame_index is None:
            return None
        if not points_json:
            raise ValueError("Polygon seed requires points")
        import json
        try:
            pts_list = json.loads(points_json)
            pts = [SeedPoint(x=float(p["x"]), y=float(p["y"])) for p in pts_list]
        except Exception as exc:
            raise ValueError(f"Failed to parse points JSON: {exc}")

        xs = [pt.x for pt in pts]
        ys = [pt.y for pt in pts]
        centroid_x = sum(xs) / len(xs) if xs else 0.0
        centroid_y = sum(ys) / len(ys) if ys else 0.0
        bounding_radius = max(((pt.x - centroid_x)**2 + (pt.y - centroid_y)**2)**0.5 for pt in pts) if pts else radius

        return ObjectSeed(
            x=centroid_x,
            y=centroid_y,
            frame_index=frame_index,
            radius=bounding_radius,
            max_tracking_dist_um=max_tracking_dist_um,
            type="polygon",
            points=pts
        )

    values = (x, y, frame_index)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("Object seed requires object_seed_x, object_seed_y, and object_seed_frame")
    return ObjectSeed(
        x=x,
        y=y,
        frame_index=frame_index,
        radius=radius,
        max_tracking_dist_um=max_tracking_dist_um,
        type="circle",
        points=None
    )


def roi_from_optional_bounds(
    xmin: int | None,
    xmax: int | None,
    ymin: int | None,
    ymax: int | None,
) -> RectROI | None:
    values = (xmin, xmax, ymin, ymax)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("ROI requires xmin, xmax, ymin, and ymax")
    return RectROI(xmin, xmax, ymin, ymax)


def z_range_from_optional_bounds(z_min: int | None, z_max: int | None) -> ZRange | None:
    values = (z_min, z_max)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("Z range requires z_min and z_max")
    return ZRange(z_min, z_max)


def roi_payload(roi: RectROI | None) -> dict[str, int] | None:
    if roi is None:
        return None
    return {"xmin": roi.xmin, "xmax": roi.xmax, "ymin": roi.ymin, "ymax": roi.ymax}


def z_range_payload(z_range: ZRange | None) -> dict[str, int] | None:
    if z_range is None:
        return None
    return {"zmin": z_range.zmin, "zmax": z_range.zmax}


def apply_preview_filters(stack, roi: RectROI | None, z_range: ZRange | None):
    if z_range is not None:
        stack = apply_z_range(stack, zmin=z_range.zmin, zmax=z_range.zmax)
    if roi is None:
        return stack
    return apply_rect_roi(
        stack,
        xmin=roi.xmin,
        xmax=roi.xmax,
        ymin=roi.ymin,
        ymax=roi.ymax,
    )


def save_upload_to_temp(file: UploadFile) -> Path:
    suffix = Path(file.filename or "upload.tif").suffix or ".tif"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(handle.name)
    try:
        with handle:
            shutil.copyfileobj(file.file, handle)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        file.file.seek(0)
    return temp_path


def preview_payload(
    source_path: str,
    preview_image: PreviewImage,
    *,
    image_transport: Literal["inline", "url"] = "inline",
    preview_quality: Literal["provisional", "exact"] = "exact",
    cache_hit: bool = False,
    requested_threshold: float | None = None,
    effective_threshold: float | None = None,
    threshold_semantics: str | None = None,
    seeded: bool = False,
    result_ok: bool | None = None,
    tracked_center_x: float | None = None,
    tracked_center_y: float | None = None,
    tracking_profile: str | None = None,
    tracking_mode: str | None = None,
    algorithm_version: str | None = None,
    tracking_key_revision: str | None = None,
    source_revision: str | None = None,
) -> dict[str, object]:
    """Build preview JSON.

    ``tracked_center_x/y`` are optional, nullable fields for exact seeded
    results. Coordinates match the preview image / contour frame: after any
    user ROI crop and Z crop, same as ``SeededSliceResult.center_xy`` (not the
    immutable user seed). Provisional, lost, or failed frames must pass null —
    never the original seed as a false current center.

    When the seeded exact path builds a :class:`TrackingCacheKey`, identity
    scaffolding fields (profile, mode, algorithm_version, key revision) are
    included for cache/job lifecycle consumers. No job service is started here.
    """
    from morphostack.core.pipeline import json_safe_float, threshold_provenance

    preview = preview_image.preview
    req = json_safe_float(requested_threshold)
    if req is None:
        req = json_safe_float(preview.threshold) or 0.0
    ok = True if result_ok is None else bool(result_ok)

    if threshold_semantics is None:
        thr_meta = threshold_provenance(
            requested=float(req),
            method=str(preview.method or ""),
            effective=json_safe_float(effective_threshold),
            ok=ok,
            provisional=preview_quality == "provisional",
            seeded=bool(seeded),
        )
        req_out = thr_meta["requested_threshold"]
        eff = thr_meta["effective_threshold"]
        sem = str(thr_meta["threshold_semantics"])
        legacy = thr_meta["threshold"]
    else:
        eff = json_safe_float(effective_threshold)
        sem = str(threshold_semantics)
        req_out = req
        legacy = eff if eff is not None else (
            req if sem in ("global_intensity", "provisional_global") else None
        )

    # Only emit a tracked center on exact accepted frames (both coords finite).
    tcx = json_safe_float(tracked_center_x)
    tcy = json_safe_float(tracked_center_y)
    if preview_quality != "exact" or not ok or tcx is None or tcy is None:
        tcx, tcy = None, None

    from morphostack.core.segmentation import THRESHOLD_CONTRACT_VERSION

    payload: dict[str, object] = {
        "source_path": source_path,
        "frame": preview_image.frame_index,
        "frame_index": preview_image.frame_index,
        "width": preview_image.width,
        "height": preview_image.height,
        # Legacy: effective gate when used; JSON null when polar/unavailable.
        "threshold": legacy,
        "requested_threshold": req_out,
        "effective_threshold": eff,
        "threshold_semantics": sem,
        "threshold_contract_version": THRESHOLD_CONTRACT_VERSION,
        "method": preview.method,
        "area_px2": preview.area_px2,
        "perimeter_px": preview.perimeter_px,
        "circularity": preview.circularity,
        "skel_ok": preview_image.skel_ok,
        "skel_perimeter_px": preview_image.skel_perimeter_px,
        "skel_perimeter_um": preview_image.skel_perimeter_um,
        # provisional = one-plane fast overlay (not authoritative object identity).
        # exact = full one-plane result without seed, or seeded tracker result.
        "preview_quality": preview_quality,
        "cache_hit": bool(cache_hit),
        # Tracking/cache identity when known (path:… or session:…); never a bare filename.
        "source_revision": source_revision,
        "tracking_revision": tracking_key_revision,
        # Preview-image coordinates (post ROI/Z crop), same frame as contour.
        "tracked_center_x": tcx,
        "tracked_center_y": tcy,
        # Exact tracking identity scaffolding (null when no seeded track key).
        "tracking_profile": tracking_profile,
        "tracking_mode": tracking_mode,
        "algorithm_version": algorithm_version,
        "tracking_key_revision": tracking_key_revision,
    }
    if image_transport == "url":
        payload["image_url"] = f"/api/preview-image/{_store_preview_image(preview_image.png_bytes)}"
    else:
        payload["image_png_base64"] = b64encode(preview_image.png_bytes).decode("ascii")
    return payload


def validate_scientific_mesh_input(obj: object, *, context: str = "mesh measurement") -> None:
    """Reject display/candidate products as scientific mesh or metric inputs.

    Used by analysis/mesh routes when a typed authority object is supplied.
    Raw arrays and contour sequences remain the legacy path.
    """

    try:
        reject_non_scientific_input(obj, context=context)
        role = result_role_of(obj)
        if role in ("display_volume", "display_mesh", "segmentation_candidate"):
            raise ResultAuthorityError(
                f"{context} rejects role={role!r}",
                role=role,
            )
        if isinstance(obj, (DisplayVolumeSpec, DisplayMesh, SegmentationCandidate)):
            raise ResultAuthorityError(
                f"{context} rejects {type(obj).__name__}",
                role=getattr(obj, "role", None),
            )
    except ResultAuthorityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def mesh_preview_payload(source_path: str, geometry: MeshGeometry | None, *, downsample: int) -> dict[str, object]:
    # Preview geometry is a display product. Reported surface/volume numbers on
    # this payload come from the complete marching-cubes measurement taken
    # before weld/compact (display-only). Preview faces must not be re-imported
    # as AuthoritativeMask / scientific export geometry.
    authority_meta = {
        "geometry_role": "display",
        "display_only": True,
        "display_method": "weld_compact",
        "measurement_source": "complete_marching_cubes",
        "measurement_authority_note": (
            "surface_area_um2/volume_um3 are from the complete mesh before "
            "display weld/compact; preview faces are not scientific geometry"
        ),
    }
    if geometry is None:
        return {
            "source_path": source_path,
            "has_mesh": False,
            "downsample": downsample,
            "vertex_count": 0,
            "face_count": 0,
            "vertices": [],
            "faces": [],
            "surface_area_um2": 0.0,
            "volume_um3": 0.0,
            "equivalent_sphere_diameter_um": 0.0,
            "sphericity": 0.0,
            "display_only": True,
            "display_method": "weld_compact",
            "result_authority": authority_meta,
        }
    # Guard: never treat a typed DisplayMesh/DisplayVolume as preview source
    # that overwrites scientific authority fields.
    if isinstance(geometry, (DisplayMesh, DisplayVolumeSpec, SegmentationCandidate)):
        raise HTTPException(
            status_code=400,
            detail=f"mesh preview rejects non-geometry authority type {type(geometry).__name__}",
        )
    measurement = geometry.measurement
    vertices = geometry.vertices_xyz.round(6).tolist()
    faces = geometry.faces.astype(int).tolist()
    display_method = geometry.display_method or "weld_compact"
    authority_meta = {
        **authority_meta,
        "display_method": display_method,
        "source_vertex_count": geometry.source_vertex_count,
        "source_face_count": geometry.source_face_count,
        "output_vertex_count": int(len(vertices)),
        "output_face_count": int(len(faces)),
        "boundary_edge_count_source": geometry.boundary_edge_count_source,
        "boundary_edge_count_display": geometry.boundary_edge_count_display,
        "within_face_budget": geometry.within_face_budget,
        "face_budget": geometry.face_budget,
        "display_only": bool(geometry.display_only) if geometry.display_only is not None else True,
    }
    return {
        "source_path": source_path,
        "has_mesh": True,
        "downsample": downsample,
        "vertex_count": int(len(vertices)),
        "face_count": int(len(faces)),
        "vertices": vertices,
        "faces": faces,
        "surface_area_um2": measurement.surface_area_um2,
        "volume_um3": measurement.volume_um3,
        "equivalent_sphere_diameter_um": measurement.equivalent_sphere_diameter_um,
        "sphericity": measurement.sphericity,
        "display_only": True,
        "display_method": display_method,
        "source_vertex_count": geometry.source_vertex_count,
        "source_face_count": geometry.source_face_count,
        "boundary_edge_count_source": geometry.boundary_edge_count_source,
        "boundary_edge_count_display": geometry.boundary_edge_count_display,
        "within_face_budget": geometry.within_face_budget,
        "result_authority": authority_meta,
    }


def resolve_suggestion_source_identity(
    *,
    path: str | None = None,
    stack_id: str | None = None,
    resolved_source_path: str | None = None,
    ephemeral_upload: bool = False,
) -> tuple[str | None, str]:
    """Map threshold suggestion to tracking/cache stack identity.

    Returns ``(source_revision, source_identity_kind)``:

    - path → ``path_source_identity`` (``path:…|m…|s…``), kind ``path``
    - session → ``session:{stack_id}``, kind ``session``
    - ephemeral multipart → ``(None, "upload_ephemeral")`` — never a filename
    """
    if ephemeral_upload:
        return None, "upload_ephemeral"
    sid = (stack_id or "").strip()
    if sid:
        return f"session:{sid}", "session"
    from morphostack.core.stack_cache import path_source_identity

    path_for_id = (path or resolved_source_path or "").strip()
    if not path_for_id:
        return None, "unknown"
    return path_source_identity(path_for_id), "path"


def threshold_payload(source_path: str, threshold: float, method: str) -> dict[str, object]:
    """Legacy compatibility payload (threshold + method). Prefer contract report."""
    from morphostack.core.segmentation import THRESHOLD_CONTRACT_VERSION

    return {
        "source_path": source_path,
        # Unknown identity: do not pretend display path is a revision.
        "source_revision": None,
        "source_identity_kind": "unknown",
        "threshold": threshold,
        "method": method,
        "threshold_semantics": "ui_starting_guess",
        "suggestion_scope": "stack_sample",
        "threshold_contract_version": THRESHOLD_CONTRACT_VERSION,
        "authoritative_for": [],
        "not_authoritative_for": [
            "seeded_exact_contour",
            "seeded_exact_mask",
            "per_frame_adaptive_threshold",
        ],
        "warnings": [
            "Single global starting guess; intensity may vary across Z.",
            "Seeded exact analysis uses a per-frame local gate or ridge method.",
        ],
    }


def threshold_payload_from_report(meta: dict[str, object]) -> dict[str, object]:
    """Full THRESHOLD_CONTRACT suggestion response (keeps top-level threshold/method)."""
    # Preserve explicit null revisions (ephemeral upload); do not fall back to filename.
    rev = meta["source_revision"] if "source_revision" in meta else None
    return {
        "source_path": meta.get("source_path", ""),
        "source_revision": rev,
        "source_identity_kind": meta.get("source_identity_kind", "unknown"),
        "threshold": meta.get("threshold"),
        "method": meta.get("method"),
        "threshold_semantics": meta.get("threshold_semantics", "ui_starting_guess"),
        "suggestion_scope": meta.get("suggestion_scope", "stack_sample"),
        "histogram_domain": meta.get("histogram_domain") or {},
        "authoritative_for": list(meta.get("authoritative_for") or []),
        "not_authoritative_for": list(meta.get("not_authoritative_for") or []),
        "warnings": list(meta.get("warnings") or []),
        "threshold_contract_version": meta.get("threshold_contract_version", "1"),
    }


def sweep_payload(source_path: str, profile: str, voxel_source: str, results) -> dict[str, object]:
    best = best_sweep_result(results)
    best_threshold = best.threshold if best else None
    return {
        "source_path": source_path,
        "profile": profile,
        "voxel_source": voxel_source,
        "threshold_count": len(results),
        "best_threshold": best_threshold,
        "columns": list(SWEEP_COLUMNS),
        "rows": threshold_sweep_rows(results),
    }


def validation_payload(report, *, expected_name: str, actual_name: str) -> dict[str, object]:
    return {
        "passed": report.passed,
        "expected_path": expected_name,
        "actual_path": actual_name,
        "tolerance": report.tolerance,
        "compared_rows": report.compared_rows,
        "compared_cells": report.compared_cells,
        "differences": [
            {
                "row_id": difference.row_id,
                "column": difference.column,
                "expected": difference.expected,
                "actual": difference.actual,
                "delta": difference.delta,
            }
            for difference in report.differences
        ],
    }


def parse_columns(columns: str | None) -> list[str] | None:
    if columns is None or not columns.strip():
        return None
    return [column for column in columns.replace(",", " ").split() if column]


def voxel_payload(voxel: VoxelSize) -> dict[str, float]:
    return {"x_um": voxel.x_um, "y_um": voxel.y_um, "z_um": voxel.z_um}


def parse_excluded_frames_text(value: str | None) -> list[int]:
    if not value or not value.strip():
        return []
    frames: list[int] = []
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if part:
            frames.append(int(part))
    return frames


def mount_static_ui(api: FastAPI, static_dir: Path) -> FastAPI:
    """Serve API under /api and the built SPA from static_dir.

    Use a pure ASGI mount of the API app so upload routes stay on the same
    process as the static UI (morphostack app single-port mode).
    """
    from fastapi import FastAPI as RootFastAPI
    from fastapi.staticfiles import StaticFiles

    root = RootFastAPI(title="MorphoStack", version=__version__)
    try:
        from fastapi.middleware.cors import CORSMiddleware

        root.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception:
        pass

    # Mount API first so /api/* is never swallowed by the SPA static handler.
    root.mount("/api", api)
    root.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    return root


app = create_app()
