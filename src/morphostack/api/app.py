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
    PROFILE_CHOICES,
    RectROI,
    VoxelSize,
    analyze_stack,
    analysis_manifest,
    analysis_summary,
    analysis_warnings,
    load_image_stack,
    suggest_threshold,
)
from morphostack.core.export import analysis_rows
from morphostack.core.preview import PreviewImage, render_segmentation_preview_png
from morphostack.core.segmentation import apply_rect_roi


class VoxelOverride(BaseModel):
    x_um: float = Field(gt=0)
    y_um: float = Field(gt=0)
    z_um: float = Field(gt=0)


class ROIRequest(BaseModel):
    xmin: int
    xmax: int
    ymin: int
    ymax: int


class InspectRequest(BaseModel):
    path: str
    voxel: VoxelOverride | None = None


class AnalyzeRequest(BaseModel):
    path: str
    threshold: float
    profile: str = DEFAULT_PROFILE
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    include_mesh: bool = False
    prefer_opencv: bool = True


class PreviewRequest(BaseModel):
    path: str
    threshold: float
    frame_index: int = Field(default=0, ge=0)
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    prefer_opencv: bool = True


class ThresholdRequest(BaseModel):
    path: str
    method: str = "auto"
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="MorphoStack API", version=__version__)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__, "profiles": list(PROFILE_CHOICES)}

    @app.post("/inspect")
    def inspect_stack(request: InspectRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "source_path": str(stack.source_path),
            "grayscale_shape": list(stack.grayscale.shape),
            "color_shape": list(stack.color.shape),
            "voxel_size": voxel_payload(stack.voxel_size),
        }

    @app.post("/analyze")
    def analyze(request: AnalyzeRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=request.threshold,
                voxel_size=stack.voxel_size,
                roi=to_rect_roi(request.roi),
                profile=request.profile,
                prefer_opencv=request.prefer_opencv,
                include_mesh=request.include_mesh,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        mesh = None
        if analysis.mesh:
            mesh = {
                "surface_area_um2": analysis.mesh.surface_area_um2,
                "volume_um3": analysis.mesh.volume_um3,
            }
        return {
            "source_path": str(stack.source_path),
            "profile": analysis.profile,
            "frame_count": len(analysis.frames),
            "valid_frame_count": len(analysis.valid_frames),
            "voxel_size": voxel_payload(stack.voxel_size),
            "mesh": mesh,
            "summary": analysis_summary(analysis),
            "warnings": analysis_warnings(analysis),
            "manifest": analysis_manifest(
                analysis,
                source_path=str(stack.source_path),
                threshold=request.threshold,
                roi=roi_payload(to_rect_roi(request.roi)),
                include_mesh=request.include_mesh,
                prefer_opencv=request.prefer_opencv,
            ),
            "rows": analysis_rows(analysis),
        }

    @app.post("/threshold")
    def threshold(request: ThresholdRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
            grayscale = apply_preview_roi(stack.grayscale, to_rect_roi(request.roi))
            value, method = suggest_threshold(grayscale, method=request.method)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return threshold_payload(str(stack.source_path), value, method)

    @app.post("/preview")
    def preview(request: PreviewRequest) -> dict[str, object]:
        try:
            stack = load_image_stack(request.path, voxel_override=to_voxel_size(request.voxel))
            grayscale = apply_preview_roi(stack.grayscale, to_rect_roi(request.roi))
            preview_image = render_segmentation_preview_png(
                grayscale,
                frame_index=request.frame_index,
                threshold=request.threshold,
                prefer_opencv=request.prefer_opencv,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return preview_payload(str(stack.source_path), preview_image)

    @app.post("/upload/inspect")
    def upload_inspect_stack(
        file: Annotated[UploadFile, File()],
        voxel_x_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_y_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_z_um: Annotated[float, Form(gt=0)] = 1.0,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            stack = load_image_stack(
                temp_path,
                voxel_override=VoxelSize(voxel_x_um, voxel_y_um, voxel_z_um),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return {
            "source_path": file.filename or str(temp_path.name),
            "grayscale_shape": list(stack.grayscale.shape),
            "color_shape": list(stack.color.shape),
            "voxel_size": voxel_payload(stack.voxel_size),
        }

    @app.post("/upload/analyze")
    def upload_analyze(
        file: Annotated[UploadFile, File()],
        threshold: Annotated[float, Form()],
        profile: Annotated[str, Form()] = DEFAULT_PROFILE,
        voxel_x_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_y_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_z_um: Annotated[float, Form(gt=0)] = 1.0,
        include_mesh: Annotated[bool, Form()] = False,
        prefer_opencv: Annotated[bool, Form()] = True,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            stack = load_image_stack(
                temp_path,
                voxel_override=VoxelSize(voxel_x_um, voxel_y_um, voxel_z_um),
            )
            analysis = analyze_stack(
                stack.grayscale,
                thresholds=threshold,
                voxel_size=stack.voxel_size,
                roi=roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax),
                profile=profile,
                prefer_opencv=prefer_opencv,
                include_mesh=include_mesh,
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
            }
        return {
            "source_path": file.filename or str(temp_path.name),
            "profile": analysis.profile,
            "frame_count": len(analysis.frames),
            "valid_frame_count": len(analysis.valid_frames),
            "voxel_size": voxel_payload(stack.voxel_size),
            "mesh": mesh,
            "summary": analysis_summary(analysis),
            "warnings": analysis_warnings(analysis),
            "manifest": analysis_manifest(
                analysis,
                source_path=file.filename or str(temp_path.name),
                threshold=threshold,
                roi=roi_payload(roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax)),
                include_mesh=include_mesh,
                prefer_opencv=prefer_opencv,
            ),
            "rows": analysis_rows(analysis),
        }

    @app.post("/upload/preview")
    def upload_preview(
        file: Annotated[UploadFile, File()],
        threshold: Annotated[float, Form()],
        frame_index: Annotated[int, Form(ge=0)] = 0,
        voxel_x_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_y_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_z_um: Annotated[float, Form(gt=0)] = 1.0,
        prefer_opencv: Annotated[bool, Form()] = True,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            stack = load_image_stack(
                temp_path,
                voxel_override=VoxelSize(voxel_x_um, voxel_y_um, voxel_z_um),
            )
            grayscale = apply_preview_roi(
                stack.grayscale,
                roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax),
            )
            preview_image = render_segmentation_preview_png(
                grayscale,
                frame_index=frame_index,
                threshold=threshold,
                prefer_opencv=prefer_opencv,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return preview_payload(file.filename or str(temp_path.name), preview_image)

    @app.post("/upload/threshold")
    def upload_threshold(
        file: Annotated[UploadFile, File()],
        method: Annotated[str, Form()] = "auto",
        voxel_x_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_y_um: Annotated[float, Form(gt=0)] = 1.0,
        voxel_z_um: Annotated[float, Form(gt=0)] = 1.0,
        roi_xmin: Annotated[int | None, Form()] = None,
        roi_xmax: Annotated[int | None, Form()] = None,
        roi_ymin: Annotated[int | None, Form()] = None,
        roi_ymax: Annotated[int | None, Form()] = None,
    ) -> dict[str, object]:
        temp_path = save_upload_to_temp(file)
        try:
            stack = load_image_stack(
                temp_path,
                voxel_override=VoxelSize(voxel_x_um, voxel_y_um, voxel_z_um),
            )
            grayscale = apply_preview_roi(
                stack.grayscale,
                roi_from_optional_bounds(roi_xmin, roi_xmax, roi_ymin, roi_ymax),
            )
            value, used_method = suggest_threshold(grayscale, method=method)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)

        return threshold_payload(file.filename or str(temp_path.name), value, used_method)

    return app


def to_voxel_size(voxel: VoxelOverride | None) -> VoxelSize | None:
    if voxel is None:
        return None
    return VoxelSize(voxel.x_um, voxel.y_um, voxel.z_um)


def to_rect_roi(roi: ROIRequest | None) -> RectROI | None:
    if roi is None:
        return None
    return RectROI(roi.xmin, roi.xmax, roi.ymin, roi.ymax)


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


def roi_payload(roi: RectROI | None) -> dict[str, int] | None:
    if roi is None:
        return None
    return {"xmin": roi.xmin, "xmax": roi.xmax, "ymin": roi.ymin, "ymax": roi.ymax}


def apply_preview_roi(stack, roi: RectROI | None):
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


def threshold_payload(source_path: str, threshold: float, method: str) -> dict[str, object]:
    return {"source_path": source_path, "threshold": threshold, "method": method}


def voxel_payload(voxel: VoxelSize) -> dict[str, float]:
    return {"x_um": voxel.x_um, "y_um": voxel.y_um, "z_um": voxel.z_um}


app = create_app()
