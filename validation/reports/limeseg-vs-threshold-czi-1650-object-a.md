# LimeSeg vs Threshold — Crowded CZI 1650 (object A)

- Source: `C:\Users\systemm\Downloads\1650_z stack.czi`
- Threshold: `190.0`
- Seed: frame `105`, center `(359.97, 516.78)`, radius `12.0` px

## Summary

| Metric | Threshold (vesicle) | LimeSeg | Delta |
| --- | ---: | ---: | ---: |
| Valid frames | 30 | 30 | — |
| Valid fraction | 1.000 | 1.000 | — |
| Mean area (µm²) | 2752.102950087345 | 6.763932946382071 | -99.8% |
| Mesh volume (µm³) | 40267.56602677844 | 109.93593621133961 | -99.7% |
| Mesh surface (µm²) | 90311.7536423048 | 160.9162755743226 | -99.8% |
| Mesh sphericity | 0.0629086118554494 | 0.6896741342853312 | +996.3% |

## Warnings

- Threshold: `roi_boundary_touch`
- LimeSeg: `none`

## Interpretation

- Large mesh-volume deltas on crowded or touching data usually mean LimeSeg or tracking picked a different object region.
- On synthetic spheres, profiles should agree within a few percent when the seed sits on the object center.
- Treat LimeSeg as experimental until side-by-side previews look correct on your dataset.
