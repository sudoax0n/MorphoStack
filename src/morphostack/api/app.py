"""FastAPI application for the local MorphoStack backend."""

from __future__ import annotations

import shutil
import tempfile
from base64 import b64encode
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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
    StackViewTransform,
    ZRange,
    analyze_stack,
    analysis_manifest,
    analysis_run_warnings,
    analysis_summary,
    analysis_summary_row,
    best_sweep_result,
    compare_metric_csv,
    failed_analysis_summary_row,
    file_sha256,
    inspect_image_stack,
    load_image_stack,
    suggest_threshold,
    threshold_sweep,
    threshold_sweep_rows,
    threshold_values,
)
from morphostack.core.export import BATCH_SUMMARY_COLUMNS, analysis_rows
from morphostack.core.mesh import MeshGeometry, contour_stack_mesh_geometry, write_mesh_file
from morphostack.core.pipeline import object_seed_payload, tracking_diagnostics_payload
from morphostack.core.preview import PreviewImage, render_segmentation_preview_png
from morphostack.core.segmentation import apply_rect_roi, apply_z_range


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


class InspectRequest(BaseModel):
    path: str
    voxel: VoxelOverride | None = None


class AnalyzeRequest(BaseModel):
    path: str
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    include_mesh: bool = False
    prefer_opencv: bool = True
    object_seed: ObjectSeedRequest | None = None


class MeshPreviewRequest(BaseModel):
    path: str
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    prefer_opencv: bool = True
    downsample: int = Field(default=2, ge=1, le=8)
    max_faces: int = Field(default=12000, ge=1000, le=50000)
    object_seed: ObjectSeedRequest | None = None


class MeshExportRequest(BaseModel):
    path: str
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    prefer_opencv: bool = True
    downsample: int = Field(default=1, ge=1, le=8)
    max_faces: int = Field(default=50000, ge=1000, le=100000)
    object_seed: ObjectSeedRequest | None = None
    destination: str


class PreviewRequest(BaseModel):
    path: str
    threshold: float
    frame_index: int = Field(default=0, ge=0)
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    prefer_opencv: bool = True
    object_seed: ObjectSeedRequest | None = None


class ThresholdRequest(BaseModel):
    path: str
    method: str = "auto"
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None


class SweepRequest(BaseModel):
    path: str
    start: float
    stop: float
    step: float = Field(gt=0)
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    z_range: ZRangeRequest | None = None
    include_mesh: bool = False
    prefer_opencv: bool = True


