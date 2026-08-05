from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from morphostack.core import ImageStack, VoxelSize, file_sha256, load_image_stack
from morphostack.core import io


@dataclass
class FakeTag:
    value: object


class FakePage:
    def __init__(self, tags: dict[str, object]):
        self.tags = tags


class FakeTiff:
    def __init__(self, tags: dict[str, object]):
        self.pages = [FakePage(tags)]


def test_load_image_stack_rejects_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported image format"):
        load_image_stack("sample.png")


def test_load_image_stack_uses_override_before_detected_metadata(monkeypatch):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    from morphostack.core.rbc_models import CalibrationAssessment, CalibrationAxis

    detected = CalibrationAssessment(
        x=CalibrationAxis(9.0, "metadata", True),
        y=CalibrationAxis(9.0, "metadata", True),
        z=CalibrationAxis(9.0, "metadata", True),
        source_format="tiff",
    )
    override = VoxelSize(x_um=0.1, y_um=0.2, z_um=0.3)

    monkeypatch.setattr(io, "read_tiff_axes", lambda path, source_format=None: (raw, detected))
    loaded = load_image_stack("sample.tif", voxel_override=override)

    assert loaded.source_path == Path("sample.tif")
    assert loaded.voxel_size == override
    assert loaded.voxel_source == "override"
    assert loaded.calibration.all_axes_from_override
    assert loaded.grayscale.shape == (1, 4, 4)
    assert loaded.color.shape == (1, 4, 4, 3)


def test_load_image_stack_skips_full_color_by_default(monkeypatch):
    """Default include_color=False avoids tripling RAM; shape still reports RGB."""
    # Use width != 3/4 so grayscale loader does not treat last axis as RGB/RGBA.
    raw = np.arange(2 * 8 * 8, dtype=np.uint8).reshape(2, 8, 8)
    monkeypatch.setattr(io, "read_tiff_axes", lambda path, source_format=None: (raw, None))

    loaded = load_image_stack("sample.tif")
    assert loaded.grayscale.shape == (2, 8, 8)
    assert loaded.color.shape == (2, 8, 8, 3)
    # Broadcast stub reuses a scalar base (no owned multi-channel pixel buffer).
    assert not loaded.color.flags["OWNDATA"]
    assert 0 in loaded.color.strides

    full = load_image_stack("sample.tif", include_color=True)
    assert full.color.shape == (2, 8, 8, 3)
    # Real grayscale→RGB expansion materializes channel data.
    assert full.color.strides[-1] == full.color.dtype.itemsize
    assert full.color.flags["C_CONTIGUOUS"]


def test_load_image_stack_uses_default_voxel_when_metadata_missing(monkeypatch):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    monkeypatch.setattr(io, "read_tiff_axes", lambda path, source_format=None: (raw, None))

    loaded = load_image_stack("sample.tiff")

    assert loaded.voxel_size == io.DEFAULT_VOXEL_SIZE
    assert loaded.voxel_source == "default"
    assert not loaded.calibration.all_axes_verified


def test_load_image_stack_reads_lsm_as_tiff_like(monkeypatch):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    monkeypatch.setattr(io, "read_tiff_axes", lambda path, source_format=None: (raw, None))

    loaded = load_image_stack("sample.lsm")

    assert loaded.source_path == Path("sample.lsm")
    assert loaded.grayscale.shape == (1, 4, 4)
    assert loaded.voxel_source == "default"
    assert loaded.calibration.source_format == "lsm"


def test_load_image_stack_records_metadata_voxel_source(monkeypatch):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    from morphostack.core.rbc_models import CalibrationAssessment, CalibrationAxis

    detected = CalibrationAssessment(
        x=CalibrationAxis(0.5, "metadata", True),
        y=CalibrationAxis(0.5, "metadata", True),
        z=CalibrationAxis(2.0, "metadata", True),
        source_format="tiff",
    )
    monkeypatch.setattr(io, "read_tiff_axes", lambda path, source_format=None: (raw, detected))

    loaded = load_image_stack("sample.tif")

    assert loaded.voxel_size == VoxelSize(x_um=0.5, y_um=0.5, z_um=2.0)
    assert loaded.voxel_source == "metadata"
    assert loaded.calibration.all_axes_verified


