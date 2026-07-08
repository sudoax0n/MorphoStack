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
from morphostack.core.active_surfaces import (
    _sample_intensity_profile,
    _surfel_in_contact_zone,
    apply_watershed_pre_split_stack,
    build_seed_mask_2d,
    compute_grad_force_max,
    compute_grad_force_nearest_edge,
    concavity_contact_bend_scale,
    find_nearest_edge_offset,
    make_sphere,
    surfels_to_mask_stack,
    watershed_foreground_from_seed,
)


def _touching_vesicle_slice() -> np.ndarray:
    frame = np.zeros((80, 80), dtype=np.uint8)
    for y in range(80):
        for x in range(80):
            if np.hypot(x - 30.0, y - 40.0) < 12.0 or np.hypot(x - 48.0, y - 40.0) < 8.0:
                frame[y, x] = 220
    return frame


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


def test_find_nearest_edge_offset_prefers_close_membrane():
    arr = np.zeros((1, 1, 40), dtype=np.uint8)
    arr[0, 0, 8:18] = 180
    arr[0, 0, 18:22] = 20
    arr[0, 0, 22:32] = 255

    pos = np.array([13.0, 0.0, 0.0], dtype=np.float32)
    normal = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    samples = _sample_intensity_profile(
        arr,
        pos,
        normal,
        radius_search=12.0,
        radius_res=0.5,
        radius_delta=0.0,
        ZScale=1.0,
    )
    s_edge, relaxed = find_nearest_edge_offset(
        samples,
        radius_res=0.5,
        radius_relaxed=6.0,
    )

    assert s_edge is not None
    assert 3.0 <= s_edge <= 7.0
    assert relaxed == 1.0

    nearest_force, _ = compute_grad_force_nearest_edge(
        arr,
        pos,
        normal,
        k_grad=0.03,
        radius_relaxed=6.0,
        radius_res=0.5,
        radius_delta=0.0,
        radius_search=20.0,
        ZScale=1.0,
    )
    legacy_force, _ = compute_grad_force_max(
        arr,
        pos,
        normal,
        k_grad=0.03,
        radius_relaxed=6.0,
        radius_res=0.5,
        radius_delta=0.0,
        radius_search=20.0,
        ZScale=1.0,
    )
    assert float(nearest_force[0]) > 0.0
    assert float(legacy_force[0]) > 0.0
    assert abs(s_edge) < 8.0


def test_build_seed_mask_circle_excludes_neighbor():
    mask = build_seed_mask_2d(60, 60, seed_x=20.0, seed_y=30.0, seed_radius=8.0)
    assert mask[30, 20]
    assert not mask[30, 35]


def test_surfels_to_mask_stack_respects_hard_seed_mask():
    surfels = []
    for center_x, center_y, radius in ((20.0, 30.0, 8.0), (42.0, 30.0, 7.0)):
        for angle in np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False):
            surfels.append({
                "pos": np.array([
                    center_x + radius * np.cos(angle),
                    center_y + radius * np.sin(angle),
                    1.0,
                ], dtype=np.float32),
            })

    mask = surfels_to_mask_stack(
        surfels,
        (3, 60, 60),
        1.0,
        seed_x=20.0,
        seed_y=30.0,
        seed_radius=9.0,
        d_0=2.0,
    )

    assert mask[1, 30, 20]
    assert not mask[1, 30, 42]
    assert np.max(np.where(mask[1])[1]) < 35


def test_watershed_splits_touching_vesicles_from_seed():
    frame = _touching_vesicle_slice()
    seed_mask = build_seed_mask_2d(80, 80, seed_x=30.0, seed_y=40.0, seed_radius=9.0)
    split = watershed_foreground_from_seed(frame, 100.0, 30.0, 40.0, seed_mask)

    assert split[40, 30]
    assert not split[40, 48]
    assert int(np.max(np.where(split)[1])) < 42


def test_apply_watershed_pre_split_stack_masks_neighbor():
    frame = _touching_vesicle_slice()
    stack = np.repeat(frame[np.newaxis, ...], 3, axis=0)
    masked = apply_watershed_pre_split_stack(
        stack,
        [100.0, 100.0, 100.0],
        seed_x=30.0,
        seed_y=40.0,
        seed_radius=9.0,
    )

    assert masked[1, 40, 30] > 0
    assert masked[1, 40, 48] == 0


