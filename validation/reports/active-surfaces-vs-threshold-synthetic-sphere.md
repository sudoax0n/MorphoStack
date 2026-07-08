# Active Surfaces vs Threshold — Synthetic Sphere

- Source: `in-memory synthetic sphere (r=6 µm)`
- Threshold: `100.0`
- Seed: frame `5`, center `(20.00, 20.00)`, radius `6.0` px

## Summary

| Metric | Threshold (vesicle) | Active Surfaces | Delta |
| --- | ---: | ---: | ---: |
| Valid frames | 10 | 10 | — |
| Valid fraction | 1.000 | 1.000 | — |
| Mean area (µm²) | 71.2 | 78.05 | +9.6% |
| Mesh volume (µm³) | 622.1666666666666 | 570.25 | -8.3% |
| Mesh surface (µm²) | 357.65199050045214 | 696.656116569129 | +94.8% |
| Mesh sphericity | 0.9854349725269891 | 0.47735616147667004 | -51.6% |

## Warnings

- Threshold: `likely_neighbor_merge`
- Active Surfaces: `none`

## Interpretation

- Large mesh-volume deltas on crowded or touching data usually mean Active Surfaces or tracking picked a different object region.
- On synthetic spheres, profiles should agree within a few percent when the seed sits on the object center.
- Treat Active Surfaces as experimental until side-by-side previews look correct on your dataset.
