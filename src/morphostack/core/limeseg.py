"""LimeSeg-lite active surfaces segmentation engine in Python."""

from __future__ import annotations

from typing import Any
import numpy as np
from scipy.spatial import KDTree
from PIL import Image, ImageDraw


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
    """Search along normal vector for local intensity maximum to compute gradient force."""
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

    NSteps = int((radius_search / 2.0) / radius_res)
    relaxed = 1.0
    all_equal = True

    # Search forward
    x_curr, y_curr, z_curr = xp, yp, zp
    r = 0.0
    for _ in range(NSteps):
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

    # Search backward
    x_curr, y_curr, z_curr = xp, yp, zp
    r = 0.0
    for _ in range(NSteps):
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


def run_limeseg_optimization(
    arr: np.ndarray,
    seed_x: float,
    seed_y: float,
    seed_z: float,
    seed_radius: float,
    voxel_size_x: float = 1.0,
    voxel_size_z: float = 1.0,
    d_0: float = 2.0,
    f_pressure: float = 0.015,
    k_grad: float = 0.03,
    relaxation_steps: int = 100,
    optimization_steps: int = 200,
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
    rm_if_neighbor_below = 5
    rm_if_neighbor_above = 11
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

    def clamp_pos(pos: np.ndarray) -> None:
        pos[0] = np.clip(pos[0], min_x, max_x)
        pos[1] = np.clip(pos[1], min_y, max_y)
        pos[2] = np.clip(pos[2], min_z * ZScale, max_z * ZScale)

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
                gf, rel = compute_grad_force_max(
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

                        i_perpend1 = -k_bend * np.dot(s1["normal"], [ux, uy, uz])
                        s1["moment"] += i_perpend1 * np.array([ux, uy, uz])
                        i_perpend2 = -k_bend * np.dot(s2["normal"], [ux, uy, uz])
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
            if s["N_Neighbor"] >= rm_if_neighbor_below and s["N_Neighbor"] <= rm_if_neighbor_above
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


def surfels_to_mask_stack(surfels: list[dict[str, Any]], shape: tuple[int, int, int], ZScale: float) -> np.ndarray:
    """Convert a cloud of surfels to a 3D binary mask stack."""
    mask = np.zeros(shape, dtype=bool)
    nz, ny, nx = shape

    from collections import defaultdict
    z_groups = defaultdict(list)
    for s in surfels:
        z_idx = int(round(s["pos"][2] / ZScale))
        if 0 <= z_idx < nz:
            z_groups[z_idx].append(s["pos"][:2])

    for z_idx, pts in z_groups.items():
        if len(pts) < 3:
            continue
        pts_arr = np.array(pts)
        cx = np.mean(pts_arr[:, 0])
        cy = np.mean(pts_arr[:, 1])

        angles = np.arctan2(pts_arr[:, 1] - cy, pts_arr[:, 0] - cx)
        sorted_indices = np.argsort(angles)
        sorted_pts = pts_arr[sorted_indices]

        # Draw using PIL
        img = Image.new("1", (nx, ny), 0)
        draw = ImageDraw.Draw(img)
        poly_pts = [(float(p[0]), float(p[1])) for p in sorted_pts]
        draw.polygon(poly_pts, outline=1, fill=1)
        mask[z_idx] = np.array(img, dtype=bool)

    return mask
