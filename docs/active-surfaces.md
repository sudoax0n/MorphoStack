# Active Surfaces Profile

Experimental **surfel-based** refinement when threshold contours are unstable. Profile name: `active_surfaces`.

<p align="center">
  <img src="public/active-surfaces-sketch.jpg" alt="Active surfaces sketch" width="75%" />
</p>

## When to use

- Weak or uneven membrane signal where thresholding leaks into neighbors.
- Single seeded object with moderate spacing from neighbors.
- After an ROI crop narrows the field.

## When to avoid

- Dense touching objects without ROI isolation — pre-split helps but is not guaranteed.
- Default-voxel stacks where absolute mesh size will be published.
- Fast batch jobs — optimization is intentionally slower than threshold contours (~1–2 minutes per stack is common).

## Requirements

- An **object seed** (circle or polygon) is required.
- Prefer verified voxel calibration for any quantitative mesh claim.

## Default optimization parameters

Defaults live in `ACTIVE_SURFACES_DEFAULTS` (`src/morphostack/core/active_surfaces.py`):

| Parameter | Typical default | Role |
| --- | ---: | --- |
| `k_grad` | 0.05 | Image-gradient force |
| `f_pressure` | 0.02 | Outward normal pressure |
| `optimization_steps` | 300 | Steps after relaxation |
| `d_0` | 2.0 | Surfel spacing (pixels) |

On synthetic spheres, defaults often track threshold mesh volume within ~10%. Crowded real stacks may still diverge — always compare side-by-side.

## CLI example

```bash
morphostack analyze stack.tif \
  --profile active_surfaces \
  --threshold 100 \
  --seed-x 200 --seed-y 180 --seed-frame 10 \
  --mesh --mesh-export mesh_as.obj \
  --out metrics_as.csv --report
```

## Validation status

**Experimental.** Compare against threshold-based mesh on the same seed before figures or tables.

Side-by-side reports under `validation/reports/`:

```bash
python scripts/compare_active_surfaces_threshold.py
python scripts/compare_active_surfaces_threshold.py --skip-crowded   # faster
```

Unit coverage: `tests/test_core_active_surfaces.py`.

## Related

[limitations.md](limitations.md) · [validation.md](validation.md) · [usage.md](usage.md)