def test_file_sha256_hashes_file_bytes(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"morphostack")

    assert file_sha256(path) == "25217bc4395b2cfca282576d6dbcbac64e6b5f08c32a25c67b6e34868d3aa8d4"


def test_tiff_metadata_parses_resolution_and_spacing():
    tif = FakeTiff(
        {
            "XResolution": FakeTag((2, 1)),
            "YResolution": FakeTag((4, 1)),
            "ImageDescription": FakeTag("spacing=1.5 unit=micron"),
        }
    )

    voxel = io.voxel_from_tiff(tif)

    assert voxel == VoxelSize(x_um=0.5, y_um=0.25, z_um=1.5)


def test_czi_metadata_parses_meter_scaling_to_micrometers():
    metadata = """
    <ScalingX>2.5e-7</ScalingX>
    <ScalingY>3.0e-7</ScalingY>
    <ScalingZ>1.1e-6</ScalingZ>
    """

    voxel = io.voxel_from_czi_metadata(metadata)

    assert voxel == VoxelSize(x_um=0.25, y_um=0.3, z_um=1.1)


def test_image_stack_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="share z/y/x"):
        ImageStack(
            source_path=Path("bad.tif"),
            grayscale=np.zeros((1, 4, 4)),
            color=np.zeros((1, 5, 4, 3)),
            voxel_size=VoxelSize(1.0, 1.0, 1.0),
        )


def test_czi_metadata_parses_standard_distance_format():
    metadata = """
    <Scaling>
      <Items>
        <Distance Id="X">
          <Value>2.1921761326058251E-07</Value>
          <DefaultUnitFormat>µm</DefaultUnitFormat>
        </Distance>
        <Distance Id="Y">
          <Value>2.1921761326058251E-07</Value>
          <DefaultUnitFormat>µm</DefaultUnitFormat>
        </Distance>
        <Distance Id="Z">
          <Value>5E-07</Value>
          <DefaultUnitFormat>µm</DefaultUnitFormat>
        </Distance>
      </Items>
    </Scaling>
    """
    voxel = io.voxel_from_czi_metadata(metadata)
    assert voxel is not None
    assert pytest.approx(voxel.x_um) == 0.2192176
    assert pytest.approx(voxel.y_um) == 0.2192176
    assert pytest.approx(voxel.z_um) == 0.5


def test_czi_metadata_lateral_mirror_fallback():
    # Only X is present -> Y mirrors X
    metadata_x = """
    <Scaling>
      <Items>
        <Distance Id="X">
          <Value>2.5E-07</Value>
        </Distance>
      </Items>
    </Scaling>
    """
    voxel = io.voxel_from_czi_metadata(metadata_x)
    assert voxel is not None
    assert pytest.approx(voxel.x_um) == 0.25
    assert pytest.approx(voxel.y_um) == 0.25
    assert voxel.z_um == io.DEFAULT_VOXEL_SIZE.z_um

    # Only Y is present -> X mirrors Y
    metadata_y = """
    <Scaling>
      <Items>
        <Distance Id="Y">
          <Value>3.0E-07</Value>
        </Distance>
      </Items>
    </Scaling>
    """
    voxel2 = io.voxel_from_czi_metadata(metadata_y)
    assert voxel2 is not None
    assert pytest.approx(voxel2.x_um) == 0.3
    assert pytest.approx(voxel2.y_um) == 0.3
    assert voxel2.z_um == io.DEFAULT_VOXEL_SIZE.z_um


