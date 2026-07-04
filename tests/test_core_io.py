from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from morphostack.core import ImageStack, VoxelSize, load_image_stack
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
    assert loaded.grayscale.shape == (1, 4, 4)
    assert loaded.color.shape == (1, 4, 4, 3)


def test_load_image_stack_uses_default_voxel_when_metadata_missing(monkeypatch):
    raw = np.arange(16, dtype=np.uint8).reshape(1, 4, 4)
    monkeypatch.setattr(io, "read_tiff", lambda _: (raw, None))

    loaded = load_image_stack("sample.tiff")

    assert loaded.voxel_size == io.DEFAULT_VOXEL_SIZE


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
