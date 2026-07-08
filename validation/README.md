# MorphoStack Validation

This directory contains all real-data validation artefacts for MorphoStack.

## Purpose

Validate that MorphoStack produces correct, reproducible outputs on real microscopy
data before any further development. Establish a baseline that can be compared
against as the codebase evolves.

## Structure

```
validation/
├── README.md              # This file
├── research-notes.md      # External library survey (licenses, reuse guidance)
├── runs/                  # One subdirectory per validation run
│   ├── dopc-smoke-test/   # First real-data run on the DOPC movie
│   ├── dopc-seeded-object/ # DOPC with explicit GUV seed
│   ├── czi-1650-crowded-two-objects/
│   ├── czi-1644-crowded-two-objects/
│   ├── rbc-image46-crowded-two-objects/
│   ├── rbc-image32-crowded-two-objects/
│   ├── synthetic-sphere/  # Known-geometry sphere regression
│   ├── synthetic-ellipsoid/ # Known-geometry ellipsoid regression
│   └── synthetic-touching-failure/ # Documented threshold-merge negative case
│       ├── metrics.csv
│       ├── manifest.json
│       └── report.md
├── reports/               # Comparison and checklist reports
│   └── dopc-vs-reference.md
└── data-notes/            # Notes about specific datasets
    └── dopc-movie1.md
```

## Primary Test Dataset

| Item | Value |
|------|-------|
| File | `syst202400052-sup-0001-movie1-dopc.tif` |
| Location | `D:\lab-data\paper-data\` |
| Stack shape | 26 frames x 447 x 318 px |
| Voxel source | **default (1.0 um)** -- no calibration in file metadata |
| Paper DOI | https://doi.org/10.1002/syst.202400052 |

**Calibration disclaimer:** Surface area and volume are computational outputs
using the configured voxel size (currently 1.0 um default). Biological
interpretation requires verified microscope calibration from the original
acquisition metadata or instrument log.

## Running Validation

```powershell
# From D:\MorphoStack
.\scripts\validate_dopc.ps1
python scripts\validate_synthetic.py
python scripts\validate_synthetic_ellipsoid.py
python scripts\validate_synthetic_touching.py
python scripts\validate_crowded.py
python scripts\validate_crowded.py --only czi-1644-crowded-two-objects rbc-image32-crowded-two-objects
python scripts\validate_dopc_seeded.py
python scripts\capture_validation_previews.py
python scripts\validate_all.py
python scripts\compare_active_surfaces_threshold.py
```

Active surfaces vs threshold comparison reports are written to `validation/reports/active-surfaces-vs-threshold-*.md`.

See `scripts/validate_dopc.ps1` for full details.

## Comparison Checklist

See `reports/dopc-vs-reference.md` for the item-by-item comparison against
`D:\Shape-Analysis` and `D:\tanmays original code`.

## Useful CLI Commands

```powershell
# Inspect a stack (metadata + shape)
.\.venv\Scripts\morphostack inspect "D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif"

# Suggest threshold (Otsu)
.\.venv\Scripts\morphostack threshold "D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif" --method otsu

# Full analysis with 3D mesh
.\.venv\Scripts\morphostack analyze "D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif" `
    --threshold 30 --mesh --bundle-dir validation\runs\dopc-smoke-test

# Threshold sweep (sensitivity check)
.\.venv\Scripts\morphostack sweep "D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif" `
    --start 20 --stop 80 --step 10 --out validation\runs\dopc-smoke-test\sweep.csv
```
