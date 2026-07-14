# Active Surfaces Profile

Experimental **surfel-based** refinement when threshold contours are unstable.  
CLI / API name: `active_surfaces`. UI label: **Experimental — slow 3D refine**.

<p align="center">
  <img src="public/active-surfaces-sketch.jpg" alt="Active surfaces sketch" width="75%" />
</p>

## How this differs from Standard (`vesicle`)

| | **Standard** | **Experimental (active surfaces)** |
| --- | --- | --- |
| Core idea | Threshold each slice → contour (optional skeleton) | Seed a 3D surface of particles → optimize → mask → contour |
| Speed | Fast (seconds after stack is loaded) | Slow (tens of seconds to minutes) |
| Seed | Recommended on crowded fields | **Required** |
| Multi-vesicle field | Still Standard — seed the target object | Still **one** object only; not multi-label |

**Do not** switch to Experimental just because the image has many vesicles. For multi-vesicle stacks, stay on **Standard**, use **Select Object** (and optional XY crop). See [usage.md — Modes](usage.md#modes-profiles).

## When to use

- Weak or uneven membrane signal where thresholding leaks or merges neighbors **after** seeding failed under Standard.
- Single seeded object with moderate spacing from neighbors.
- After a seed isolation crop or user ROI narrows the field.

## When to avoid

- Everyday GUV/vesicle work — use **Standard** first.
- Dense touching objects without seed isolation — pre-split helps but is not guaranteed.
- Default-voxel stacks where absolute mesh size will be published.
- Fast batch jobs — full Analyze uses ~100 + 300 optimization steps; mesh preview uses reduced “fast” steps but is still heavier than threshold.

## Requirements

- An **object seed** (circle or polygon) is required (UI blocks Analyze/Mesh without it).
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
