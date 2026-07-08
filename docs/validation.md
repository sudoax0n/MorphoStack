# Validation

Regression and lab-check artifacts live under `validation/`. Each intentional run should include `manifest.json`, metrics CSV, and usually `report.md` (plus optional mesh/preview).

<p align="center">
  <img src="public/preview-dopc-seed.png" alt="DOPC validation preview" width="220" />
  <img src="public/preview-crowded-czi.png" alt="Crowded CZI preview" width="220" />
  <img src="public/preview-rbc-seed.png" alt="RBC preview" width="220" />
</p>

<p align="center"><sub>Example seed-frame previews from tracked validation runs</sub></p>

## Quick health checks

```bash
morphostack doctor
pytest -q
cd apps/web && npm run build
```

Optional heavy tests that load large real files:

```bash
pytest -m slow
```

## Synthetic geometry

```bash
python scripts/validate_synthetic.py
python scripts/validate_synthetic_ellipsoid.py
python scripts/validate_synthetic_touching.py
```

Outputs under:

- `validation/runs/synthetic-sphere/`
- `validation/runs/synthetic-ellipsoid/`
- `validation/runs/synthetic-touching-failure/` (negative / hard case)

Sphere and ellipsoid regressions should **PASS** within their configured tolerances.

## Crowded real stacks

```bash
python scripts/validate_crowded.py
```

Creates multi-object seed runs such as:

- `validation/runs/czi-1650-crowded-two-objects/`
- `validation/runs/rbc-image46-crowded-two-objects/`

Each object folder records threshold, profile, seed, Z range, voxel source, tracking diagnostics, and mesh path in `manifest.json`.

## DOPC

```bash
# PowerShell helper
./scripts/validate_dopc.ps1
# or seeded variant
python scripts/validate_dopc_seeded.py
```

See `validation/data-notes/dopc-movie1.md` and [citations.md](citations.md) for dataset attribution.

## Aggregate report

```bash
python scripts/validate_all.py
```

Writes `validation/reports/validation-all.md` (and JSON companion).

## Active surfaces vs threshold

```bash
python scripts/compare_active_surfaces_threshold.py
```

Reports land in `validation/reports/active-surfaces-vs-threshold-*.md`.

## Compare two CSV exports

```bash
morphostack validate reference_metrics.csv new_metrics.csv --tolerance 0.000001
morphostack validate ref_batch.csv new_batch.csv --key-column source_path --all-columns
```

CSV validation proves **numeric regression stability**, not biological truth, unless the reference is a curated lab standard.

## What to inspect in a run

1. **`voxel_source`** — never treat `default` as calibrated biology.
2. **`object_seed` / `tracking`** — same object for preview, analyze, mesh.
3. **`warnings`** — `default_voxel_size`, `tracking_lost_*`, `roi_boundary_touch`, `likely_neighbor_merge`.
4. Crowded pairs — distinct mean `area_um2` for object A vs B when both are real separate objects.
5. Preview PNGs — human visual QC.

## Related

[troubleshooting.md](troubleshooting.md) · [limitations.md](limitations.md) · [methods.md](methods.md)
