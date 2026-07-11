"""MorphoStack active-surfaces (surfel) segmentation engine."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import KDTree


def build_seed_mask_2d(
    width: int,
    height: int,
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    polygon_points: list[tuple[float, float]] | None = None,
) -> np.ndarray:
    """Build a 2D boolean mask for the user seed region (circle or polygon)."""
    img = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(img)
    if polygon_points is not None and len(polygon_points) >= 3:
        draw.polygon([(float(x), float(y)) for x, y in polygon_points], fill=1)
    else:
        cx = float(seed_x)
        cy = float(seed_y)
        r = float(seed_radius)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=1)
    return np.asarray(img, dtype=bool)


def _xy_inside_seed_mask(x: float, y: float, seed_mask: np.ndarray) -> bool:
    ny, nx = seed_mask.shape
    xi = int(round(x))
    yi = int(round(y))
    if 0 <= xi < nx and 0 <= yi < ny:
        return bool(seed_mask[yi, xi])
    return False


def constrain_xy_to_seed(
    pos: np.ndarray,
    seed_mask: np.ndarray,
    anchor_x: float,
    anchor_y: float,
) -> None:
    """Pull an (x, y) surfel position back inside the hard seed mask."""
    if _xy_inside_seed_mask(float(pos[0]), float(pos[1]), seed_mask):
        return

    x = float(pos[0])
    y = float(pos[1])
    for _ in range(200):
        if _xy_inside_seed_mask(x, y, seed_mask):
            break
        x += (anchor_x - x) * 0.25
        y += (anchor_y - y) * 0.25
    else:
        x = anchor_x
        y = anchor_y

    ny, nx = seed_mask.shape
    pos[0] = np.clip(x, 0.0, float(nx - 1))
    pos[1] = np.clip(y, 0.0, float(ny - 1))


def _rasterize_surfel_ring(
    pts: list[np.ndarray],
    width: int,
    height: int,
    brush_radius: int,
) -> np.ndarray:
    """Rasterize surfel XY positions into a closed ring-like binary image."""
    ring = np.zeros((height, width), dtype=np.uint8)
    try:
        import cv2
    except Exception:
        for p in pts:
            xi = int(round(float(p[0])))
            yi = int(round(float(p[1])))
            if 0 <= xi < width and 0 <= yi < height:
                ring[yi, xi] = 255
        return ring

    for p in pts:
        xi = int(round(float(p[0])))
        yi = int(round(float(p[1])))
        if 0 <= xi < width and 0 <= yi < height:
            cv2.circle(ring, (xi, yi), brush_radius, 255, thickness=-1)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    ring = cv2.morphologyEx(ring, cv2.MORPH_CLOSE, kernel, iterations=2)
    ring = cv2.dilate(ring, kernel, iterations=1)
    return ring


def _fill_slice_from_ring(
    ring: np.ndarray,
    seed_mask: np.ndarray,
    seed_x: float,
    seed_y: float,
) -> np.ndarray:
    """Fill the interior bounded by a surfel ring, then clip to the seed mask."""
    height, width = ring.shape
    sx = int(round(seed_x))
    sy = int(round(seed_y))
    sx = int(np.clip(sx, 0, width - 1))
    sy = int(np.clip(sy, 0, height - 1))

    interior = np.zeros((height, width), dtype=bool)
    if np.any(ring):
        try:
            from scipy.ndimage import binary_fill_holes
        except Exception:
            binary_fill_holes = None

        try:
            import cv2
        except Exception:
            cv2 = None

        if binary_fill_holes is not None:
            filled = binary_fill_holes(ring > 0)
        else:
            filled = ring > 0

        if cv2 is not None:
            filled_u8 = filled.astype(np.uint8)
            n_labels, labels = cv2.connectedComponents(filled_u8, connectivity=8)
            seed_label = int(labels[sy, sx])
            if seed_label > 0:
                interior = labels == seed_label
            else:
                contours, _ = cv2.findContours(filled_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours:
                    if cv2.pointPolygonTest(contour, (float(sx), float(sy)), measureDist=False) >= 0:
                        cv2.fillPoly(filled_u8, [contour], 1)
                        interior = filled_u8.astype(bool)
                        break
        else:
            interior = filled

    if not np.any(interior):
        interior[sy, sx] = True

    return interior & seed_mask


def _connected_component_at_seed(binary: np.ndarray, seed_x: float, seed_y: float) -> np.ndarray:
    """Return the 8-connected component containing the seed pixel."""
    ny, nx = binary.shape
    sx = int(np.clip(round(seed_x), 0, nx - 1))
    sy = int(np.clip(round(seed_y), 0, ny - 1))

    try:
        import cv2
        n_labels, labels = cv2.connectedComponents(binary.astype(np.uint8), connectivity=8)
        seed_label = int(labels[sy, sx])
        if seed_label > 0:
            return labels == seed_label
    except Exception:
        pass

    try:
        from scipy.ndimage import label as nd_label
        labeled, _ = nd_label(binary)
        seed_label = int(labeled[sy, sx])
        if seed_label > 0:
            return labeled == seed_label
    except Exception:
        pass

    fallback = np.zeros_like(binary, dtype=bool)
    fallback[sy, sx] = True
    return fallback


def watershed_foreground_from_seed(
    frame: np.ndarray,
    threshold: float,
    seed_x: float,
    seed_y: float,
    seed_mask: np.ndarray,
) -> np.ndarray:
    """Watershed-split a thresholded slice and keep the component seeded by the ROI."""
    binary = np.asarray(frame) >= threshold
    if not np.any(binary):
        return np.zeros_like(binary, dtype=bool)

    sx = int(np.clip(round(seed_x), 0, binary.shape[1] - 1))
    sy = int(np.clip(round(seed_y), 0, binary.shape[0] - 1))

    try:
        from scipy import ndimage
        from skimage.feature import peak_local_max
        from skimage.segmentation import watershed
    except Exception:
        return _connected_component_at_seed(binary, seed_x, seed_y) & seed_mask

    distance = ndimage.distance_transform_edt(binary)
    seed_distance = float(distance[sy, sx])
    min_distance = max(3, int(round(max(1.0, seed_distance) * 0.75)))

    coords = peak_local_max(
        distance,
        min_distance=min_distance,
        labels=binary.astype(np.int32),
        exclude_border=False,
    )
    markers = np.zeros(binary.shape, dtype=np.int32)
    markers[~binary] = 1

    if coords.size == 0:
        markers[sy, sx] = 2
        seed_label = 2
    else:
        seed_label = None
        best_dist = float("inf")
        for idx, (py, px) in enumerate(coords):
            label_id = idx + 2
            markers[py, px] = label_id
            dist = (float(px) - seed_x) ** 2 + (float(py) - seed_y) ** 2
            if dist < best_dist:
                best_dist = dist
                seed_label = label_id
        if seed_label is None:
            markers[sy, sx] = 2
            seed_label = 2

    labels = watershed(-distance, markers, mask=binary)
    component = labels == seed_label
    if not np.any(component):
        component = _connected_component_at_seed(binary, seed_x, seed_y)
    return component & seed_mask


def watershed_split_stack(
    arr: np.ndarray,
    thresholds: tuple[float, ...] | list[float],
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    polygon_points: list[tuple[float, float]] | None = None,
) -> np.ndarray:
    """Build a per-slice watershed foreground mask for the seeded vesicle."""
    nz, ny, nx = arr.shape
    seed_mask = build_seed_mask_2d(nx, ny, seed_x, seed_y, seed_radius, polygon_points)
    splits = np.zeros((nz, ny, nx), dtype=bool)
    threshold_list = list(thresholds)
    for z in range(nz):
        thresh = threshold_list[z] if z < len(threshold_list) else threshold_list[-1]
        splits[z] = watershed_foreground_from_seed(arr[z], thresh, seed_x, seed_y, seed_mask)
    return splits


def apply_watershed_pre_split_stack(
    arr: np.ndarray,
    thresholds: tuple[float, ...] | list[float],
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    polygon_points: list[tuple[float, float]] | None = None,
    *,
    enabled: bool = True,
    splits: np.ndarray | None = None,
) -> np.ndarray:
    """Mask stack intensities to watershed-split foreground for the seeded vesicle."""
    if not enabled:
        return np.array(arr, copy=True)

    if splits is None:
        splits = watershed_split_stack(
            arr,
            thresholds,
            seed_x,
            seed_y,
            seed_radius,
            polygon_points,
        )
    return np.where(splits, arr, 0)


def _surfel_in_contact_zone(
    surfel: dict[str, Any],
    arr: np.ndarray,
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    ZScale: float,
    seed_z_scaled: float,
) -> bool:
    """True when a surfel sits near the seed rim and faces a darker outward gap."""
    pos = surfel["pos"]
    normal = surfel["normal"]
    dx = float(pos[0]) - seed_x
    dy = float(pos[1]) - seed_y
    dz = float(pos[2]) - seed_z_scaled
    radial_xy = float(np.hypot(dx, dy))
    if radial_xy < seed_radius * 0.55 or radial_xy > seed_radius * 1.05:
        return False

    radial_3d = float(np.sqrt(dx * dx + dy * dy + dz * dz))
    outward = (
        dx * float(normal[0]) + dy * float(normal[1]) + dz * float(normal[2])
    ) / max(radial_3d, 1e-6)
    outward_xy = (
        dx * float(normal[0]) + dy * float(normal[1])
    ) / max(radial_xy, 1e-6)
    if outward < 0.35 and outward_xy < 0.35 and abs(float(normal[2])) < 0.5:
        return False

    probe = 2.5
    here = get_pixel_value(arr, float(pos[0]), float(pos[1]), float(pos[2]) / ZScale)
    ahead = get_pixel_value(
        arr,
        float(pos[0]) + float(normal[0]) * probe,
        float(pos[1]) + float(normal[1]) * probe,
        (float(pos[2]) + float(normal[2]) * probe) / ZScale,
    )
    return ahead < here * 0.75


def concavity_contact_bend_scale(
    s1: dict[str, Any],
    s2: dict[str, Any],
    ux: float,
    uy: float,
    uz: float,
    *,
    arr: np.ndarray,
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    ZScale: float,
    seed_z_scaled: float,
) -> float:
    """Boost local bending stiffness at concave hinges and outward contact zones."""
    n1 = s1["normal"]
    n2 = s2["normal"]
    link = np.array([ux, uy, uz], dtype=np.float32)
    normal_alignment = float(np.dot(n1, n2))
    hinge = float(np.dot(n1 + n2, link))

    scale = 1.0
    if normal_alignment < 0.25:
        scale += 2.5 * (1.0 - max(normal_alignment, -1.0))
    if hinge < 0.0:
        scale += 2.0 * min(1.0, -hinge)

    if _surfel_in_contact_zone(s1, arr, seed_x, seed_y, seed_radius, ZScale, seed_z_scaled):
        scale += 1.5
    elif _surfel_in_contact_zone(s2, arr, seed_x, seed_y, seed_radius, ZScale, seed_z_scaled):
        scale += 1.5

    return scale


def make_sphere(d_0: float, px: float, py: float, pz: float, radius: float) -> list[dict[str, Any]]:
    """Initialize a sphere of surfels."""
    ans = []
    dlat = d_0 / radius
    lat_i = -np.pi / 2
    lat_f = np.pi / 2

    lat = lat_i + dlat
    while lat < lat_f:
        R = radius * np.cos(lat)
        N = int(np.pi * 2.0 * R / d_0)
        if N > 0:
            d_angle = np.pi * 2.0 / N
            for i in range(N):
                angle = i * d_angle
                nx = R * np.sin(angle)
                ny = R * np.cos(angle)
                nz = radius * np.sin(lat)

                mag = np.sqrt(nx**2 + ny**2 + nz**2)
                ux = nx / mag if mag > 0.0 else 0.0
                uy = ny / mag if mag > 0.0 else 0.0
                uz = nz / mag if mag > 0.0 else 0.0

                ans.append({
                    "pos": np.array([px + nx, py + ny, pz + nz], dtype=np.float32),
                    "normal": np.array([ux, uy, uz], dtype=np.float32),
                    "force": np.zeros(3, dtype=np.float32),
                    "moment": np.zeros(3, dtype=np.float32),
                    "repForce": np.zeros(3, dtype=np.float32),
                    "N_Neighbor": 6,
                    "age": 0,
                    "relaxed": 0.0
                })
        lat += dlat
    return ans


def make_polygon_shell(d_0: float, pz: float, points: list[tuple[float, float]], radius: float) -> list[dict[str, Any]]:
    """Initialize a deformed 3D shell of surfels matching a 2D polygon seed."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if not xs or not ys:
        return []
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    pts = list(points)
    if len(pts) > 0 and (pts[0][0] != pts[-1][0] or pts[0][1] != pts[-1][1]):
        pts.append(pts[0])

    dists = []
    for i in range(len(pts) - 1):
        dx = pts[i+1][0] - pts[i][0]
        dy = pts[i+1][1] - pts[i][1]
        dists.append(np.sqrt(dx**2 + dy**2))
    
    cum_dists = [0.0] + list(np.cumsum(dists))
    total_perimeter = cum_dists[-1]

    if total_perimeter <= 1e-4:
        return make_sphere(d_0, cx, cy, pz, radius)

    def interpolate_perimeter(d: float) -> tuple[float, float, float, float]:
        d = max(0.0, min(total_perimeter, d))
        idx = np.searchsorted(cum_dists, d)
        if idx == 0:
            idx = 1
        t = (d - cum_dists[idx-1]) / (cum_dists[idx] - cum_dists[idx-1]) if (cum_dists[idx] - cum_dists[idx-1]) > 0 else 0.0
        p1 = pts[idx-1]
        p2 = pts[idx]
        x = p1[0] + t * (p2[0] - p1[0])
        y = p1[1] + t * (p2[1] - p1[1])
        
        # Unit vector pointing outward from centroid to serve as local normal guide
        vx = x - cx
        vy = y - cy
        v_len = np.sqrt(vx**2 + vy**2)
        ux = vx / v_len if v_len > 0.0 else 1.0
        uy = vy / v_len if v_len > 0.0 else 0.0
        return x, y, ux, uy

    ans = []
    
    # South Pole cap
    ans.append({
        "pos": np.array([cx, cy, pz - radius], dtype=np.float32),
        "normal": np.array([0.0, 0.0, -1.0], dtype=np.float32),
        "force": np.zeros(3, dtype=np.float32),
        "moment": np.zeros(3, dtype=np.float32),
        "repForce": np.zeros(3, dtype=np.float32),
        "N_Neighbor": 6,
        "age": 0,
        "relaxed": 0.0
    })

    # Draped latitude rings
    dlat = d_0 / radius
    lat_i = -np.pi / 2
    lat_f = np.pi / 2

    lat = lat_i + dlat
    while lat < lat_f:
        cos_lat = np.cos(lat)
        sin_lat = np.sin(lat)
        N = int(total_perimeter * cos_lat / d_0)
        if N > 0:
            for i in range(N):
                d = (i / N) * total_perimeter
                px_val, py_val, ux, uy = interpolate_perimeter(d)
                
                # Deform horizontal position relative to centroid based on latitude cos
                nx = (px_val - cx) * cos_lat
                ny = (py_val - cy) * cos_lat
                nz = radius * sin_lat
                
                # Construct 3D normal vector
                unx = ux * cos_lat
                uny = uy * cos_lat
                unz = sin_lat
                mag = np.sqrt(unx**2 + uny**2 + unz**2)
                if mag > 0.0:
                    unx /= mag
                    uny /= mag
                    unz /= mag
                else:
                    unx, uny, unz = 0.0, 0.0, 1.0

                ans.append({
                    "pos": np.array([cx + nx, cy + ny, pz + nz], dtype=np.float32),
                    "normal": np.array([unx, uny, unz], dtype=np.float32),
                    "force": np.zeros(3, dtype=np.float32),
                    "moment": np.zeros(3, dtype=np.float32),
                    "repForce": np.zeros(3, dtype=np.float32),
                    "N_Neighbor": 6,
                    "age": 0,
                    "relaxed": 0.0
                })
        lat += dlat

    # North Pole cap
    ans.append({
        "pos": np.array([cx, cy, pz + radius], dtype=np.float32),
        "normal": np.array([0.0, 0.0, 1.0], dtype=np.float32),
        "force": np.zeros(3, dtype=np.float32),
        "moment": np.zeros(3, dtype=np.float32),
        "repForce": np.zeros(3, dtype=np.float32),
        "N_Neighbor": 6,
        "age": 0,
        "relaxed": 0.0
    })

    return ans


