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

When `--mesh` / UI mesh is enabled, per-frame contour masks are stacked, optionally aligned, and meshed with **marching cubes**.

| Column | Definition | Notes |
| --- | --- | --- |
| `mesh_surface_area_um2` | Sum of triangle areas | Needs enough valid frames |
| `mesh_volume_um3` | Enclosed mesh volume | Sensitive to holes / missing slices |
| `mesh_equivalent_sphere_diameter_um` | \((6V/\pi)^{1/3}\) | Equal-volume sphere |
| `mesh_sphericity` | \(\pi^{1/3}(6V)^{2/3}/A\), capped at 1 | 1.0 ≈ sphere |

Browser mesh preview may be **decimated for speed**. Trust CSV mesh columns (and exported mesh files) for numbers; use the viewer for QC.

## Frame exclusion

Exclude bad slices via UI or repeated `--exclude-frame INDEX`.

Excluded frames:

- remain listed in CSV when present, with exclusion flag
- are **omitted** from valid-frame summaries, 3D mesh assembly, and mask/mesh exports

## Profile notes

| Profile | Metrics engine | Caveat |
| --- | --- | --- |
| `vesicle` | Threshold contours + optional seed tracking | Primary path |
| `rbc` | Same contour engine | No validated biconcavity/thickness suite yet |
| `active_surfaces` | Surfel refinement → masks → same metric layer | Experimental; compare to threshold |

## Related

[methods.md](methods.md) · [limitations.md](limitations.md) · [validation.md](validation.md)
