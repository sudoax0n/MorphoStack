import numpy as np
import pytest
from morphostack.core import (
    ObjectSeed,
    SeedPoint,
    VoxelSize,
    RectROI,
    ZRange,
    StackViewTransform,
    analyze_stack,
)
from morphostack.core.limeseg import make_sphere, run_limeseg_optimization, surfels_to_mask_stack


def test_make_sphere():
    # Test sphere initialization
    surfels = make_sphere(d_0=2.0, px=10.0, py=10.0, pz=10.0, radius=5.0)
    assert len(surfels) > 0
    for s in surfels:
        assert s["pos"].shape == (3,)
        assert s["normal"].shape == (3,)
        assert np.abs(np.linalg.norm(s["normal"]) - 1.0) < 1e-4
        # Distance from center should be around 5.0
        dist = np.linalg.norm(s["pos"] - np.array([10.0, 10.0, 10.0]))
        assert np.abs(dist - 5.0) < 0.5


def test_to_local_seed_object():
    transform = StackViewTransform(
        x_offset=10,
        y_offset=15,
        z_offset=2,
        x_limit=100,
        y_limit=100,
        z_limit=10,
        roi=RectROI(10, 50, 15, 60),
        z_range=ZRange(2, 8),
    )

    # Circle seed
    circle_seed = ObjectSeed(x=20, y=25, frame_index=4, radius=5.0, type="circle")
    local_circle = transform.to_local_seed_object(circle_seed)
    assert local_circle.x == 10
    assert local_circle.y == 10
    assert local_circle.frame_index == 2
    assert local_circle.type == "circle"

    # Polygon seed
    poly_seed = ObjectSeed(
        x=0, y=0, frame_index=5, radius=8.0, type="polygon",
        points=[SeedPoint(20.0, 30.0), SeedPoint(30.0, 40.0)]
    )
    local_poly = transform.to_local_seed_object(poly_seed)
    assert local_poly.type == "polygon"
    assert local_poly.frame_index == 3
    assert len(local_poly.points) == 2
    assert local_poly.points[0].x == 10.0
    assert local_poly.points[0].y == 15.0
    # centroid (20+30)/2 - 10 = 15; (30+40)/2 - 15 = 20
    assert local_poly.x == 15.0
    assert local_poly.y == 20.0


def test_polygon_seed_overlap():
    # Ensure polygon seed selects correct component by overlap
    voxel = VoxelSize(1.0, 1.0, 1.0)
    stack = np.zeros((1, 50, 50), dtype=np.uint8)
    # Left component (distractor)
    stack[0, 10:20, 5:15] = 200
    # Right component (target)
    stack[0, 10:20, 25:35] = 200

    # Draw a polygon overlapping the right component
    poly_seed = ObjectSeed(
        x=30, y=15, frame_index=0, radius=5.0, type="polygon",
        points=[SeedPoint(24.0, 9.0), SeedPoint(36.0, 9.0), SeedPoint(36.0, 21.0), SeedPoint(24.0, 21.0)]
    )

    # Run vesicle profile (uses _build_per_frame_seeds)
    analysis = analyze_stack(stack, thresholds=100, voxel_size=voxel, object_seed=poly_seed, profile="vesicle")
    
    # Left comp center is ~10, right is ~30. The seed should have chosen the right component.
    assert analysis.frames[0].contour is not None
    cx = np.mean(analysis.frames[0].contour[:, 0])
    assert cx > 20.0


def test_limeseg_segmentation_active_surfaces():
    # Build a synthetic 3D sphere stack
    shape = (10, 40, 40)
    stack = np.zeros(shape, dtype=np.uint8)
    
    # Center of sphere: (20, 20, 5)
    cz, cy, cx = 5.0, 20.0, 20.0
    for z in range(shape[0]):
        for y in range(shape[1]):
            for x in range(shape[2]):
                # Make ZScale 1.0 for simplicity
                dist = np.sqrt((x - cx)**2 + (y - cy)**2 + (z - cz)**2)
                if dist < 6.0:
                    stack[z, y, x] = 255
                    
    voxel = VoxelSize(1.0, 1.0, 1.0)
    circle_seed = ObjectSeed(x=20, y=20, frame_index=5, radius=5.0, type="circle")

    # Run LimeSeg-lite profile
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=voxel,
        profile="limeseg",
        include_mesh=True,
        object_seed=circle_seed
    )

    # Verify that we generated results for slices near center
    assert len(analysis.frames) == 10
    # Check that frame 5 (the center slice) has a valid contour
    assert analysis.frames[5].contour is not None
    assert len(analysis.frames[5].contour) >= 3
    # Check that we built a mesh
    assert analysis.mesh is not None
    assert analysis.mesh.surface_area_um2 > 0
    assert analysis.mesh.volume_um3 > 0
