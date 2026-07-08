# MorphoStack Validation Workflow

Validation runs live under `validation/runs/`. Each run should include `manifest.json`, `report.md`, and `metrics.csv` (plus optional `mesh.obj`).

## Quick checks

```powershell
.\.venv\Scripts\morphostack doctor
.\.venv\Scripts\python -m pytest -q
cd apps\web
npm run build
```

## Crowded-stack validation script

```powershell
.\.venv\Scripts\python scripts\validate_crowded.py
```

This creates:

- `validation/runs/czi-1650-crowded-two-objects/` — two vesicle seeds on CZI metadata-calibrated data
- `validation/runs/rbc-image46-crowded-two-objects/` — two RBC seeds on Image 46 LSM

Each object folder records threshold, profile, seed coordinates, Z range, voxel source, tracking diagnostics, and mesh export path in `manifest.json`.

## DOPC smoke test

```powershell
.\scripts\validate_dopc.ps1
```

## Comparing metrics

```powershell
.\.venv\Scripts\morphostack validate reference.csv new.csv
```

## What to inspect

1. `voxel_source` in manifest and report — must not be mistaken for real calibration when `default`.
2. `object_seed` and `tracking` blocks — confirm preview/analyze/mesh targeted the same object.
3. `warnings` — `default_voxel_size`, `tracking_lost_*`, `roi_boundary_touch`, `likely_neighbor_merge`.
4. Distinct `mean area_um2` between object_a and object_b in crowded runs.