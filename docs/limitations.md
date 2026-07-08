# MorphoStack Limitations

MorphoStack is a lab prototype for vesicle and RBC shape analysis. Treat outputs as exploratory unless validation artifacts and calibration are in place.

## Calibration

- TIFF and LSM stacks without embedded spacing fall back to **1 × 1 × 1 µm**. Surface area, volume, and perimeter in micrometers are **not biological** in that case.
- CZI metadata is read when present, but always confirm against the acquisition log.
- Manual overrides are stored in manifests and reports as `voxel_source: override`.

## Object selection and tracking

- Seed point or polygon selects one connected component on the seed frame.
- Tracking follows overlap-first connected components across Z, with centroid-distance fallback.
- Tracking can fail when objects move quickly, touch neighbors, or leave the ROI.
- The UI debug overlay and manifest `tracking` field show per-frame centroids and lost frames.

## Profiles

- **Vesicle** — threshold contours with optional 3D mesh from rasterized contours.
- **RBC** — same pipeline with RBC-oriented defaults; biconcavity and thickness metrics are not validated yet.
- **Active Surfaces** — experimental surfel-based refinement. Use only when threshold contours merge neighbors or miss weak edges. Compare against threshold mesh before trusting output.

## Mesh and export

- 3D meshes come from marching cubes on aligned contour masks. Empty or tiny contours produce empty meshes.
- Exported OBJ/STL/PLY/GLB files use the active voxel calibration. Uncalibrated exports are useful for shape review, not quantitative biology.

## Crowded fields

- MorphoStack does not segment all objects automatically. Each run targets one seeded object.
- Neighbor merge warnings appear when tracked area grows sharply versus the seed frame.