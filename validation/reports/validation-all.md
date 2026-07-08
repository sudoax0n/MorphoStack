# MorphoStack Validation Summary

- Generated: `2026-07-08T17:46:05.027712+00:00`
- Synthetic sphere regression: `PASS`
- Synthetic ellipsoid regression: `PASS`
- Validation runs indexed: `13`

## Synthetic Sphere

```text
MorphoStack CSV Validation
==========================
Expected: D:\MorphoStack\validation\runs\synthetic-sphere\reference-metrics.csv
Actual: D:\MorphoStack\validation\runs\synthetic-sphere\metrics.csv
Tolerance: 0.05
Rows compared: 10
Cells compared: 40
Result: PASS
```

## Synthetic Ellipsoid

```text
MorphoStack CSV Validation
==========================
Expected: D:\MorphoStack\validation\runs\synthetic-ellipsoid\reference-metrics.csv
Actual: D:\MorphoStack\validation\runs\synthetic-ellipsoid\metrics.csv
Tolerance: 0.08
Rows compared: 12
Cells compared: 48
Result: PASS
```

## Preview Capture

```text
(not run)
```

## Validation Runs

| Manifest | Profile | Valid frames | Preview PNG |
| --- | --- | ---: | --- |
| `czi-1644-crowded-two-objects\object_a_center\1644_z_stack\manifest.json` | `vesicle` | 40 | yes |
| `czi-1644-crowded-two-objects\object_b_corner\1644_z_stack\manifest.json` | `vesicle` | 40 | yes |
| `czi-1650-crowded-two-objects\object_a_left\1650_z_stack\manifest.json` | `vesicle` | 30 | yes |
| `czi-1650-crowded-two-objects\object_b_right\1650_z_stack\manifest.json` | `vesicle` | 30 | yes |
| `dopc-seeded-object\seeded_guv\syst202400052-sup-0001-movie1-dopc\manifest.json` | `vesicle` | 26 | yes |
| `dopc-smoke-test\syst202400052-sup-0001-movie1-dopc\manifest.json` | `vesicle` | 26 | yes |
| `rbc-image32-crowded-two-objects\object_a_center\Image_32\manifest.json` | `rbc` | 16 | yes |
| `rbc-image32-crowded-two-objects\object_b_right\Image_32\manifest.json` | `rbc` | 19 | yes |
| `rbc-image46-crowded-two-objects\object_a_lower\Image_46\manifest.json` | `rbc` | 10 | yes |
| `rbc-image46-crowded-two-objects\object_b_upper\Image_46\manifest.json` | `rbc` | 13 | yes |
| `rbc-image46-smoke-test\Image_46\manifest.json` | `rbc` | 25 | yes |
| `synthetic-ellipsoid\manifest.json` | `vesicle` | 0 | no |
| `synthetic-sphere\manifest.json` | `vesicle` | 0 | no |
