import numpy as np
import pytest

from morphostack.core.mesh import contours_to_mask_stack, write_mask_stack_tiff
from morphostack.core.models import VoxelSize
from morphostack.core.pipeline import analyze_stack


def test_write_mask_stack_tiff_writes_binary_stack(tmp_path):
    tifffile = pytest.importorskip("tifffile")
    stack = np.zeros((2, 10, 10), dtype=np.uint8)
    stack[:, 3:7, 3:7] = 255
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        prefer_opencv=False,
    )
    destination = tmp_path / "mask.tif"
    write_mask_stack_tiff(
        tuple(frame.contour for frame in analysis.frames),
        shape=stack.shape,
        destination=destination,
    )
    loaded = tifffile.imread(destination)
    assert loaded.shape == stack.shape
    assert int(np.max(loaded)) == 255
    assert int(np.min(loaded)) == 0


def test_contours_to_mask_stack_shape_matches_z_dimension():
    contours = [None, None]
    mask = contours_to_mask_stack(contours, shape=(2, 5, 5))
    assert mask.shape == (2, 5, 5)