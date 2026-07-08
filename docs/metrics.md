# MorphoStack Metrics

MorphoStack reports per-frame 2D contour metrics and optional 3D mesh measurements. All physical units depend on verified voxel calibration.

## Voxel calibration

- `area_um2`, `perimeter_um`, and mesh outputs scale with X/Y voxel size.
- Z-aware mesh measurements also use Z voxel spacing.
- Default `1×1×1 µm` is a placeholder only; treat those values as uncalibrated.

## Per-frame contour metrics

| Metric | Formula / definition | Notes |
| --- | --- | --- |
| `area_px2` | OpenCV contour area in pixels | Raw segmentation output |
| `perimeter_px` | OpenCV contour perimeter in pixels | Raw segmentation output |
| `area_um2` | `area_px2 × voxel_x × voxel_y` | Projected membrane area |
| `perimeter_um` | `perimeter_px × mean(voxel_x, voxel_y)` | Contour perimeter |
| `circularity` | `4π × area / perimeter²` | 1.0 for a perfect circle |
| `bbox_width_um`, `bbox_height_um` | Axis-aligned bounding box in µm | From contour bounds |
| `aspect_ratio` | `max(width, height) / min(width, height)` | ≥ 1 |
| `elongation` | `1 - min(width, height) / max(width, height)` | 0 for square bbox |
| `deformation_index` | `(L - W) / (L + W)` using bbox axes | RBC-style elongation proxy |
| `extent` | `area / bbox_area` | Fill fraction of bbox |
| `equivalent_diameter_um` | `2 × sqrt(area_um2 / π)` | Diameter of equal-area circle |
| `solidity` | `area / convex_hull_area` | Concavity proxy |

## 3D mesh metrics

Meshes are built by rasterizing per-frame contours, aligning slice centroids, and running marching cubes.

| Metric | Formula / definition | Notes |
| --- | --- | --- |
| `mesh_surface_area_um2` | Sum of triangle areas from marching-cubes mesh | Requires valid contours across Z |
| `mesh_volume_um3` | Enclosed volume of marching-cubes mesh | Sensitive to missing slices |
| `mesh_equivalent_sphere_diameter_um` | `(6V / π)^(1/3)` | Sphere with same volume |
| `mesh_sphericity` | `π^(1/3) (6V)^(2/3) / A`, capped at 1 | 1.0 for a perfect sphere |

## Frame exclusion

Users can exclude bad slices before trusting summary statistics or mesh output. Excluded frames remain visible in CSV output with `excluded=true`, but they are omitted from:

- valid-frame summaries
- 3D mesh assembly
- exported mask/mesh files

## Profile notes

- `vesicle`: default threshold-contour pipeline with optional object seed tracking.
- `rbc`: same contour engine with RBC-oriented reporting; mesh outputs remain exploratory unless calibration and segmentation quality are verified.
- `limeseg`: experimental active-surfaces refinement; use only when threshold contours fail on touching objects.