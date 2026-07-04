"""FastAPI application for the local MorphoStack backend."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from morphostack import __version__
from morphostack.core import RectROI, VoxelSize, analyze_stack, load_image_stack
from morphostack.core.export import analysis_rows


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
    voxel: VoxelOverride | None = None
    roi: ROIRequest | None = None
    include_mesh: bool = False
    prefer_opencv: bool = True


def create_app() -> FastAPI:
    app = FastAPI(title="MorphoStack API", version=__version__)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__}

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
            "frame_count": len(analysis.frames),
            "valid_frame_count": len(analysis.valid_frames),
            "voxel_size": voxel_payload(stack.voxel_size),
            "mesh": mesh,
            "rows": analysis_rows(analysis),
        }

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
            "frame_count": len(analysis.frames),
            "valid_frame_count": len(analysis.valid_frames),
            "voxel_size": voxel_payload(stack.voxel_size),
            "mesh": mesh,
            "rows": analysis_rows(analysis),
        }

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


def voxel_payload(voxel: VoxelSize) -> dict[str, float]:
    return {"x_um": voxel.x_um, "y_um": voxel.y_um, "z_um": voxel.z_um}


app = create_app()