def test_inspect_image_stack_czi(tmp_path, monkeypatch):
    czi_file = tmp_path / "test.czi"
    czi_file.touch()

    # Mock czifile.CziFile
    class MockCziFile:
        def __init__(self, path):
            self.shape = (1, 1, 10, 50, 50, 1)
            self.axes = "TCZYX0"
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def metadata(self):
            return """
            <Scaling><Items>
              <Distance Id="X"><Value>1e-7</Value></Distance>
              <Distance Id="Y"><Value>1e-7</Value></Distance>
              <Distance Id="Z"><Value>1e-6</Value></Distance>
            </Items></Scaling>
            """

    import sys
    from types import ModuleType
    mock_czi = ModuleType("czifile")
    mock_czi.CziFile = MockCziFile
    monkeypatch.setitem(sys.modules, "czifile", mock_czi)

    info = io.inspect_image_stack(czi_file)
    assert info["source_path"] == czi_file
    assert info["grayscale_shape"] == (10, 50, 50)
    assert info["color_shape"] == (10, 50, 50, 3)
    assert pytest.approx(info["voxel_size"].x_um) == 0.1
    assert pytest.approx(info["voxel_size"].y_um) == 0.1
    assert pytest.approx(info["voxel_size"].z_um) == 1.0
    assert info["voxel_source"] == "metadata"


def test_inspect_image_stack_tiff(tmp_path, monkeypatch):
    tiff_file = tmp_path / "test.tif"
    tiff_file.touch()

    class MockTiffSeries:
        def __init__(self):
            self.shape = (5, 60, 60)

    class MockTiffFile:
        def __init__(self, path):
            self.series = [MockTiffSeries()]
            self.pages = []
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    import sys
    from types import ModuleType
    from morphostack.core.rbc_models import CalibrationAssessment, CalibrationAxis

    mock_tiff = ModuleType("tifffile")
    mock_tiff.TiffFile = MockTiffFile
    monkeypatch.setitem(sys.modules, "tifffile", mock_tiff)
    monkeypatch.setattr(
        io,
        "calibration_from_tiff",
        lambda tif, source_format="tiff": CalibrationAssessment(
            x=CalibrationAxis(0.5, "metadata", True),
            y=CalibrationAxis(0.5, "metadata", True),
            z=CalibrationAxis(2.0, "metadata", True),
            source_format=source_format,
        ),
    )

    info = io.inspect_image_stack(tiff_file)
    assert info["source_path"] == tiff_file
    assert info["grayscale_shape"] == (5, 60, 60)
    assert info["color_shape"] == (5, 60, 60, 3)
    assert info["voxel_size"] == VoxelSize(0.5, 0.5, 2.0)
    assert info["voxel_source"] == "metadata"
    assert info["calibration"].all_axes_verified