def create_app() -> FastAPI:
    app = FastAPI(title="MorphoStack API", version=__version__)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__, "profiles": list(PROFILE_CHOICES)}

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
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
            source_sha256 = file_sha256(stack.source_path)
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=request.threshold,
                voxel_size=stack.voxel_size,
                roi=to_rect_roi(request.roi),
                z_range=to_z_range(request.z_range),
                profile=request.profile,
                prefer_opencv=request.prefer_opencv,
                include_mesh=request.include_mesh,
                object_seed=to_object_seed(request.object_seed),
            )
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
            "voxel_size": voxel_payload(stack.voxel_size),
            "voxel_source": stack.voxel_source,
            "mesh": mesh,
            "summary": analysis_summary(analysis),
            "warnings": analysis_run_warnings(analysis, voxel_source=stack.voxel_source),
            "object_seed": object_seed_payload(to_object_seed(request.object_seed)),
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
                object_seed=to_object_seed(request.object_seed),
            ),
            "rows": analysis_rows(analysis),
        }

    @app.post("/threshold")
    def threshold(request: ThresholdRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
            grayscale = apply_preview_filters(stack.grayscale, to_rect_roi(request.roi), to_z_range(request.z_range))
            value, method = suggest_threshold(grayscale, method=request.method)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return threshold_payload(str(stack.source_path), value, method)

    @app.post("/preview")
    def preview(request: PreviewRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
            roi = to_rect_roi(request.roi)
            z_range = to_z_range(request.z_range)
            
            transform = StackViewTransform.create(roi=roi, z_range=z_range, raw_shape=stack.grayscale.shape)
            grayscale = apply_preview_filters(stack.grayscale, roi, z_range)
            
            local_frame = request.frame_index - transform.z_offset
            if z_range is not None:
                if request.frame_index < z_range.zmin or request.frame_index >= z_range.zmax:
                    raise ValueError(f"Requested frame_index {request.frame_index} is outside selected Z-range [{z_range.zmin}, {z_range.zmax})")
            if local_frame < 0 or local_frame >= grayscale.shape[0]:
                raise ValueError(f"Local frame_index {local_frame} is outside bounds (0-{grayscale.shape[0] - 1})")

            seed = to_object_seed(request.object_seed)
            if seed is not None:
                local_seed = transform.to_local_seed_object(seed)
            else:
                local_seed = None

            preview_image = render_segmentation_preview_png(
                grayscale,
                frame_index=local_frame,
                threshold=request.threshold,
                prefer_opencv=request.prefer_opencv,
                object_seed=local_seed,
            )
            preview_image = PreviewImage(
                frame_index=request.frame_index,
                width=preview_image.width,
                height=preview_image.height,
                preview=preview_image.preview,
                png_bytes=preview_image.png_bytes,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return preview_payload(str(stack.source_path), preview_image)

    @app.post("/mesh-preview")
    def mesh_preview(request: MeshPreviewRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
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
            )
            filtered = apply_preview_filters(stack.grayscale, roi, z_range)
            geometry = contour_stack_mesh_geometry(
                tuple(frame.contour for frame in analysis.frames),
                shape=filtered.shape,
                voxel=stack.voxel_size,
                downsample=request.downsample,
                max_faces=request.max_faces,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return mesh_preview_payload(str(stack.source_path), geometry, downsample=request.downsample)

    @app.post("/mesh-export")
    def mesh_export(request: MeshExportRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
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
            )
            filtered = apply_preview_filters(stack.grayscale, roi, z_range)
            geometry = contour_stack_mesh_geometry(
                tuple(frame.contour for frame in analysis.frames),
                shape=filtered.shape,
                voxel=stack.voxel_size,
                downsample=request.downsample,
                max_faces=request.max_faces,
            )
            if geometry is None:
                raise ValueError("Mesh export produced no geometry. Check threshold, seed, and ROI.")
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
            "object_seed": object_seed_payload(to_object_seed(request.object_seed)),
            "tracking": tracking_diagnostics_payload(analysis.tracking),
        }

    @app.post("/sweep")
    def sweep(request: SweepRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
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

    @app.post("/upload/inspect")
    def upload_inspect_stack(
        file: Annotated[UploadFile, File()],
        voxel_x_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_y_um: Annotated[float | None, Form(gt=0)] = None,
        voxel_z_um: Annotated[float | None, Form(gt=0)] = None,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            voxel_override = get_voxel_override(voxel_x_um, voxel_y_um, voxel_z_um)
            info = inspect_image_stack(
                temp_path,
                voxel_override=voxel_override,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return {
            "source_path": file.filename or str(temp_path.name),
            "grayscale_shape": list(info["grayscale_shape"]),
            "color_shape": list(info["color_shape"]),
            "voxel_size": voxel_payload(info["voxel_size"]),
            "voxel_source": info["voxel_source"],
        }

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
            "voxel_size": voxel_payload(stack.voxel_size),
            "voxel_source": stack.voxel_source,
            "mesh": mesh,
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
        file: Annotated[UploadFile, File()],
        threshold: Annotated[float, Form()],
        frame_index: Annotated[int, Form(ge=0)] = 0,
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
            
            transform = StackViewTransform.create(roi=roi, z_range=z_range, raw_shape=stack.grayscale.shape)
            grayscale = apply_preview_filters(stack.grayscale, roi, z_range)
            
            local_frame = frame_index - transform.z_offset
            if z_range is not None:
                if frame_index < z_range.zmin or frame_index >= z_range.zmax:
                    raise ValueError(f"Requested frame_index {frame_index} is outside selected Z-range [{z_range.zmin}, {z_range.zmax})")
            if local_frame < 0 or local_frame >= grayscale.shape[0]:
                raise ValueError(f"Local frame_index {local_frame} is outside bounds (0-{grayscale.shape[0] - 1})")

            seed = object_seed_from_optional_fields(
                object_seed_x,
                object_seed_y,
                object_seed_frame,
                radius=object_seed_radius,
                max_tracking_dist_um=object_seed_max_dist_um,
                type=object_seed_type,
                points_json=object_seed_points,
            )
            if seed is not None:
                local_seed = transform.to_local_seed_object(seed)
            else:
                local_seed = None

            preview_image = render_segmentation_preview_png(
                grayscale,
                frame_index=local_frame,
                threshold=threshold,
                prefer_opencv=prefer_opencv,
                object_seed=local_seed,
            )
            preview_image = PreviewImage(
                frame_index=frame_index,
                width=preview_image.width,
                height=preview_image.height,
                preview=preview_image.preview,
                png_bytes=preview_image.png_bytes,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return preview_payload(file.filename or str(temp_path.name), preview_image)

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
        downsample: Annotated[int, Form(ge=1, le=8)] = 2,
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
            )
            filtered = apply_preview_filters(stack.grayscale, roi, z_range)
            geometry = contour_stack_mesh_geometry(
                tuple(frame.contour for frame in analysis.frames),
                shape=filtered.shape,
                voxel=stack.voxel_size,
                downsample=downsample,
                max_faces=max_faces,
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
            value, used_method = suggest_threshold(grayscale, method=method)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return threshold_payload(file.filename or str(temp_path.name), value, used_method)

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

    return app


def to_voxel_size(voxel: VoxelOverride | None) -> VoxelSize | None:
    if voxel is None:
        return None
    return VoxelSize(voxel.x_um, voxel.y_um, voxel.z_um)


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



def to_rect_roi(roi: ROIRequest | None) -> RectROI | None:
    if roi is None:
        return None
    return RectROI(roi.xmin, roi.xmax, roi.ymin, roi.ymax)


def to_z_range(z_range: ZRangeRequest | None) -> ZRange | None:
    if z_range is None:
        return None
    return ZRange(z_range.zmin, z_range.zmax)


def to_object_seed(seed: ObjectSeedRequest | None) -> ObjectSeed | None:
    if seed is None:
        return None
    pts = [SeedPoint(x=p.x, y=p.y) for p in seed.points] if seed.points is not None else None
    return ObjectSeed(
        x=seed.x,
        y=seed.y,
        frame_index=seed.frame_index,
        radius=seed.radius,
        max_tracking_dist_um=seed.max_tracking_dist_um,
        type=seed.type,
        points=pts,
    )


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


def preview_payload(source_path: str, preview_image: PreviewImage) -> dict[str, object]:
    preview = preview_image.preview
    return {
        "source_path": source_path,
        "frame_index": preview_image.frame_index,
        "width": preview_image.width,
        "height": preview_image.height,
        "threshold": preview.threshold,
        "method": preview.method,
        "area_px2": preview.area_px2,
        "perimeter_px": preview.perimeter_px,
        "circularity": preview.circularity,
        "image_png_base64": b64encode(preview_image.png_bytes).decode("ascii"),
    }


def mesh_preview_payload(source_path: str, geometry: MeshGeometry | None, *, downsample: int) -> dict[str, object]:
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
        }
    measurement = geometry.measurement
    vertices = geometry.vertices_xyz.round(6).tolist()
    faces = geometry.faces.astype(int).tolist()
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
    }


def threshold_payload(source_path: str, threshold: float, method: str) -> dict[str, object]:
    return {"source_path": source_path, "threshold": threshold, "method": method}


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


app = create_app()
