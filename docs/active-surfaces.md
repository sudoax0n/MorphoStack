# Active Surfaces Profile Notes

MorphoStack ships an **active-surfaces** (surfel-based) segmentation profile for advanced segmentation when threshold contours are unstable.

## When to use

- Weak or uneven membrane signal where thresholding leaks into neighbors.
- Single seeded object with moderate spacing from neighbors.
- After ROI crop narrows the field.

## When to avoid

- Dense touching objects without ROI isolation — watershed pre-split helps but cannot guarantee separation.
- Default-voxel LSM stacks where quantitative mesh size matters.
- Fast batch runs — active-surfaces optimization is slower than threshold contours.

## Default optimization parameters

MorphoStack uses tuned defaults in `ACTIVE_SURFACES_DEFAULTS` (`src/morphostack/core/active_surfaces.py`):

| Parameter | Value | Notes |
| --- | ---: | --- |
| `k_grad` | 0.05 | Image-gradient force during optimization |
| `f_pressure` | 0.02 | Outward normal pressure |
| `optimization_steps` | 300 | Steps after 100-step relaxation |
| `d_0` | 2.0 | Surfels spacing (pixels) |

On synthetic spheres these defaults track threshold mesh volume within ~10%. Crowded real stacks may still diverge — always compare side-by-side previews.

Active surfaces is **slow by design** (~1–2 minutes per stack). It is optional and excluded from fast validation (`validate_synthetic_touching.py` runs threshold-only unless you pass `--with-active-surfaces`).

## Validation status

Active surfaces remains **experimental**. Compare against threshold-based mesh on the same seed before using these outputs in figures or tables.

Side-by-side reports live under `validation/reports/`:

```powershell
python scripts/compare_active_surfaces_threshold.py
python scripts/compare_active_surfaces_threshold.py --skip-crowded   # synthetic only (~30s)
```

Regression tests cover seed masks, watershed pre-split, and touching-object cases in `tests/test_core_active_surfaces.py`.