def test_parse_czi_xml_metadata():
    # Namespaced CZI metadata XML
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
    <ImageDocument xmlns="http://www.zeiss.com/METADATA">
      <Metadata>
        <Scaling>
          <Items>
            <Distance Id="X">
              <Value>2.5e-7</Value>
            </Distance>
            <Distance Id="Y">
              <Value>2.5e-7</Value>
            </Distance>
            <Distance Id="Z">
              <Value>1.2e-6</Value>
            </Distance>
          </Items>
        </Scaling>
      </Metadata>
    </ImageDocument>
    """
    voxels = io.parse_czi_xml_metadata(xml_content)
    assert pytest.approx(voxels["X"]) == 2.5e-7
    assert pytest.approx(voxels["Y"]) == 2.5e-7
    assert pytest.approx(voxels["Z"]) == 1.2e-6

    # Test old ScalingX format parsing via XML
    old_xml = """
    <root>
      <ScalingX>1.5e-7</ScalingX>
      <ScalingY>1.5e-7</ScalingY>
      <ScalingZ>8.0e-7</ScalingZ>
    </root>
    """
    voxels_old = io.parse_czi_xml_metadata(old_xml)
    assert pytest.approx(voxels_old["X"]) == 1.5e-7
    assert pytest.approx(voxels_old["Y"]) == 1.5e-7
    assert pytest.approx(voxels_old["Z"]) == 8.0e-7

    # Malformed XML handles gracefully
    bad_xml = "<invalid><Distance Id='X'><Value>1.23</Value>"
    assert io.parse_czi_xml_metadata(bad_xml) == {}


def test_standardize_shapes_unsupported():
    # Unsupported 4D shapes
    with pytest.raises(ValueError, match="Unsupported image stack shape"):
        io.standardize_shapes((10, 5, 256, 256)) # 5 channels (not 3 or 4)

    # 5D shape
    with pytest.raises(ValueError, match="Unsupported image stack shape"):
        io.standardize_shapes((2, 2, 2, 2, 2))


def test_tiff_resolution_unit_cm_scales_to_micrometers():
    # 2 pixels per cm => 0.5 cm/pixel => 5000 um/pixel
    tif = FakeTiff(
        {
            "XResolution": FakeTag((2, 1)),
            "YResolution": FakeTag((2, 1)),
            "ResolutionUnit": FakeTag(3),
        }
    )
    voxel = io.voxel_from_tiff(tif)
    assert voxel == VoxelSize(x_um=5000.0, y_um=5000.0, z_um=1.0)
    axes = io.calibration_from_tiff(tif)
    assert axes is not None
    assert axes.x.verified and axes.y.verified
    assert not axes.z.verified
    assert axes.z.source == "placeholder"


def test_tiff_resolution_unit_inch_scales_to_micrometers():
    # 1 pixel per inch => 25400 um/pixel
    tif = FakeTiff(
        {
            "XResolution": FakeTag((1, 1)),
            "YResolution": FakeTag((1, 1)),
            "ResolutionUnit": FakeTag(2),
        }
    )
    voxel = io.voxel_from_tiff(tif)
    assert voxel == VoxelSize(x_um=25400.0, y_um=25400.0, z_um=1.0)


def test_tiff_missing_resolution_unit_keeps_legacy_um_behavior():
    # No ResolutionUnit: reciprocal of pixels-per-unit treated as um (pinned legacy).
    tif = FakeTiff(
        {
            "XResolution": FakeTag((2, 1)),
            "YResolution": FakeTag((4, 1)),
        }
    )
    voxel = io.voxel_from_tiff(tif)
    assert voxel == VoxelSize(x_um=0.5, y_um=0.25, z_um=1.0)


def test_tiff_single_axis_resolution_mirrors_other():
    tif = FakeTiff({"XResolution": FakeTag((2, 1))})
    voxel = io.voxel_from_tiff(tif)
    assert voxel == VoxelSize(x_um=0.5, y_um=0.5, z_um=1.0)

    tif_y = FakeTiff({"YResolution": FakeTag((4, 1))})
    voxel_y = io.voxel_from_tiff(tif_y)
    assert voxel_y == VoxelSize(x_um=0.25, y_um=0.25, z_um=1.0)


def test_image_description_spacing_unit_nm_mm_um():
    assert io.image_description_spacing_um(FakeTag("spacing=500.0 unit=nm")) == pytest.approx(0.5)
    assert io.image_description_spacing_um(FakeTag("spacing=0.5 unit=mm")) == pytest.approx(500.0)
    assert io.image_description_spacing_um(FakeTag("spacing=1.5 unit=um")) == pytest.approx(1.5)
    assert io.image_description_spacing_um(FakeTag("spacing=1.5 unit=\u00b5m")) == pytest.approx(1.5)
    assert io.image_description_spacing_um(FakeTag("spacing=2.0 unit=micron")) == pytest.approx(2.0)
    # No unit= keeps legacy um interpretation
    assert io.image_description_spacing_um(FakeTag("spacing=1.5")) == pytest.approx(1.5)
    # Unknown explicit unit must not be guessed
    assert io.image_description_spacing_um(FakeTag("spacing=1.5 unit=furlong")) is None


def test_tiff_imagej_nm_spacing_with_xy_resolution():
    tif = FakeTiff(
        {
            "XResolution": FakeTag((2, 1)),
            "YResolution": FakeTag((2, 1)),
            "ImageDescription": FakeTag("ImageJ=1.53 spacing=500.0 unit=nm"),
        }
    )
    voxel = io.voxel_from_tiff(tif)
    assert voxel == VoxelSize(x_um=0.5, y_um=0.5, z_um=0.5)
