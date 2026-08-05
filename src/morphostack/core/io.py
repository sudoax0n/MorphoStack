"""Non-interactive microscopy file loading."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from morphostack.core.images import as_color_stack, as_grayscale_stack, color_stub_for_grayscale
from morphostack.core.models import ImageStack, VoxelSize
from morphostack.core.rbc_models import CalibrationAssessment, CalibrationAxis

SUPPORTED_EXTENSIONS = {".tif", ".tiff", ".lsm", ".czi"}
DEFAULT_VOXEL_SIZE = VoxelSize(x_um=1.0, y_um=1.0, z_um=1.0)


def _source_format_for_path(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    name = file_path.name.lower()
    if name.endswith(".ome.tif") or name.endswith(".ome.tiff"):
        return "ome-tiff"
    if suffix == ".lsm":
        return "lsm"
    if suffix in {".tif", ".tiff"}:
        return "tiff"
    if suffix == ".czi":
        return "czi"
    return suffix.lstrip(".") or "unknown"


def _effective_voxel_from_axes(
    x: CalibrationAxis,
    y: CalibrationAxis,
    z: CalibrationAxis,
) -> VoxelSize:
    """Legacy VoxelSize: keep positive placeholders for display/compat paths."""

    return VoxelSize(
        x_um=float(x.value_um) if x.value_um is not None else DEFAULT_VOXEL_SIZE.x_um,
        y_um=float(y.value_um) if y.value_um is not None else DEFAULT_VOXEL_SIZE.y_um,
        z_um=float(z.value_um) if z.value_um is not None else DEFAULT_VOXEL_SIZE.z_um,
    )


def _override_calibration(voxel: VoxelSize, *, source_format: str) -> CalibrationAssessment:
    return CalibrationAssessment(
        x=CalibrationAxis(float(voxel.x_um), "override", True),
        y=CalibrationAxis(float(voxel.y_um), "override", True),
        z=CalibrationAxis(float(voxel.z_um), "override", True),
        source_format=source_format,
    )


def _default_calibration(*, source_format: str) -> CalibrationAssessment:
    return CalibrationAssessment(
        x=CalibrationAxis(DEFAULT_VOXEL_SIZE.x_um, "default", False),
        y=CalibrationAxis(DEFAULT_VOXEL_SIZE.y_um, "default", False),
        z=CalibrationAxis(DEFAULT_VOXEL_SIZE.z_um, "default", False),
        source_format=source_format,
    )


def _resolve_voxel_and_calibration(
    detected: CalibrationAssessment | None,
    voxel_override: VoxelSize | None,
    *,
    source_format: str,
) -> tuple[VoxelSize, str, CalibrationAssessment]:
    if voxel_override is not None:
        calibration = _override_calibration(voxel_override, source_format=source_format)
        return voxel_override, "override", calibration
    if detected is not None:
        voxel = _effective_voxel_from_axes(detected.x, detected.y, detected.z)
        return voxel, "metadata", detected
    calibration = _default_calibration(source_format=source_format)
    return DEFAULT_VOXEL_SIZE, "default", calibration


def load_image_stack(
    path: str | Path,
    *,
    voxel_override: VoxelSize | None = None,
    include_color: bool = False,
) -> ImageStack:
    """Load a TIFF/TIFF-like or CZI file without GUI prompts.

    ``include_color`` defaults to False: analysis/session/cache paths only need
    grayscale, and a full RGB copy roughly triples RAM on large stacks. Pass
    True only when real multichannel color pixels are required.
    """

    file_path = Path(path)
    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported image format {ext!r}; expected one of {supported}")

    source_format = _source_format_for_path(file_path)
    if ext in {".tif", ".tiff", ".lsm"}:
        raw, detected_axes = read_tiff_axes(file_path, source_format=source_format)
    else:
        raw, detected_axes = read_czi_axes(file_path, source_format=source_format)

    voxel, voxel_source, calibration = _resolve_voxel_and_calibration(
        detected_axes,
        voxel_override,
        source_format=source_format,
    )
    grayscale = as_grayscale_stack(raw)
    if include_color:
        color = as_color_stack(raw)
    else:
        color = color_stub_for_grayscale(grayscale)
    return ImageStack(
        source_path=file_path,
        grayscale=grayscale,
        color=color,
        voxel_size=voxel,
        voxel_source=voxel_source,
        calibration=calibration,
    )


def file_sha256(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest for a source file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tiff(path: Path) -> tuple[np.ndarray, VoxelSize | None]:
    image, axes = read_tiff_axes(path, source_format=_source_format_for_path(path))
    if axes is None:
        return image, None
    return image, _effective_voxel_from_axes(axes.x, axes.y, axes.z)


def read_tiff_axes(
    path: Path,
    *,
    source_format: str | None = None,
) -> tuple[np.ndarray, CalibrationAssessment | None]:
    try:
        import tifffile
    except Exception as exc:  # pragma: no cover - dependency-specific branch
        raise RuntimeError("tifffile is required to load TIFF files") from exc

    fmt = source_format or _source_format_for_path(path)
    with tifffile.TiffFile(path) as tif:
        image = tif.asarray()
        axes = calibration_from_tiff(tif, source_format=fmt)
    return image, axes


def read_czi(path: Path) -> tuple[np.ndarray, VoxelSize | None]:
    image, axes = read_czi_axes(path, source_format=_source_format_for_path(path))
    if axes is None:
        return image, None
    return image, _effective_voxel_from_axes(axes.x, axes.y, axes.z)


def read_czi_axes(
    path: Path,
    *,
    source_format: str | None = None,
) -> tuple[np.ndarray, CalibrationAssessment | None]:
    try:
        import czifile
    except Exception as exc:  # pragma: no cover - dependency-specific branch
        raise RuntimeError("czifile is required to load CZI files") from exc

    fmt = source_format or _source_format_for_path(path)
    with czifile.CziFile(path) as czi:
        image = czi.asarray()
        axes = calibration_from_czi_metadata(czi.metadata(), source_format=fmt)
    return image, axes

def resolution_unit_um_scale(tag: Any) -> float | None:
    """TIFF ResolutionUnit → micrometres per resolution unit.

    TIFF 6.0: 1 = none, 2 = inch, 3 = centimetre. Absent/none keeps legacy
    behaviour (treat 1/resolution as already-µm).
    """
    if tag is None:
        return None
    value = getattr(tag, "value", tag)
    try:
        unit = int(value)
    except Exception:
        return None
    if unit == 2:  # inch
        return 25_400.0
    if unit == 3:  # centimetre
        return 10_000.0
    # 1 = no absolute unit, or unknown → preserve pre-fix µm interpretation
    return None


def calibration_from_tiff(tif: Any, *, source_format: str = "tiff") -> CalibrationAssessment | None:
    """Parse TIFF tags into per-axis calibration; None if no axis metadata found."""

    if not getattr(tif, "pages", None):
        return None

    first_page = tif.pages[0]
    tags = getattr(first_page, "tags", {})
    unit_scale = resolution_unit_um_scale(tags.get("ResolutionUnit"))
    x_um = resolution_tag_to_um(tags.get("XResolution"), unit_um_per_res_unit=unit_scale)
    y_um = resolution_tag_to_um(tags.get("YResolution"), unit_um_per_res_unit=unit_scale)
    z_um = image_description_spacing_um(tags.get("ImageDescription"))

    x_source = "metadata" if x_um is not None else None
    y_source = "metadata" if y_um is not None else None
    # Mirror single XY axis like CZI / Fiji / Bio-Formats (do not invent 1.0 µm).
    if x_um is not None and y_um is None:
        y_um = x_um
        y_source = "mirrored"
    elif y_um is not None and x_um is None:
        x_um = y_um
        x_source = "mirrored"

    if x_um is None and y_um is None and z_um is None:
        return None

    # Placeholder-filled axes keep legacy VoxelSize display values but stay unverified.
    x_axis = (
        CalibrationAxis(float(x_um), x_source, True)
        if x_um is not None and x_source is not None
        else CalibrationAxis(DEFAULT_VOXEL_SIZE.x_um, "placeholder", False)
    )
    y_axis = (
        CalibrationAxis(float(y_um), y_source, True)
        if y_um is not None and y_source is not None
        else CalibrationAxis(DEFAULT_VOXEL_SIZE.y_um, "placeholder", False)
    )
    z_axis = (
        CalibrationAxis(float(z_um), "metadata", True)
        if z_um is not None
        else CalibrationAxis(DEFAULT_VOXEL_SIZE.z_um, "placeholder", False)
    )
    return CalibrationAssessment(x=x_axis, y=y_axis, z=z_axis, source_format=source_format)


def voxel_from_tiff(tif: Any) -> VoxelSize | None:
    axes = calibration_from_tiff(tif)
    if axes is None:
        return None
    return _effective_voxel_from_axes(axes.x, axes.y, axes.z)


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


def calibration_from_czi_metadata(
    metadata: Any,
    *,
    source_format: str = "czi",
) -> CalibrationAssessment | None:
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

    x_source = "metadata" if x is not None else None
    y_source = "metadata" if y is not None else None
    # If only one of X or Y is found, mirror the other (mirroring Fiji/Bio-Formats)
    if x is not None and y is None:
        y = x
        y_source = "mirrored"
    elif y is not None and x is None:
        x = y
        x_source = "mirrored"

    x_um = metadata_value_to_um(x)
    y_um = metadata_value_to_um(y)
    z_um = metadata_value_to_um(z)

    if x_um is None and y_um is None and z_um is None:
        return None

    x_axis = (
        CalibrationAxis(float(x_um), x_source or "metadata", True)
        if x_um is not None
        else CalibrationAxis(DEFAULT_VOXEL_SIZE.x_um, "placeholder", False)
    )
    y_axis = (
        CalibrationAxis(float(y_um), y_source or "metadata", True)
        if y_um is not None
        else CalibrationAxis(DEFAULT_VOXEL_SIZE.y_um, "placeholder", False)
    )
    z_axis = (
        CalibrationAxis(float(z_um), "metadata", True)
        if z_um is not None
        else CalibrationAxis(DEFAULT_VOXEL_SIZE.z_um, "placeholder", False)
    )
    return CalibrationAssessment(x=x_axis, y=y_axis, z=z_axis, source_format=source_format)


def voxel_from_czi_metadata(metadata: Any) -> VoxelSize | None:
    axes = calibration_from_czi_metadata(metadata)
    if axes is None:
        return None
    return _effective_voxel_from_axes(axes.x, axes.y, axes.z)


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


def resolution_tag_to_um(
    tag: Any,
    *,
    unit_um_per_res_unit: float | None = None,
) -> float | None:
    """Convert TIFF XResolution/YResolution to micrometres per pixel.

    Tags are pixels-per-unit. When ``unit_um_per_res_unit`` is set (from
    ResolutionUnit inch/cm), scale into µm; when None, keep legacy behaviour
    that treats the reciprocal as already-µm (unit absent/none).
    """
    if tag is None:
        return None
    value = getattr(tag, "value", tag)
    try:
        numerator, denominator = value
        if float(numerator) == 0:
            return None
        pixels_per_unit = float(numerator) / float(denominator)
        if pixels_per_unit == 0:
            return None
        size_in_unit = 1.0 / pixels_per_unit
        if unit_um_per_res_unit is not None:
            return size_in_unit * float(unit_um_per_res_unit)
        return size_in_unit
    except Exception:
        return None


# ImageJ ImageDescription unit= token → multiply spacing by this to get µm.
# Unknown explicit units return None from image_description_spacing_um (no guess).
_IMAGEJ_UNIT_TO_UM: dict[str, float] = {
    "nm": 1e-3,
    "nanometer": 1e-3,
    "nanometre": 1e-3,
    "um": 1.0,
    "µm": 1.0,
    "micron": 1.0,
    "microns": 1.0,
    "micrometer": 1.0,
    "micrometre": 1.0,
    "micrometers": 1.0,
    "micrometres": 1.0,
    "mm": 1e3,
    "millimeter": 1e3,
    "millimetre": 1e3,
}


def imagej_unit_to_um_factor(unit: str) -> float | None:
    """Return scale from ImageJ unit token to µm, or None if unknown."""
    key = unit.strip().lower()
    # Normalize unicode micro sign variants already lowercased as µm in table.
    if key in _IMAGEJ_UNIT_TO_UM:
        return _IMAGEJ_UNIT_TO_UM[key]
    # Bare "u" sometimes used for micron
    if key == "u":
        return 1.0
    return None


def image_description_spacing_um(tag: Any) -> float | None:
    """Parse ImageJ spacing= (and optional unit=) into z spacing in µm.

    Without unit=, keep legacy behaviour (value already treated as µm).
    With a known unit, convert. With an unknown explicit unit, return None
    rather than guessing.
    """
    if tag is None:
        return None
    description = str(getattr(tag, "value", tag))
    match = re.search(r"spacing\s*=\s*([0-9.eE+-]+)", description, re.IGNORECASE)
    if not match:
        return None
    try:
        spacing = float(match.group(1))
    except ValueError:
        return None
    unit_match = re.search(r"unit\s*=\s*([^\s\r\n]+)", description, re.IGNORECASE)
    if not unit_match:
        return spacing
    factor = imagej_unit_to_um_factor(unit_match.group(1))
    if factor is None:
        return None
    return spacing * factor


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


def open_volume_source(
    path: str | Path,
    *,
    voxel_override: VoxelSize | None = None,
    register: bool = True,
):
    """Open a path-backed :class:`~morphostack.core.volume_source.VolumeSource`.

    Thin adapter over the volume-source module so I/O entry points stay in
    ``io`` while reader lifecycle lives in ``volume_source``.
    """

    from morphostack.core.volume_source import open_volume_source as _open

    return _open(path, voxel_override=voxel_override, register=register)


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

    source_format = _source_format_for_path(file_path)
    if ext in {".tif", ".tiff", ".lsm"}:
        try:
            import tifffile
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("tifffile is required to load TIFF files") from exc

        with tifffile.TiffFile(file_path) as tif:
            detected_axes = calibration_from_tiff(tif, source_format=source_format)
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
            detected_axes = calibration_from_czi_metadata(czi.metadata(), source_format=source_format)
            raw_shape = czi.shape

    voxel, voxel_source, calibration = _resolve_voxel_and_calibration(
        detected_axes,
        voxel_override,
        source_format=source_format,
    )

    g_shape, c_shape = standardize_shapes(raw_shape)
    return {
        "source_path": file_path,
        "grayscale_shape": g_shape,
        "color_shape": c_shape,
        "voxel_size": voxel,
        "voxel_source": voxel_source,
        "calibration": calibration,
    }