def test_concavity_contact_bend_scale_boosts_at_diverging_normals():
    frame = _touching_vesicle_slice()
    arr = frame[np.newaxis, ...]
    s1 = {
        "pos": np.array([30.0, 38.0, 0.0], dtype=np.float32),
        "normal": np.array([0.9, 0.4, 0.0], dtype=np.float32),
    }
    concave_s2 = {
        "pos": np.array([34.0, 38.0, 0.0], dtype=np.float32),
        "normal": np.array([-0.9, 0.4, 0.0], dtype=np.float32),
    }
    aligned_s2 = {
        "pos": np.array([34.0, 38.0, 0.0], dtype=np.float32),
        "normal": np.array([0.9, 0.4, 0.0], dtype=np.float32),
    }

    concave_scale = concavity_contact_bend_scale(
        s1,
        concave_s2,
        1.0,
        0.0,
        0.0,
        arr=arr,
        seed_x=30.0,
        seed_y=40.0,
        seed_radius=9.0,
        ZScale=1.0,
        seed_z_scaled=0.0,
    )
    aligned_scale = concavity_contact_bend_scale(
        s1,
        aligned_s2,
        1.0,
        0.0,
        0.0,
        arr=arr,
        seed_x=30.0,
        seed_y=40.0,
        seed_radius=9.0,
        ZScale=1.0,
        seed_z_scaled=0.0,
    )

    assert concave_scale > aligned_scale
    assert concave_scale >= 2.0


def test_surfel_contact_zone_samples_ahead_along_z_normal():
    stack = np.zeros((8, 80, 80), dtype=np.uint8)
    stack[2, 39:41, 37:39] = 200
    stack[5, 39:41, 37:39] = 30

    surfel = {
        "pos": np.array([38.0, 40.0, 2.0], dtype=np.float32),
        "normal": np.array([0.0, 0.0, 1.0], dtype=np.float32),
    }
    assert _surfel_in_contact_zone(
        surfel,
        stack,
        seed_x=30.0,
        seed_y=40.0,
        seed_radius=9.0,
        ZScale=1.0,
        seed_z_scaled=2.0,
    )


def test_apply_watershed_pre_split_stack_can_be_disabled():
    frame = _touching_vesicle_slice()
    stack = np.repeat(frame[np.newaxis, ...], 3, axis=0)
    masked = apply_watershed_pre_split_stack(
        stack,
        [100.0, 100.0, 100.0],
        seed_x=30.0,
        seed_y=40.0,
        seed_radius=9.0,
        enabled=False,
    )
    assert np.array_equal(masked, stack)


def test_analyze_stack_active_surfaces_watershed_pre_split_opt_out():
    shape = (5, 80, 80)
    stack = np.zeros(shape, dtype=np.uint8)
    for z in range(shape[0]):
        for y in range(shape[1]):
            for x in range(shape[2]):
                if np.hypot(x - 30.0, y - 40.0) < 12.0 or np.hypot(x - 48.0, y - 40.0) < 8.0:
                    stack[z, y, x] = 220

    seed = ObjectSeed(x=30.0, y=40.0, frame_index=2, radius=9.0, type="circle")
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=VoxelSize(1.0, 1.0, 1.0),
        profile="active_surfaces",
        object_seed=seed,
        active_surfaces_watershed_pre_split=False,
    )
    frame = analysis.frames[2]
    assert frame.contour is not None
    assert float(np.max(frame.contour[:, 0])) < 42.0


def test_active_surfaces_touching_vesicles_stays_inside_seed():
    shape = (5, 80, 80)
    stack = np.zeros(shape, dtype=np.uint8)
    large_cx, large_cy, large_r = 30.0, 40.0, 12.0
    small_cx, small_cy, small_r = 48.0, 40.0, 8.0

    for z in range(shape[0]):
        for y in range(shape[1]):
            for x in range(shape[2]):
                d_large = np.hypot(x - large_cx, y - large_cy)
                d_small = np.hypot(x - small_cx, y - small_cy)
                if d_large < large_r or d_small < small_r:
                    stack[z, y, x] = 220

    voxel = VoxelSize(1.0, 1.0, 1.0)
    circle_seed = ObjectSeed(x=30.0, y=40.0, frame_index=2, radius=9.0, type="circle")

    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=voxel,
        profile="active_surfaces",
        object_seed=circle_seed,
    )

    frame = analysis.frames[2]
    assert frame.contour is not None
    contour_x = frame.contour[:, 0]
    assert float(np.mean(contour_x)) < 38.0
    assert float(np.max(contour_x)) < 42.0


def test_active_surfaces_segmentation_active_surfaces():
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

    # Run Active surfaces-lite profile
    analysis = analyze_stack(
        stack,
        thresholds=100,
        voxel_size=voxel,
        profile="active_surfaces",
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
