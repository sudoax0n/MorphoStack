# LimeSeg vs Threshold — Synthetic Sphere

- Source: `in-memory synthetic sphere (r=6 µm)`
- Threshold: `100.0`
- Seed: frame `5`, center `(20.00, 20.00)`, radius `6.0` px

## Summary

| Metric | Threshold (vesicle) | LimeSeg | Delta |
| --- | ---: | ---: | ---: |
| Valid frames | 10 | 10 | — |
| Valid fraction | 1.000 | 1.000 | — |
| Mean area (µm²) | 71.2 | 57.95 | -18.6% |
| Mesh volume (µm³) | 622.1666666666666 | 323.125 | -48.1% |
| Mesh surface (µm²) | 357.65199050045214 | 542.5706008230591 | +51.7% |
| Mesh sphericity | 0.9854349725269891 | 0.41970251689516436 | -57.4% |

## Warnings

- Threshold: `likely_neighbor_merge`
- LimeSeg: `none`

## Interpretation

- Large mesh-volume deltas on crowded or touching data usually mean LimeSeg or tracking picked a different object region.
- On synthetic spheres, profiles should agree within a few percent when the seed sits on the object center.
- Treat LimeSeg as experimental until side-by-side previews look correct on your dataset.
