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

## Profiles (modes)

| Profile (CLI) | UI label | Status |
| --- | --- | --- |
| **vesicle** | Standard | Primary threshold-contour path + optional skeleton/mesh. Use for **single** and **multi-vesicle** fields (seed the target object). |
| **rbc** | RBC | One selected cell; verified X/Y/Z required. Engineering capability ladder active (preview → 2D → occupancy QC). **Biological validation of 2D/3D, estimated model, and surface/thickness remain WITHHELD** until lab evidence bundle + thresholds are accepted (`validation/reports/rbc-capability-decision-v1.md`). |
| **active_surfaces** | Experimental | Surfel refinement — slow, seed required, still one object. Not “multi mode.” Compare to Standard before paper use. |

Choosing Experimental does not analyze every vesicle in the FOV. Multi-object fields still need one seed per run under Standard (or Experimental). See [usage.md — Modes](usage.md#modes-profiles).

## Mesh and export

- Primary 3D surface area and volume come from a calibrated, **unaligned**
  Lewiner marching-cubes mesh of the filled contour stack. The calculation
  preserves acquired XY positions and uses the active `(z, y, x)` voxel
  spacing.
- Empty or tiny contours → empty/skipped mesh.
- Missing contours, incomplete stack coverage, or poor segmentation can still
  bias 3D measurements; inspect the contour and mesh QC views.
- `slice_integrated_volume_um3` is a trapezoidal integration of the calibrated
  enclosed 2D areas through Z. It is a volume cross-check only, and is withheld
  when there is an internal missing contour rather than silently bridging it.
- Do **not** use `sum(perimeter * dz)` as membrane surface area. It ignores
  sloped curvature between slices and systematically underestimates a sphere.
- Exported geometry uses the **active** voxel calibration; uncalibrated exports are for shape review only.
- The browser preview uses full voxel sampling (`x1`, so a 0.5 µm active Z step
  remains 0.5 µm). Its rendered faces may be simplified for responsiveness;
  reported surface area and volume come from the complete triangulation before that display simplification.

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
