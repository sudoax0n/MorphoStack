# Active Surfaces vs Threshold — Crowded RBC Image 46 (object A)

- Source: `D:\rbc data pranay\Image 46.lsm`
- Threshold: `43.0`
- Seed: frame `10`, center `(290.61, 731.79)`, radius `12.0` px

## Summary

| Metric | Threshold (rbc) | Active Surfaces | Delta |
| --- | ---: | ---: | ---: |
| Valid frames | 10 | 22 | — |
| Valid fraction | 0.357 | 0.786 | — |
| Mean area (µm²) | 2274.55 | 152.5681818181818 | -93.3% |
| Mesh volume (µm³) | 23610.791666666668 | 3586.0833333333335 | -84.8% |
| Mesh surface (µm²) | 7977.764532303003 | 3054.923285191493 | -61.7% |
| Mesh sphericity | 0.49889590994440375 | 0.37087771111469814 | -25.7% |

## Warnings

- Threshold: `partial_contours, tracking_lost_many_frames, default_voxel_size`
- Active Surfaces: `partial_contours, default_voxel_size`

## Interpretation

- Large mesh-volume deltas on crowded or touching data usually mean Active Surfaces or tracking picked a different object region.
- On synthetic spheres, profiles should agree within a few percent when the seed sits on the object center.
- Treat Active Surfaces as experimental until side-by-side previews look correct on your dataset.
