---
title: RBC confocal morphometry must separate measured and estimated outputs
date: 2026-08-04
category: best-practices
module: rbc-morphometry
problem_type: best_practice
component: documentation
severity: high
applies_when:
  - Reconstructing one RBC from a confocal Z-stack
  - Reporting calibrated RBC volume, surface area, thickness, or biconcavity
tags: [rbc, confocal, morphometry, calibration, topology, validation]
---

# RBC confocal morphometry must separate measured and estimated outputs

## Context

The current RBC path largely shares the vesicle contour pipeline, while a red blood cell's central depression requires topology that one filled outer contour per slice cannot preserve. The supplied scientific review is the evidence base for the planned RBC work, not proof that the current implementation already meets these requirements.

## Guidance

- Treat `researches/rbc-confocal-z-stack-morphometry-deep-research-2026-08-04.md` as the canonical research source for the RBC plan.
- Optimize for one deliberately selected RBC rather than simultaneous field-wide quantification.
- Preserve inner and outer boundary loops or reconstruct separate upper and lower surfaces. Do not infer a measured biconcavity from a stack of filled outer silhouettes.
- Refuse calibrated physical outputs from `.lsm` input until the user supplies either a metadata-preserving TIFF/OME-TIFF conversion or manual voxel calibration.
- Gate measured volume, surface area, thickness, and biconcavity on acquisition sufficiency, complete cell coverage, valid calibration, segmentation confidence, and mesh or occupancy QC.
- When measured biconcavity is not supported, show the limitation first and only then offer a model-based result labeled `ESTIMATED`. Keep estimated values separate from measured values in the UI and exports.
- Call static shape measures `aspect_ratio_L_over_W` and `static_elongation_index`; do not label them as mechanical deformability without a stress-controlled experiment.
- Validate with synthetic phantoms, annotated real Zeiss stacks, and instrument checks. Synthetic tests verify controlled geometry and edge cases but do not establish biological accuracy by themselves.

## Why This Matters

An outer-contour-only reconstruction can plug the RBC dimple, inflate volume, distort surface area, and produce visually plausible but scientifically misleading meshes. Capability gates make unavailable measurements explicit and keep a transparent model estimate from being confused with an observation.

## When to Apply

- Any RBC-specific segmentation, contour, meshing, metric, report, export, or viewer change.
- Any decision about whether a stack supports 2D morphometry, coarse 3D occupancy, or membrane-resolving 3D surface morphometry.
- Any validation claim about RBC accuracy or reliability.

## Examples

- A calibrated, complete, membrane-resolving stack that passes topology and mesh checks may report measured 3D metrics with QC metadata.
- A stack that shows the selected RBC but does not resolve both surfaces may report supported 2D or coarse 3D results, show a disclaimer, and optionally render a separate estimated biconcave model.
- An `.lsm` file without accepted calibration must not produce physical measurements; the user is asked for a metadata-preserving conversion or manual voxel spacing.

## Related

- `researches/rbc-confocal-z-stack-morphometry-deep-research-2026-08-04.md`
- `improvements.md`
- `docs/limitations.md`
