"""Non-interactive microscopy file loading."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from morphostack.core.images import as_color_stack, as_grayscale_stack
from morphostack.core.models import ImageStack, VoxelSize

SUPPORTED_EXTENSIONS = {".tif", ".tiff", ".lsm", ".czi"}
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

    if ext in {".tif", ".tiff", ".lsm"}:
        raw, detected = read_tiff(file_path)
    else:
        raw, detected = read_czi(file_path)

    if voxel_override is not None:
        voxel = voxel_override
        voxel_source = "override"
    elif detected is not None:
        voxel = detected
        voxel_source = "metadata"
    else:
        voxel = DEFAULT_VOXEL_SIZE
        voxel_source = "default"
    return ImageStack(
        source_path=file_path,
        grayscale=as_grayscale_stack(raw),
        color=as_color_stack(raw),
        voxel_size=voxel,
        voxel_source=voxel_source,
    )


def file_sha256(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest for a source file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def parse_czi_xml_metadata(metadata_str: str) -> dict[str, float]:
    result = {}
    if not metadata_str or not isinstance(metadata_str, str):
        return result
    
    try:
        clean_xml = metadata_str.strip()
        if not clean_xml:
            return result
        root = ET.fromstring(clean_xml)
    except Exception:
        try:
            root = ET.fromstring(f"<root>{metadata_str}</root>")
        except Exception:
            return result

    def traverse(node):
        tag_local = node.tag.split("}")[-1]
        if tag_local == "Distance":
            dist_id = node.attrib.get("Id")
            if dist_id in ("X", "Y", "Z"):
                for child in node:
                    child_tag_local = child.tag.split("}")[-1]
                    if child_tag_local == "Value" and child.text:
                        try:
                            result[dist_id] = float(child.text)
                        except ValueError:
                            pass
        elif tag_local in ("ScalingX", "ScalingY", "ScalingZ"):
            dim = tag_local[-1]
            if node.text:
                try:
                    result[dim] = float(node.text)
                except ValueError:
                    pass
                    
        for child in node:
            traverse(child)

    traverse(root)
    return result


def voxel_from_czi_metadata(metadata: Any) -> VoxelSize | None:
    text = str(metadata)
    
    # Try XML parsing first
    parsed_voxels = parse_czi_xml_metadata(text)
    x = parsed_voxels.get("X")
    y = parsed_voxels.get("Y")
    z = parsed_voxels.get("Z")

    # Fallback to regex-based find_czi_distance for backward/malformed compatibility
    if x is None:
        x = find_czi_distance(text, "X")
    if y is None:
        y = find_czi_distance(text, "Y")
    if z is None:
        z = find_czi_distance(text, "Z")

    # Fallback to old ScalingX/Y/Z format
    if x is None:
        x = find_metadata_number(text, "ScalingX")
    if y is None:
        y = find_metadata_number(text, "ScalingY")
    if z is None:
        z = find_metadata_number(text, "ScalingZ")

    # If only one of X or Y is found, mirror the other (mirroring Fiji/Bio-Formats)
    if x is not None and y is None:
        y = x
    elif y is not None and x is None:
        x = y

    x_um = metadata_value_to_um(x)
    y_um = metadata_value_to_um(y)
    z_um = metadata_value_to_um(z)

    if x_um is None and y_um is None and z_um is None:
        return None

    return VoxelSize(
        x_um=x_um or DEFAULT_VOXEL_SIZE.x_um,
        y_um=y_um or DEFAULT_VOXEL_SIZE.y_um,
        z_um=z_um or DEFAULT_VOXEL_SIZE.z_um,
    )


def find_czi_distance(text: str, dimension: str) -> float | None:
    """Extract value from <Distance Id="DIM"><Value>VAL</Value> tags."""
    pattern = rf"<Distance\s+[^>]*Id\s*=\s*['\"]{dimension}['\"][^>]*>.*?<Value>\s*([0-9.eE+-]+)\s*</Value>"
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


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


def standardize_shapes(raw_shape: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Determine grayscale and color stack shapes from raw array shape."""
    # Squeeze the shape using a zero-strided view to avoid memory allocation
    dummy = np.broadcast_to(np.zeros((1,), dtype=np.uint8), raw_shape)
    squeezed_shape = np.squeeze(dummy).shape

    if len(squeezed_shape) == 2:
        g_shape = (1, squeezed_shape[0], squeezed_shape[1])
        c_shape = (1, squeezed_shape[0], squeezed_shape[1], 3)
    elif len(squeezed_shape) == 3:
        if squeezed_shape[-1] in (3, 4):
            g_shape = (1, squeezed_shape[0], squeezed_shape[1])
            c_shape = (1, squeezed_shape[0], squeezed_shape[1], squeezed_shape[2])
        else:
            g_shape = squeezed_shape
            c_shape = squeezed_shape + (3,)
    elif len(squeezed_shape) == 4:
        if squeezed_shape[-1] in (3, 4):
            g_shape = squeezed_shape[:-1]
            c_shape = squeezed_shape
        elif squeezed_shape[1] in (3, 4):
            g_shape = (squeezed_shape[0], squeezed_shape[2], squeezed_shape[3])
            c_shape = (squeezed_shape[0], squeezed_shape[2], squeezed_shape[3], squeezed_shape[1])
        else:
            raise ValueError(f"Unsupported image stack shape: {squeezed_shape}")
    else:
        raise ValueError(f"Unsupported image stack shape: {squeezed_shape}")

    return g_shape, c_shape


def inspect_image_stack(
    path: str | Path,
    *,
    voxel_override: VoxelSize | None = None,
) -> dict[str, Any]:
    """Inspect image shape and metadata without loading all pixel data."""
    file_path = Path(path)
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported image format {ext!r}; expected one of {supported}")

    if ext in {".tif", ".tiff", ".lsm"}:
        try:
            import tifffile
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("tifffile is required to load TIFF files") from exc

        with tifffile.TiffFile(file_path) as tif:
            detected = voxel_from_tiff(tif)
            if tif.series:
                raw_shape = tif.series[0].shape
            elif tif.pages:
                raw_shape = tif.pages[0].shape
                if len(tif.pages) > 1:
                    raw_shape = (len(tif.pages),) + raw_shape
            else:
                raw_shape = tif.asarray().shape
    else:
        try:
            import czifile
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("czifile is required to load CZI files") from exc

        with czifile.CziFile(file_path) as czi:
            detected = voxel_from_czi_metadata(czi.metadata())
            raw_shape = czi.shape

    if voxel_override is not None:
        voxel = voxel_override
        voxel_source = "override"
    elif detected is not None:
        voxel = detected
        voxel_source = "metadata"
    else:
        voxel = DEFAULT_VOXEL_SIZE
        voxel_source = "default"

    g_shape, c_shape = standardize_shapes(raw_shape)
    return {
        "source_path": file_path,
        "grayscale_shape": g_shape,
        "color_shape": c_shape,
        "voxel_size": voxel,
        "voxel_source": voxel_source,
    }

