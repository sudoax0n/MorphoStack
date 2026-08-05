# Metrics Reference

MorphoStack reports **per-frame 2D contour metrics** and optional **3D mesh measurements**. All physical units depend on verified voxel calibration.

<p align="center">
  <img src="public/vesicle-glow.jpg" alt="Vesicle concept" width="320" />
  &nbsp;
  <img src="public/mesh-3d.jpg" alt="Mesh concept" width="320" />
</p>

## Voxel calibration

| Situation | `voxel_source` | How to treat µm columns |
| --- | --- | --- |
| Metadata from file | `metadata` | Confirm against acquisition log |
| User override | `override` | Your responsibility |
| Missing both | `default` (1×1×1 µm) | **Not biological** — geometry in placeholder units |

- `area_um2` and planar lengths scale with **X/Y** spacing.
- Mesh volume/surface also use **Z** spacing.
- Pixel columns (`*_px*`) are independent of calibration.

## Per-frame contour metrics

Contour points are in pixel coordinates; physical metrics scale by `VoxelSize` (µm).

| Column | Definition | Notes |
| --- | --- | --- |
| `area_px2` | Polygon area in pixels | Raw segmentation size |
| `perimeter_px` | Polygon perimeter in pixels | Closed contour |
| `area_um2` | Area after scaling points by `(vx, vy)` | Projected area in µm² |
| `perimeter_um` | Sum of edge lengths with **separate** `vx` and `vy` scales | Anisotropic-safe (not a single mean scale factor) |
| `skel_perimeter_um` | Skeleton centerline length (optional) | **Isotropic XY:** Vossepoel–Smeulders metrication. **Anisotropic XY:** Euclidean step lengths with independent `vx`/`vy` (VS constants assume square pixels). All skeleton components are summed. |
| `circularity` | \(4\pi A / P^2\) using physical area/perimeter | 1.0 ≈ circle |
| `bbox_width_um`, `bbox_height_um` | Axis-aligned bbox in µm | From scaled points |
| `aspect_ratio` | major / minor bbox side | ≥ 1 |
| `elongation` | \(1 - \mathrm{minor}/\mathrm{major}\) | 0 for square bbox |
| `deformation_index` | \((L - W) / (L + W)\) | Elongation proxy |
| `extent` | area / bbox area | Fill fraction |
| `equivalent_diameter_um` | \(2\sqrt{A/\pi}\) | Equal-area circle |
| `solidity` | area / convex-hull area (physical) | Concavity proxy |

Frames with no valid contour omit metric values or carry analysis warnings depending on export path. Excluded frames can appear with `excluded=true` (see below).

## 3D mesh metrics

When `--mesh` / UI mesh is enabled, MorphoStack rasterizes the filled contours
into a 3D mask and measures a calibrated, **unaligned** Lewiner marching-cubes
surface. These mesh measurements are the primary 3D surface-area and volume
results: the stack keeps its acquired XY positions and uses the active `(z, y,
x)` voxel spacing.

| Column | Definition | Notes |
| --- | --- | --- |
| `mesh_surface_area_um2` | Sum of triangle areas | Needs enough valid frames |
| `mesh_volume_um3` | Enclosed mesh volume | Sensitive to holes / missing slices |
| `mesh_equivalent_sphere_diameter_um` | \((6V/\pi)^{1/3}\) | Equal-volume sphere |
| `mesh_sphericity` | \(\pi^{1/3}(6V)^{2/3}/A\), capped at 1 | 1.0 ≈ sphere |
| `slice_integrated_volume_um3` | Trapezoidal integration of calibrated 2D slice areas through Z | Volume cross-check, not the primary 3D volume |
| `mesh_slice_volume_relative_difference` | Relative difference between mesh and slice-integrated volume | QC signal; review differences above 5% |

The slice-area cross-check uses
\(\sum_i \tfrac{A_i + A_{i+1}}{2}\Delta z\). It is withheld rather than
bridging an internal missing contour, and it does **not** estimate membrane
surface area. In particular, `sum(perimeter_i * dz)` is not a valid
surface-area measurement for a curved, closed vesicle.

Browser mesh preview defaults to full voxel sampling (`x1`): with an active
Z step of 0.5 µm, the preview is sampled at 0.5 µm in Z. To remain responsive,
the renderer may show a simplified set of faces. Surface area and volume are
measured from the complete marching-cubes triangulation before that display
simplification; use the viewer for QC, not manual measurement.
## Frame exclusion

Exclude bad slices via UI or repeated `--exclude-frame INDEX`.

Excluded frames:

- remain listed in CSV when present, with exclusion flag
- are **omitted** from valid-frame summaries, 3D mesh assembly, and mask/mesh exports

## Profile notes

| Profile | Metrics engine | Caveat |
| --- | --- | --- |
| `vesicle` (UI: **Standard**) | Threshold contours + optional seed tracking + optional skeleton | Default for single **and** multi-vesicle (seed the target) |
| `rbc` (UI: **RBC**) | Topology occupancy + capability QC | Engineering: projected L/W & static elongation; volume only under `3D_OCCUPANCY_VALIDATED`. **Not lab-certified.** Estimated model and dimple/rim thickness WITHHELD (Phase 5). |
| `active_surfaces` (UI: **Experimental**) | Surfel refinement → masks → same metric layer | Slow single-object fallback; not multi-label |

## Related

[methods.md](methods.md) · [limitations.md](limitations.md) · [validation.md](validation.md)
