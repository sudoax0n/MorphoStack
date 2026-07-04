"""Non-interactive microscopy file loading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from morphostack.core.images import as_color_stack, as_grayscale_stack
from morphostack.core.models import ImageStack, VoxelSize

SUPPORTED_EXTENSIONS = {".tif", ".tiff", ".czi"}
DEFAULT_VOXEL_SIZE = VoxelSize(x_um=1.0, y_um=1.0, z_um=1.0)


def load_image_stack(
    path: str | Path,
    *,
    voxel_override: VoxelSize | None = None,
) -> ImageStack:
    """Load a TIFF/TIFF-like or CZI file without GUI prompts."""

    file_path = Path(path)
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported image format {ext!r}; expected one of {supported}")

    if ext in {".tif", ".tiff"}:
        raw, detected = read_tiff(file_path)
    else:
        raw, detected = read_czi(file_path)

    voxel = voxel_override or detected or DEFAULT_VOXEL_SIZE
    return ImageStack(
        source_path=file_path,
        grayscale=as_grayscale_stack(raw),
        color=as_color_stack(raw),
        voxel_size=voxel,
    )


def read_tiff(path: Path) -> tuple[np.ndarray, VoxelSize | None]:
    try:
        import tifffile
    except Exception as exc:  # pragma: no cover - dependency-specific branch
        raise RuntimeError("tifffile is required to load TIFF files") from exc

    with tifffile.TiffFile(path) as tif:
        image = tif.asarray()
        voxel = voxel_from_tiff(tif)
    return image, voxel


def read_czi(path: Path) -> tuple[np.ndarray, VoxelSize | None]:
    try:
        import czifile
    except Exception as exc:  # pragma: no cover - dependency-specific branch
        raise RuntimeError("czifile is required to load CZI files") from exc

    with czifile.CziFile(path) as czi:
        image = czi.asarray()
        voxel = voxel_from_czi_metadata(czi.metadata())
    return image, voxel


def voxel_from_tiff(tif: Any) -> VoxelSize | None:
    if not getattr(tif, "pages", None):
        return None

    first_page = tif.pages[0]
    tags = getattr(first_page, "tags", {})
    x_um = resolution_tag_to_um(tags.get("XResolution"))
    y_um = resolution_tag_to_um(tags.get("YResolution"))
    z_um = image_description_spacing_um(tags.get("ImageDescription"))

    if x_um is None and y_um is None and z_um is None:
        return None

    return VoxelSize(
        x_um=x_um or DEFAULT_VOXEL_SIZE.x_um,
        y_um=y_um or DEFAULT_VOXEL_SIZE.y_um,
        z_um=z_um or DEFAULT_VOXEL_SIZE.z_um,
    )


def voxel_from_czi_metadata(metadata: Any) -> VoxelSize | None:
    text = str(metadata)
    x_um = metadata_value_to_um(find_metadata_number(text, "ScalingX"))
    y_um = metadata_value_to_um(find_metadata_number(text, "ScalingY"))
    z_um = metadata_value_to_um(find_metadata_number(text, "ScalingZ"))
    if x_um is None and y_um is None and z_um is None:
        return None
    return VoxelSize(
        x_um=x_um or DEFAULT_VOXEL_SIZE.x_um,
        y_um=y_um or DEFAULT_VOXEL_SIZE.y_um,
        z_um=z_um or DEFAULT_VOXEL_SIZE.z_um,
    )


def resolution_tag_to_um(tag: Any) -> float | None:
    if tag is None:
        return None
    value = getattr(tag, "value", tag)
    try:
        numerator, denominator = value
        if float(numerator) == 0:
            return None
        pixels_per_unit = float(numerator) / float(denominator)
        return 1.0 / pixels_per_unit
    except Exception:
        return None


def image_description_spacing_um(tag: Any) -> float | None:
    if tag is None:
        return None
    description = str(getattr(tag, "value", tag))
    match = re.search(r"spacing\s*=\s*([0-9.eE+-]+)", description)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def find_metadata_number(text: str, key: str) -> float | None:
    patterns = (
        rf"{re.escape(key)}[^0-9+\-.eE]+([0-9.eE+-]+)",
        rf"<[^>]*{re.escape(key)}[^>]*>\s*([0-9.eE+-]+)\s*</",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def metadata_value_to_um(value: float | None) -> float | None:
    """Convert metadata spacing to micrometers."""

    if value is None or value <= 0:
        return None
    if value < 0.001:
        return value * 1_000_000.0
    return value
