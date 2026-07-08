# Active Surfaces vs Threshold — DOPC Movie 1

- Source: `D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif`
- Threshold: `127.0`
- Seed: frame `13`, center `(209.00, 419.00)`, radius `12.0` px

## Summary

| Metric | Threshold (vesicle) | Active Surfaces | Delta |
| --- | ---: | ---: | ---: |
| Valid frames | 26 | 26 | — |
| Valid fraction | 1.000 | 1.000 | — |
| Mean area (µm²) | 303.0 | 164.01923076923077 | -45.9% |
| Mesh volume (µm³) | 6791.666666666667 | 4120.666666666667 | -39.3% |
| Mesh surface (µm²) | 5270.710678118656 | 6770.633027935773 | +28.5% |
| Mesh sphericity | 0.32905300067526777 | 0.18358329992797406 | -44.2% |

## Warnings

- Threshold: `default_voxel_size`
- Active Surfaces: `default_voxel_size`

## Interpretation

- Large mesh-volume deltas on crowded or touching data usually mean Active Surfaces or tracking picked a different object region.
- On synthetic spheres, profiles should agree within a few percent when the seed sits on the object center.
- Treat Active Surfaces as experimental until side-by-side previews look correct on your dataset.