def compute_forces_attract_repul(
    d_0: float,
    radius_threshold_interact: float,
    N_step_per_R0: int,
    ka: float,
    pa: float,
    pr: float,
    kr: float,
    max_displacement_per_step: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute the attraction/repulsion force lookup tables."""
    NPt = int((radius_threshold_interact + 1.0) * N_step_per_R0)
    f_att = np.zeros(NPt, dtype=np.float32)
    f_rep = np.zeros(NPt, dtype=np.float32)
    i_tr = -1
    for i in range(NPt - 1, 0, -1):
        dist_ratio = float(i) / float(N_step_per_R0)
        f_att[i] = pa * ka / (dist_ratio ** (pa + 1))
        f_rep[i] = -pr * kr / (dist_ratio ** (pr + 1))
        if f_att[i] + f_rep[i] < 0:
            if i_tr == -1:
                i_tr = i
            f_att[i] = pr * kr
            f_rep[i] = -pr * kr - (1.0 - dist_ratio) * max_displacement_per_step
    return f_att, f_rep


def get_pixel_value(arr: np.ndarray, x: float, y: float, z: float) -> float:
    """Read a pixel intensity from the stack using nearest-neighbor interpolation and bounds checking."""
    zi = int(round(z))
    yi = int(round(y))
    xi = int(round(x))
    nz, ny, nx = arr.shape
    if 0 <= zi < nz and 0 <= yi < ny and 0 <= xi < nx:
        return float(arr[zi, yi, xi])
    return 0.0


def _sample_intensity_profile(
    arr: np.ndarray,
    pos: np.ndarray,
    normal: np.ndarray,
    *,
    radius_search: float,
    radius_res: float,
    radius_delta: float,
    ZScale: float,
) -> list[tuple[float, float]]:
    """Sample image intensity along the surfel normal centered on pos."""
    n_steps = max(1, int(round(radius_search / radius_res)))
    origin = np.asarray(pos, dtype=np.float64)
    normal_vec = np.asarray(normal, dtype=np.float64)
    delta = float(radius_delta)
    samples: list[tuple[float, float]] = []
    for i in range(-n_steps, n_steps + 1):
        s = float(i) * radius_res
        x = origin[0] + (delta + s) * normal_vec[0]
        y = origin[1] + (delta + s) * normal_vec[1]
        z = origin[2] + (delta + s) * normal_vec[2]
        samples.append((s, get_pixel_value(arr, x, y, z / ZScale)))
    return samples


def _edge_peaks_from_profile(samples: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """Return local maxima of |dI/ds| along a 1D intensity profile."""
    if len(samples) < 2:
        return []

    edges: list[tuple[float, float, float]] = []
    for i in range(1, len(samples)):
        s0, v0 = samples[i - 1]
        s1, v1 = samples[i]
        ds = s1 - s0
        if ds <= 0.0:
            continue
        grad = (v1 - v0) / ds
        s_mid = 0.5 * (s0 + s1)
        edges.append((s_mid, grad, abs(grad)))

    if not edges:
        return []

    peaks: list[tuple[float, float, float]] = []
    for j, edge in enumerate(edges):
        s_mid, grad, abs_grad = edge
        left = edges[j - 1][2] if j > 0 else 0.0
        right = edges[j + 1][2] if j < len(edges) - 1 else 0.0
        if abs_grad >= left and abs_grad >= right:
            peaks.append((s_mid, grad, abs_grad))
    return peaks


def find_nearest_edge_offset(
    samples: list[tuple[float, float]],
    *,
    radius_res: float,
    radius_relaxed: float,
) -> tuple[float | None, float]:
    """Pick the nearest significant membrane edge along a normal profile.

    Prefers the first outward edge so a nearby vesicle membrane wins over a
    brighter neighbor further along the same ray.
    """
    peaks = _edge_peaks_from_profile(samples)
    if not peaks:
        values = [value for _, value in samples]
        if not values or (max(values) - min(values)) < 1.0:
            return None, 0.0
        edges = []
        for i in range(1, len(samples)):
            s0, v0 = samples[i - 1]
            s1, v1 = samples[i]
            ds = s1 - s0
            if ds <= 0.0:
                continue
            grad = (v1 - v0) / ds
            edges.append((0.5 * (s0 + s1), grad, abs((v1 - v0) / ds)))
        if not edges:
            return None, 0.0
        peaks = [max(edges, key=lambda item: item[2])]

    max_strength = max(peak[2] for peak in peaks)
    threshold = max(1.0, 0.2 * max_strength)
    strong = [peak for peak in peaks if peak[2] >= threshold] or peaks

    outward = [peak for peak in strong if peak[0] > radius_res * 0.25]
    if outward:
        s_edge, _, _ = min(outward, key=lambda item: item[0])
    else:
        s_edge, _, _ = min(strong, key=lambda item: abs(item[0]))

    relaxed = 1.0 if abs(s_edge) <= radius_relaxed else 0.0
    return s_edge, relaxed


def compute_grad_force_nearest_edge(
    arr: np.ndarray,
    pos: np.ndarray,
    normal: np.ndarray,
    k_grad: float,
    radius_relaxed: float,
    radius_res: float,
    radius_delta: float,
    radius_search: float,
    ZScale: float,
) -> tuple[np.ndarray, float]:
    """Lock surfels to the nearest membrane edge along their normal."""
    samples = _sample_intensity_profile(
        arr,
        pos,
        normal,
        radius_search=radius_search,
        radius_res=radius_res,
        radius_delta=radius_delta,
        ZScale=ZScale,
    )
    s_edge, relaxed = find_nearest_edge_offset(
        samples,
        radius_res=radius_res,
        radius_relaxed=radius_relaxed,
    )
    if s_edge is None:
        return np.zeros(3, dtype=np.float32), 0.0

    peaks = _edge_peaks_from_profile(samples)
    max_strength = max((peak[2] for peak in peaks), default=1.0)
    chosen = next((peak for peak in peaks if abs(peak[0] - s_edge) < radius_res * 0.75), None)
    edge_strength = chosen[2] if chosen is not None else max_strength
    direction_sign = 1.0 if s_edge >= 0.0 else -1.0
    strength = min(1.0, edge_strength / max(max_strength, 1e-6))

    grad_force = k_grad * direction_sign * strength * np.asarray(normal, dtype=np.float32)
    return grad_force, relaxed


def compute_grad_force_max(
    arr: np.ndarray,
    pos: np.ndarray,
    normal: np.ndarray,
    k_grad: float,
    radius_relaxed: float,
    radius_res: float,
    radius_delta: float,
    radius_search: float,
    ZScale: float,
) -> tuple[np.ndarray, float]:
    """Legacy brightest-pixel gradient search kept for regression comparisons."""
    fx_ = 0.0
    fy_ = 0.0
    fz_ = 0.0

    dx = radius_res * normal[0]
    dy = radius_res * normal[1]
    dz = radius_res * normal[2]

    xp = pos[0] + radius_delta * normal[0]
    yp = pos[1] + radius_delta * normal[1]
    zp = pos[2] + radius_delta * normal[2]

    val_max = get_pixel_value(arr, xp, yp, zp / ZScale)

    n_steps = int((radius_search / 2.0) / radius_res)
    relaxed = 1.0
    all_equal = True

    x_curr, y_curr, z_curr = xp, yp, zp
    r = 0.0
    for _ in range(n_steps):
        x_curr += dx
        y_curr += dy
        z_curr += dz
        r += radius_res

        val_test = get_pixel_value(arr, x_curr, y_curr, z_curr / ZScale)
        if val_test != val_max:
            all_equal = False
        if val_test > val_max:
            val_max = val_test
            relaxed = 1.0 if r < radius_relaxed else 0.0
            fx_, fy_, fz_ = 1.0, 1.0, 1.0

    x_curr, y_curr, z_curr = xp, yp, zp
    r = 0.0
    for _ in range(n_steps):
        x_curr -= dx
        y_curr -= dy
        z_curr -= dz
        r += radius_res

        val_test = get_pixel_value(arr, x_curr, y_curr, z_curr / ZScale)
        if val_test != val_max:
            all_equal = False
        if val_test > val_max:
            val_max = val_test
            relaxed = 1.0 if r < radius_relaxed else 0.0
            fx_, fy_, fz_ = -1.0, -1.0, -1.0

    if all_equal:
        relaxed = 0.0

    grad_force = k_grad * np.array([fx_ * normal[0], fy_ * normal[1], fz_ * normal[2]], dtype=np.float32)
    return grad_force, relaxed


ACTIVE_SURFACES_DEFAULTS: dict[str, float | int] = {
    "d_0": 2.0,
    "f_pressure": 0.02,
    "k_grad": 0.05,
    # Full-quality Analyze defaults. Mesh preview uses ACTIVE_SURFACES_FAST_DEFAULTS.
    "relaxation_steps": 100,
    "optimization_steps": 300,
}

# Reduced steps for interactive mesh preview after seed isolation crop.
# Tuned so synthetic spheres still produce usable contours while finishing much
# faster than full 100+300 optimization on large CZI stacks.
ACTIVE_SURFACES_FAST_DEFAULTS: dict[str, float | int] = {
    "d_0": 2.0,
    "f_pressure": 0.02,
    "k_grad": 0.05,
    "relaxation_steps": 40,
    "optimization_steps": 80,
}


def run_active_surfaces_optimization(
    arr: np.ndarray,
    seed_x: float,
    seed_y: float,
    seed_z: float,
    seed_radius: float,
    voxel_size_x: float = 1.0,
    voxel_size_z: float = 1.0,
    d_0: float = float(ACTIVE_SURFACES_DEFAULTS["d_0"]),
    f_pressure: float = float(ACTIVE_SURFACES_DEFAULTS["f_pressure"]),
    k_grad: float = float(ACTIVE_SURFACES_DEFAULTS["k_grad"]),
    relaxation_steps: int = int(ACTIVE_SURFACES_DEFAULTS["relaxation_steps"]),
    optimization_steps: int = int(ACTIVE_SURFACES_DEFAULTS["optimization_steps"]),
    polygon_points: list[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    """Run relaxation and optimization steps on the surfel cloud."""
    ZScale = voxel_size_z / voxel_size_x if voxel_size_x > 0.0 else 1.0

    # Initialize sphere or polygon shell
    px = seed_x
    py = seed_y
    pz = seed_z * ZScale
    if polygon_points is not None and len(polygon_points) >= 3:
        surfels = make_polygon_shell(d_0, pz, polygon_points, seed_radius)
    else:
        surfels = make_sphere(d_0, px, py, pz, seed_radius)

    # Parameters
    k_align = 0.05
    k_bend = 0.1
    radius_threshold_interact = 1.75
    N_step_per_R0 = 5000
    max_displacement_per_step = 0.3
    age_min_generate = 10
    # Tighter seeds pack surfels together; allow higher neighbor counts so the
    # cloud is not deleted when constrained to the user ROI.
    rm_if_neighbor_below = 5
    rm_if_neighbor_above = 24
    generate_dot_if_neighbor_equals = 6
    radius_relaxed = 1.0
    radius_res = 0.5
    radius_search = d_0 * 2.0
    radius_delta = 0.0

    kr = 5.0 * 0.01 / 9.0  # pa * ka / pr
    limit_interact_attract = radius_threshold_interact * d_0

    f_att, f_rep = compute_forces_attract_repul(
        d_0=d_0,
        radius_threshold_interact=radius_threshold_interact,
        N_step_per_R0=N_step_per_R0,
        ka=0.01,
        pa=5.0,
        pr=9.0,
        kr=kr,
        max_displacement_per_step=max_displacement_per_step
    )

    nz, ny, nx = arr.shape
    min_x, max_x = 0.0, float(nx - 1)
    min_y, max_y = 0.0, float(ny - 1)
    min_z, max_z = 0.0, float(nz - 1)
    seed_mask_2d = build_seed_mask_2d(
        nx,
        ny,
        seed_x=px,
        seed_y=py,
        seed_radius=seed_radius,
        polygon_points=polygon_points,
    )

    def clamp_pos(pos: np.ndarray) -> None:
        pos[0] = np.clip(pos[0], min_x, max_x)
        pos[1] = np.clip(pos[1], min_y, max_y)
        pos[2] = np.clip(pos[2], min_z * ZScale, max_z * ZScale)
        constrain_xy_to_seed(pos, seed_mask_2d, anchor_x=px, anchor_y=py)

    for step in range(relaxation_steps + optimization_steps):
        is_relaxation = (step < relaxation_steps)
        curr_k_grad = 0.0 if is_relaxation else k_grad
        curr_normal_force = 0.0 if is_relaxation else f_pressure

        # Reset forces
        for s in surfels:
            s["force"][:] = 0.0
            s["repForce"][:] = 0.0
            s["moment"][:] = 0.0
            s["N_Neighbor"] = 0

        # 1. Image gradient force
        if not is_relaxation and curr_k_grad > 0.0:
            for s in surfels:
                gf, rel = compute_grad_force_nearest_edge(
                    arr=arr,
                    pos=s["pos"],
                    normal=s["normal"],
                    k_grad=curr_k_grad,
                    radius_relaxed=radius_relaxed,
                    radius_res=radius_res,
                    radius_delta=radius_delta,
                    radius_search=radius_search,
                    ZScale=ZScale
                )
                s["force"] += gf
                s["relaxed"] = rel

        # 2. Pair-wise mechanical forces using scipy KDTree
        if len(surfels) > 1:
            positions = np.array([s["pos"] for s in surfels])
            tree = KDTree(positions)
            pairs = tree.query_pairs(limit_interact_attract)
            for i, j in pairs:
                s1 = surfels[i]
                s2 = surfels[j]

                dx = s2["pos"][0] - s1["pos"][0]
                dy = s2["pos"][1] - s1["pos"][1]
                dz = s2["pos"][2] - s1["pos"][2]
                dist = np.sqrt(dx**2 + dy**2 + dz**2)
                if dist > 0.0:
                    ux = dx / dist
                    uy = dy / dist
                    uz = dz / dist

                    pos_tbl = int(dist / d_0 * N_step_per_R0)
                    if pos_tbl < len(f_rep):
                        f_r = f_rep[pos_tbl]
                        f_a = f_att[pos_tbl]

                        rep_f = f_r * np.array([ux, uy, uz])
                        s1["repForce"] += rep_f
                        s2["repForce"] -= rep_f

                        NF = f_a + f_r
                        tot_f = NF * np.array([ux, uy, uz])
                        s1["force"] += tot_f
                        s2["force"] -= tot_f

                        s1["N_Neighbor"] += 1
                        s2["N_Neighbor"] += 1

                        sum_norm = s1["normal"] + s2["normal"]
                        prod_scal = np.dot(sum_norm, [ux, uy, uz])
                        i_flatten = k_align * prod_scal
                        s1["force"] += i_flatten * s1["normal"]
                        s2["force"] -= i_flatten * s2["normal"]

                        bend_scale = concavity_contact_bend_scale(
                            s1,
                            s2,
                            ux,
                            uy,
                            uz,
                            arr=arr,
                            seed_x=px,
                            seed_y=py,
                            seed_radius=seed_radius,
                            ZScale=ZScale,
                            seed_z_scaled=pz,
                        )
                        k_local = k_bend * bend_scale
                        i_perpend1 = -k_local * np.dot(s1["normal"], [ux, uy, uz])
                        s1["moment"] += i_perpend1 * np.array([ux, uy, uz])
                        i_perpend2 = -k_local * np.dot(s2["normal"], [ux, uy, uz])
                        s2["moment"] += i_perpend2 * np.array([ux, uy, uz])

        # 3. Update positions & normals
        for s in surfels:
            s["force"] += curr_normal_force * s["normal"] * (1.0 - s["relaxed"])
            s["force"] *= d_0
            f_norm = np.linalg.norm(s["force"])
            max_f = max_displacement_per_step * d_0
            if f_norm > max_f:
                s["force"] *= max_f / f_norm

            s["pos"] += s["force"]
            clamp_pos(s["pos"])

            s["normal"] += s["moment"]
            norm_len = np.linalg.norm(s["normal"])
            if norm_len > 0.0:
                s["normal"] /= norm_len

            s["age"] += 1

        # 4. Outlier removal
        surfels = [
            s for s in surfels
            if s["N_Neighbor"] >= rm_if_neighbor_below
            and s["N_Neighbor"] <= rm_if_neighbor_above
        ]

        # 5. Hole filling
        new_surfels = []
        for s in surfels:
            if s["N_Neighbor"] == generate_dot_if_neighbor_equals and s["age"] > age_min_generate:
                rep_norm = np.linalg.norm(s["repForce"])
                p_new = np.zeros(3, dtype=np.float32)
                if rep_norm == 0.0:
                    p_new = s["pos"] - 0.5 * d_0 * s["normal"]
                    s["pos"] += 0.25 * d_0 * s["normal"]
                else:
                    rf_u = s["repForce"] / rep_norm
                    cor_plan = np.dot(rf_u, s["normal"])
                    rep_v = rf_u - cor_plan * s["normal"]
                    rep_v_len = np.linalg.norm(rep_v)
                    if rep_v_len > 0.0:
                        rep_v /= rep_v_len
                    p_new = s["pos"] + 0.5 * d_0 * rep_v

                clamp_pos(p_new)
                new_surfels.append({
                    "pos": p_new,
                    "normal": s["normal"].copy(),
                    "force": np.zeros(3, dtype=np.float32),
                    "moment": np.zeros(3, dtype=np.float32),
                    "repForce": np.zeros(3, dtype=np.float32),
                    "N_Neighbor": 6,
                    "age": 0,
                    "relaxed": 0.0
                })
                s["age"] = 0

        surfels.extend(new_surfels)

    return surfels


def surfels_to_mask_stack(
    surfels: list[dict[str, Any]],
    shape: tuple[int, int, int],
    ZScale: float,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    polygon_points: list[tuple[float, float]] | None = None,
    d_0: float = 2.0,
    slice_fallback: np.ndarray | None = None,
) -> np.ndarray:
    """Convert a surfel cloud to a 3D binary mask, clipped to the user seed region."""
    mask = np.zeros(shape, dtype=bool)
    nz, ny, nx = shape
    seed_mask_2d = build_seed_mask_2d(
        nx,
        ny,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_radius=seed_radius,
        polygon_points=polygon_points,
    )
    brush_radius = max(1, int(round(d_0 * 0.75)))

    z_groups: dict[int, list[np.ndarray]] = defaultdict(list)
    for s in surfels:
        z_idx = int(round(s["pos"][2] / ZScale))
        if 0 <= z_idx < nz and _xy_inside_seed_mask(float(s["pos"][0]), float(s["pos"][1]), seed_mask_2d):
            z_groups[z_idx].append(s["pos"][:2])

    for z_idx in range(nz):
        pts = z_groups.get(z_idx, [])
        if len(pts) < 3:
            if (
                slice_fallback is not None
                and 0 <= z_idx < slice_fallback.shape[0]
                and np.any(slice_fallback[z_idx])
            ):
                mask[z_idx] = slice_fallback[z_idx] & seed_mask_2d
            continue
        ring = _rasterize_surfel_ring(pts, nx, ny, brush_radius)
        mask[z_idx] = _fill_slice_from_ring(ring, seed_mask_2d, seed_x, seed_y)

    return mask
