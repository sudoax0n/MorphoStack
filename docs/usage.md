# Usage Guide

How to run MorphoStack day-to-day: browser UI and CLI. For install, see [getting-started.md](getting-started.md).

<p align="center">
  <img src="public/pipeline-concept.jpg" alt="Z-stack to mesh pipeline" width="90%" />
</p>

## Modes (profiles)

The UI **Mode** selector maps to CLI `--profile` names. MorphoStack always analyzes **one object per run** (or the largest blob if you do not seed). It does **not** automatically label every vesicle in a field.

| UI label | CLI `--profile` | What it does | Use for |
| --- | --- | --- | --- |
| **Standard — GUVs / vesicles** | `vesicle` | **With Select Object:** seeded lumen/outside segmentation (random walker) + Z centroid propagation (research-backed). **Without seed:** threshold + largest component. Optional skeleton. | Default for single or multi-vesicle stacks |
| **Red blood cells (RBC)** | `rbc` | Same contour engine as Standard; RBC-oriented defaults | RBC / erythrocyte stacks |
| **Experimental — slow 3D refine** | `active_surfaces` | Seeded surfel optimization → mask → contour → metrics / mesh | Only when Standard cannot lock a weak or leaky membrane |

### Single vesicle vs multi-vesicle (which mode?)

| Situation | Mode | Why |
| --- | --- | --- |
| **One vesicle** alone in the FOV | **Standard** | Threshold + contour is enough; seed optional |
| **Many vesicles** (crowded CZI) — you want **one** of them | **Standard** + **Select Object** (and optional crop box) | Mode is still Standard; isolation is seed/ROI, not Experimental |
| **RBC** stack | **RBC** | Same engine; choose RBC so runs are labeled correctly |
| Threshold merges neighbors or membrane is too broken | **Experimental** *after* Select Object | Slow 3D refine; still one object only — [active-surfaces.md](active-surfaces.md) |

**Important:** “Multi-vesicle” does **not** mean switch to Experimental. Multi means: stay on **Standard**, click **Select Object** on the vesicle you care about, optionally drag an XY crop, then Analyze / mesh.

**Tracking notes (Standard + seed):**

- Preview and Analyze **track** the seeded object across Z (overlap + area consistency). They do not keep a fixed click coordinate that can fall into a neighbor hole or merge.
- Selection prefers components whose **exterior contour contains** the seed (works for hollow GUV rings) and **rejects** merge-sized blobs / dust relative to the seed-frame area.
- Red overlay in preview is the **selected object only** when a seed is set (not every thresholded vesicle in the field).
- If the object is lost mid-stack (touching neighbors, huge area jump), later frames stop claiming a false contour rather than painting a multi-vesicle cluster. Re-seed on a clearer slice or tighten the crop.

```text
Recommended lab path
  Mode = Standard
  → Inspect stack
  → Select Object on target vesicle (required if more than one bright object)
  → Threshold + Preview
  → Analyze (CSV) / View 3D Mesh
```

### What each mode is *not*

- **Standard / RBC** are not “measure every object in the image at once.” Use batch later or re-run with a new seed for another object.
- **Experimental** is not faster and not multi-object. It is a heavier single-object alternative when threshold contours fail. Mesh preview uses reduced optimization steps; full Analyze uses quality defaults.

## Browser UI workflow

Start with `morphostack dev` (port **5173**) or `morphostack app` (port **8000**).

### 1. Stack & calibration

1. Prefer **Stack path** for large CZI/TIFF files (avoids re-upload). Or Choose File and **Inspect once** (server keeps a session).
2. Calibration:
   - **Auto** — metadata when present
   - **Manual override** — known microscope spacing
   - **Default 1×1×1 µm** — UI marks this as uncalibrated; do not treat µm values as biology
3. Click **Inspect** — confirm shape and voxel source badge.

### 2. Preview & object selection

1. Leave **Mode** on **Standard** unless you have a reason to change it (see above).
2. **Select Object** on the vesicle (circle-drag or polygon). Required for Experimental; strongly recommended on crowded fields for Standard/RBC.
3. Optional **Z range** (`start` inclusive, `stop` exclusive) to drop empty top/bottom slices.
4. Optional **XY crop** — drag a rectangle on preview when not in Select Object mode.
5. Scrub the frame slider; **Suggest Threshold** → **Preview**. Optional **Enable skeleton** for centerline perimeter.

### 3. Analyze & export

1. **Analyze** — read warnings (`default_voxel_size`, tracking loss, neighbor merge).
2. Optional **Include 3D mesh in Analyze** and/or **View 3D Mesh** (Plotly; may be decimated for speed).
3. Download **CSV**, **manifest**, and **report**.
4. Advanced: tracked-centroid debug overlay after Analyze.

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
