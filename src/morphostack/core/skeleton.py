"""Topological skeletonization and Vossepoel–Smeulders perimeter metrics.

Ported from the shape-analysis toolkit (Abhinav / Soft Matter Biophysics Lab).
Used optionally for membrane-like masks where a 1-pixel closed skeleton is a
better perimeter estimator than raw contour polyline length.

Citation (when using these formulas in publications):
  [1] Shape Analysis of Biomimetic and Plasma Membrane Vesicles
      https://doi.org/10.1002/syst.202400052
  [2] Vesicle Deflation Analysis Using Confocal Microscopy
      https://pubs.acs.org/doi/10.1021/acs.jpcb.4c07431
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SkeletonMetrics:
    """Perimeter estimates from a pruned topological skeleton."""

    perimeter_px: float
    perimeter_um: float
    perimeter_naive_px: float
    perimeter_naive_um: float
    ok: bool


def generate_skeleton(binary_mask: np.ndarray) -> np.ndarray:
    """Reduce a 2D binary mask to a 1-pixel-thick topological skeleton.

    ``binary_mask`` must be boolean (True = object / membrane, False = background).
    """
    from skimage.morphology import skeletonize

    arr = np.asarray(binary_mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("generate_skeleton expects a 2D binary mask")
    if not np.any(arr):
        return np.zeros_like(arr, dtype=bool)
    return np.asarray(skeletonize(arr), dtype=bool)


def prune_skeleton(skeleton_array: np.ndarray, prune_threshold_pix: float = 1.0) -> np.ndarray:
    """Remove short terminal spurs from a skeleton via NetworkX graph pruning.

    Iteratively drops leaf branches shorter than ``prune_threshold_pix`` (edge
    weights use 8-connectivity Euclidean lengths) so a main continuous loop is
    preserved when present.
    """
    import networkx as nx

    skeleton = np.asarray(skeleton_array, dtype=bool)
    coords = np.column_stack(np.where(skeleton))
    if len(coords) == 0:
        return np.zeros_like(skeleton, dtype=bool)

    coord_set = set(map(tuple, coords.tolist()))
    graph = nx.Graph()
    graph.add_nodes_from(coord_set)

    neighbors_8 = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )

    for y, x in coords:
        for dy, dx in neighbors_8:
            ny, nx_pt = int(y) + dy, int(x) + dx
            if (ny, nx_pt) in coord_set:
                weight = float(np.sqrt(dy**2 + dx**2))
                graph.add_edge((int(y), int(x)), (ny, nx_pt), weight=weight)

    pruning_active = True
    while pruning_active:
        pruning_active = False
        endpoints = [node for node, degree in graph.degree() if degree == 1]

        for endpoint in endpoints:
            path = [endpoint]
            curr = endpoint
            prev = None

            while True:
                neighbors = list(graph.neighbors(curr))
                next_nodes = [node for node in neighbors if node != prev]
                if not next_nodes:
                    break
                next_node = next_nodes[0]

                if graph.degree(next_node) >= 3 or graph.degree(next_node) == 1:
                    path.append(next_node)
                    break
                path.append(next_node)
                prev = curr
                curr = next_node

            branch_len = 0.0
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                branch_len += float(graph[u][v]["weight"])

            if branch_len < float(prune_threshold_pix):
                nodes_to_remove = path[:-1] if graph.degree(path[-1]) >= 3 else path
                graph.remove_nodes_from(nodes_to_remove)
                pruning_active = True
                break

    pruned = np.zeros_like(skeleton, dtype=bool)
    for y, x in graph.nodes():
        pruned[y, x] = True
    return pruned


def calculate_vs_perimeter(
    pruned_skeleton: np.ndarray,
    voxel_size_um: float = 1.0,
) -> tuple[float, float]:
    """Vossepoel & Smeulders metrication-corrected perimeter from a skeleton loop.

    Returns ``(P_physical, P_naive_physical)`` both scaled by ``voxel_size_um``.
    Pixel-space equivalents are ``P / voxel_size_um`` when ``voxel_size_um > 0``.
    """
    coords = np.column_stack(np.where(np.asarray(pruned_skeleton, dtype=bool)))
    if len(coords) == 0:
        return 0.0, 0.0

    unvisited = set(map(tuple, coords.tolist()))
    ordered_chain: list[tuple[int, int]] = []

    current_pt = tuple(coords[0].tolist())
    ordered_chain.append(current_pt)
    unvisited.remove(current_pt)

    neighbors_8 = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )

    while unvisited:
        found_next = False
        for dy, dx in neighbors_8:
            ny, nx_pt = current_pt[0] + dy, current_pt[1] + dx
            if (ny, nx_pt) in unvisited:
                current_pt = (ny, nx_pt)
                ordered_chain.append(current_pt)
                unvisited.remove(current_pt)
                found_next = True
                break
        if not found_next:
            break

    ordered = np.asarray(ordered_chain, dtype=np.int64)
    if len(ordered) < 3:
        return 0.0, 0.0

    next_pts = np.roll(ordered, shift=-1, axis=0)
    deltas = next_pts - ordered

    abs_deltas = np.abs(deltas)
    step_magnitudes = np.sum(abs_deltas, axis=1)

    is_even = step_magnitudes == 1
    is_odd = step_magnitudes == 2

    n_even = int(np.sum(is_even))
    n_odd = int(np.sum(is_odd))

    prev_deltas = np.roll(deltas, shift=1, axis=0)
    is_corner = np.any(deltas != prev_deltas, axis=1)
    n_corner = int(np.sum(is_corner))

    p_pixels = (n_even * 0.980) + (n_odd * 1.406) - (n_corner * 0.091)
    p_physical = float(p_pixels * voxel_size_um)

    p_naive_pixels = float(n_even + n_odd * np.sqrt(2))
    p_naive_physical = float(p_naive_pixels * voxel_size_um)

    return p_physical, p_naive_physical


def selected_component_mask(
    binary_mask: np.ndarray,
    *,
    object_seed: tuple[int, int] | None = None,
    min_area_px: int = 16,
) -> np.ndarray:
    """Return a full-frame boolean mask for the selected connected component.

    With ``object_seed=(x, y)``, pick the component at/nearest that pixel.
    Without a seed, pick the largest component by area.
    """
    from morphostack.core.pipeline import get_connected_components

    mask = np.asarray(binary_mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("selected_component_mask expects a 2D mask")

    components = get_connected_components(mask, min_area_px=min_area_px)
    if not components:
        return np.zeros_like(mask, dtype=bool)

    chosen = None
    if object_seed is None:
        chosen = max(components, key=lambda comp: int(comp["area"]))
    else:
        height, width = mask.shape
        sx = max(0, min(width - 1, int(round(object_seed[0]))))
        sy = max(0, min(height - 1, int(round(object_seed[1]))))

        for comp in components:
            ymin, ymax, xmin, xmax = comp["bbox"]
            if ymin <= sy < ymax and xmin <= sx < xmax and comp["sub_mask"][sy - ymin, sx - xmin]:
                chosen = comp
                break

        if chosen is None:
            best_dist = float("inf")
            for comp in components:
                cx, cy = comp["centroid"]
                dist = (cx - sx) ** 2 + (cy - sy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    chosen = comp

    if chosen is None:
        return np.zeros_like(mask, dtype=bool)

    full = np.zeros_like(mask, dtype=bool)
    ymin, ymax, xmin, xmax = chosen["bbox"]
    full[ymin:ymax, xmin:xmax] = chosen["sub_mask"]
    return full


def skeletonize_component(
    binary_mask: np.ndarray,
    *,
    object_seed: tuple[int, int] | None = None,
    prune_threshold_pix: float = 1.0,
) -> np.ndarray:
    """Select a component, skeletonize, and prune spurs. Empty on failure."""
    try:
        component = selected_component_mask(binary_mask, object_seed=object_seed)
        if not np.any(component):
            return np.zeros_like(np.asarray(binary_mask, dtype=bool), dtype=bool)
        skel = generate_skeleton(component)
        if not np.any(skel):
            return np.zeros_like(component, dtype=bool)
        return prune_skeleton(skel, prune_threshold_pix=prune_threshold_pix)
    except Exception:
        arr = np.asarray(binary_mask, dtype=bool)
        return np.zeros_like(arr, dtype=bool)


def measure_skeleton(
    binary_mask: np.ndarray,
    *,
    object_seed: tuple[int, int] | None = None,
    prune_threshold_pix: float = 1.0,
    voxel_x_um: float = 1.0,
) -> tuple[np.ndarray, SkeletonMetrics]:
    """Skeletonize a selected component and compute VS perimeter metrics."""
    pruned = skeletonize_component(
        binary_mask,
        object_seed=object_seed,
        prune_threshold_pix=prune_threshold_pix,
    )
    scale = float(voxel_x_um) if voxel_x_um > 0 else 1.0
    if not np.any(pruned):
        empty = SkeletonMetrics(
            perimeter_px=0.0,
            perimeter_um=0.0,
            perimeter_naive_px=0.0,
            perimeter_naive_um=0.0,
            ok=False,
        )
        return pruned, empty

    p_um, p_naive_um = calculate_vs_perimeter(pruned, voxel_size_um=scale)
    p_px = p_um / scale if scale else 0.0
    p_naive_px = p_naive_um / scale if scale else 0.0
    ok = p_px > 0.0
    metrics = SkeletonMetrics(
        perimeter_px=float(p_px),
        perimeter_um=float(p_um),
        perimeter_naive_px=float(p_naive_px),
        perimeter_naive_um=float(p_naive_um),
        ok=ok,
    )
    return pruned, metrics
