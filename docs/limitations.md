# Limitations

MorphoStack is a **lab morphometry toolkit**. Treat outputs as exploratory until calibration, segmentation quality, and (where relevant) profile-specific validation are in place.

<p align="center">
  <img src="public/crowded-seed-concept.jpg" alt="Crowded field seeding concept" width="85%" />
</p>

## Calibration

- TIFF/LSM stacks without embedded spacing fall back to **1 × 1 × 1 µm**.
- Surface area, volume, and perimeter in µm are **not biological** under default spacing.
- CZI metadata is read when present — still confirm against the acquisition log.
- Manual overrides appear in manifests as `voxel_source: override`.

## Object selection and tracking

- Seed (circle or polygon) selects **one** connected component on the seed frame.
- Tracking uses overlap-first association across Z, with centroid-distance fallback.
- Tracking can fail when objects move quickly, touch neighbors, or leave the ROI.
- UI debug overlay and manifest `tracking` fields show per-frame centroids and losses.
- MorphoStack does **not** auto-segment every object in a crowded field.

## Profiles

| Profile | Status |
| --- | --- |
| **Vesicle** | Primary threshold-contour path + optional mesh |
| **RBC** | Same engine with RBC-oriented defaults; biconcavity/thickness metrics not validated |
| **Active surfaces** | Experimental surfel refinement — compare to threshold before paper use |

## Mesh and export

- Meshes come from marching cubes on aligned contour masks.
- Empty or tiny contours → empty/skipped mesh.
- Exported geometry uses the **active** voxel calibration; uncalibrated exports are for shape review only.
- Browser mesh preview may be decimated; use CSV/export files for numbers.

## Crowded fields

- One run targets **one seeded object**.
- Neighbor-merge warnings fire when tracked area jumps relative to the seed frame.
- Watershed pre-split (active-surfaces path) helps but does not guarantee separation of strongly touching cells.

## What MorphoStack is not (yet)

- Not a full ImageJ/Fiji replacement or multi-object instance segmenter for whole fields.
- Not a deep-learning segmentation suite (Cellpose/StarDist are intentionally out of scope as required deps).
- Not a substitute for manual scientific review of contours on publication datasets.

## Related

[troubleshooting.md](troubleshooting.md) · [active-surfaces.md](active-surfaces.md) · [metrics.md](metrics.md)
