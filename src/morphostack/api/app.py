"""FastAPI application for the local MorphoStack backend."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException
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

    return app


def to_voxel_size(voxel: VoxelOverride | None) -> VoxelSize | None:
    if voxel is None:
        return None
    return VoxelSize(voxel.x_um, voxel.y_um, voxel.z_um)


def to_rect_roi(roi: ROIRequest | None) -> RectROI | None:
    if roi is None:
        return None
    return RectROI(roi.xmin, roi.xmax, roi.ymin, roi.ymax)


def voxel_payload(voxel: VoxelSize) -> dict[str, float]:
    return {"x_um": voxel.x_um, "y_um": voxel.y_um, "z_um": voxel.z_um}


app = create_app()
