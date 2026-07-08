# Usage Guide

How to run MorphoStack day-to-day: browser UI and CLI. For install, see [getting-started.md](getting-started.md).

<p align="center">
  <img src="public/pipeline-concept.jpg" alt="Z-stack to mesh pipeline" width="90%" />
</p>

## Profiles

| Profile | Use when | Notes |
| --- | --- | --- |
| `vesicle` | GUVs / membrane vesicles | Default threshold-contour path |
| `rbc` | Red blood cell stacks | Same engine; RBC-specific metrics still evolving |
| `active_surfaces` | Threshold leaks or weak edges | **Experimental**; requires object seed — [details](active-surfaces.md) |

## Browser UI workflow

Start with `morphostack dev` (port **5173**) or `morphostack app` (port **8000**).

### 1. Stack & calibration

1. Choose a `.tif`, `.tiff`, `.lsm`, or `.czi` file.
2. Calibration:
   - **Auto** — metadata when present
   - **Manual override** — known microscope spacing
   - **Default 1×1×1 µm** — UI marks this as uncalibrated; do not treat µm values as biology
3. Click **Inspect** — confirm shape and voxel source badge.

### 2. Preview & object selection

1. Pick a **profile**.
2. Optional **object seed** (crowded fields): **Select Object**, then circle-drag or polygon on the preview. Set radius / max track distance if needed.
3. Optional **Z range** (`start` inclusive, `stop` exclusive) to drop empty top/bottom slices.
4. Optional **XY ROI** — type bounds or drag a rectangle on preview.
5. Scrub the frame slider; **Suggest Threshold** → **Preview**.

### 3. Analyze & export

1. **Analyze** — read warnings (`default_voxel_size`, tracking loss, neighbor merge).
2. Optional **Include 3D mesh** → **View 3D Mesh** (Plotly; may be decimated for speed).
3. Download **CSV**, **manifest**, and **report**.
4. After analyze, **Show tracked-object debug overlay** to review centroids.

### 4. Batch & threshold sweep

- **Batch** — same settings, many stacks → summary CSV/report.
- **Threshold sweep** — start/stop/step → pick a stable threshold from the sweep table.

## CLI workflows

`morphostack` and `mst` are equivalent.

### Inspect / threshold / sweep

```bash
morphostack inspect stack.tif
morphostack threshold stack.tif --method auto
morphostack sweep stack.tif --start 50 --stop 200 --step 10 --out sweep.csv \
  --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5
```

### Analyze one stack

```bash
morphostack analyze stack.tif \
  --threshold 100 \
  --profile vesicle \
  --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5 \
  --z-range 5 30 \
  --out metrics.csv --report --mesh \
  --mesh-export mesh.obj
```

Crowded object:

```bash
morphostack analyze crowded.czi \
  --threshold 190 \
  --seed-x 360 --seed-y 517 --seed-frame 105 \
  --seed-radius 10 \
  --mesh --mesh-export mesh.obj \
  --bundle-dir runs
```

Exclude bad frames:

```bash
morphostack analyze stack.tif --threshold 100 --exclude-frame 3 --exclude-frame 12 --out metrics.csv
```

### Project settings

```bash
morphostack project init --out morphostack.project.json \
  --profile vesicle --threshold 100 \
  --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5

morphostack analyze stack.tif --project morphostack.project.json --out metrics.csv --report
```

CLI flags override project file values.

### Batch folder

```bash
morphostack batch path/to/stacks --threshold 100 --out batch_summary.csv --bundle-dir runs
# add --recursive for subfolders
```

### Validate regression CSVs

```bash
morphostack validate reference_metrics.csv new_metrics.csv --tolerance 0.000001
morphostack validate ref_batch.csv new_batch.csv --key-column source_path --all-columns
```

## Outputs checklist

| File | Purpose |
| --- | --- |
| `metrics.csv` | Per-frame metrics ([definitions](metrics.md)) |
| `*.manifest.json` | SHA-256, profile, threshold, seed, voxel source, warnings |
| `*.report.md` | Lab-readable summary |
| `mesh.obj` / STL / PLY / GLB | 3D surface geometry |
| mask TIFF | Binary contour stack export |

## Presentation talking points

> MorphoStack is a local morphometry toolkit: inspect stacks, set calibration, seed objects in crowded fields, preview thresholds, export quantitative CSVs, manifests, and 3D meshes.

Be explicit about RBC:

> The RBC profile currently shares the vesicle threshold-contour engine. Domain-specific RBC metrics still need lab validation.

Be explicit about default voxels:

> Without metadata or overrides, physical units use 1×1×1 µm placeholders and must not be reported as calibrated biology.

## Related

- [limitations.md](limitations.md) · [troubleshooting.md](troubleshooting.md) · [validation.md](validation.md)
