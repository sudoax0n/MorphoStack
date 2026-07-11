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
    detected = VoxelSize(x_um=9.0, y_um=9.0, z_um=9.0)
    override = VoxelSize(x_um=0.1, y_um=0.2, z_um=0.3)

    monkeypatch.setattr(io, "read_tiff", lambda _: (raw, detected))
    loaded = load_image_stack("sample.tif", voxel_override=override)

    assert loaded.source_path == Path("sample.tif")
    assert loaded.voxel_size == override
    assert loaded.voxel_source == "override"
    assert loaded.grayscale.shape == (1, 4, 4)
    assert loaded.color.shape == (1, 4, 4, 3)


def test_load_image_stack_skips_full_color_by_default(monkeypatch):
    """Default include_color=False avoids tripling RAM; shape still reports RGB."""
    # Use width != 3/4 so grayscale loader does not treat last axis as RGB/RGBA.
    raw = np.arange(2 * 8 * 8, dtype=np.uint8).reshape(2, 8, 8)
    monkeypatch.setattr(io, "read_tiff", lambda _: (raw, None))

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
    monkeypatch.setattr(io, "read_tiff", lambda _: (raw, None))

    loaded = load_image_stack("sample.tiff")

    assert loaded.voxel_size == io.DEFAULT_VOXEL_SIZE
    assert loaded.voxel_source == "default"


def test_load_image_stack_reads_lsm_as_tiff_like(monkeypatch):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    monkeypatch.setattr(io, "read_tiff", lambda _: (raw, None))

    loaded = load_image_stack("sample.lsm")

    assert loaded.source_path == Path("sample.lsm")
    assert loaded.grayscale.shape == (1, 4, 4)
    assert loaded.voxel_source == "default"


def test_load_image_stack_records_metadata_voxel_source(monkeypatch):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    detected = VoxelSize(x_um=0.5, y_um=0.5, z_um=2.0)
    monkeypatch.setattr(io, "read_tiff", lambda _: (raw, detected))

    loaded = load_image_stack("sample.tif")

    assert loaded.voxel_size == detected
    assert loaded.voxel_source == "metadata"


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
    mock_tiff = ModuleType("tifffile")
    mock_tiff.TiffFile = MockTiffFile
    monkeypatch.setitem(sys.modules, "tifffile", mock_tiff)
    monkeypatch.setattr(io, "voxel_from_tiff", lambda _: VoxelSize(x_um=0.5, y_um=0.5, z_um=2.0))

    info = io.inspect_image_stack(tiff_file)
    assert info["source_path"] == tiff_file
    assert info["grayscale_shape"] == (5, 60, 60)
    assert info["color_shape"] == (5, 60, 60, 3)
    assert info["voxel_size"] == VoxelSize(0.5, 0.5, 2.0)
    assert info["voxel_source"] == "metadata"


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



