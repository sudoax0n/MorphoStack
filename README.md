# MorphoStack

MorphoStack is a planned local morphometry toolkit for microscopy Z-stacks, starting with vesicle analysis and expanding to red blood cell analysis.

The first milestone is intentionally small: prove the project structure, command ownership, and diagnostics before migrating scientific code from the older Shape-Analysis prototype.
See [improvements.md](improvements.md) for the current technical roadmap, known
gaps, and distribution plan.

## Current Commands

```bash
morphostack doctor
morphostack init
morphostack init --web
morphostack project init --out morphostack.project.json
morphostack inspect path\to\stack.tif
morphostack threshold path\to\stack.tif
morphostack sweep path\to\stack.tif --start 50 --stop 200 --step 10 --out sweep.csv
morphostack analyze path\to\stack.tif --threshold 100 --out metrics.csv
morphostack analyze path\to\stack.tif --threshold 100 --out metrics.csv --report
morphostack analyze path\to\stack.tif --threshold 100 --bundle-dir runs
morphostack analyze path\to\stack.tif --threshold 100 --profile rbc --z-range 5 30 --out metrics.csv
morphostack batch path\to\stacks --threshold 100 --out batch_summary.csv
morphostack batch path\to\stacks --threshold 100 --out batch_summary.csv --bundle-dir runs
morphostack validate reference_metrics.csv new_metrics.csv
morphostack validate reference_batch.csv new_batch.csv --key-column source_path --all-columns
morphostack serve
morphostack dev
mst doctor
```

Both commands use the same CLI entry point. `mst` is the short alias.

## Development Install

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\morphostack doctor
```

`doctor` reports OS/Python hardware details, command paths and versions for
Git/Node/npm, Python dependency availability, and whether the web app's
`node_modules` directory is installed.

To inspect the machine and optionally install the heavier analysis/API
dependencies into the active environment:

```bash
.\.venv\Scripts\morphostack init
```

Add `--web` to also install browser UI dependencies in `apps\web`:

```bash
.\.venv\Scripts\morphostack init --web
```

To inspect a stack after installing analysis dependencies:

```bash
.\.venv\Scripts\morphostack inspect path\to\stack.tif --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5
```

To create a reusable project settings file for a dataset or experiment:

```bash
.\.venv\Scripts\morphostack project init --out morphostack.project.json --profile rbc --threshold 100 --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5 --fallback-contours --sweep-start 50 --sweep-stop 200 --sweep-step 10
```

The project file is plain JSON. `analyze`, `batch`, `threshold`, `sweep`, and
`inspect` can read it with `--project morphostack.project.json`. Explicit
command-line flags override project defaults.

To suggest a starting threshold before analysis:

```bash
.\.venv\Scripts\morphostack threshold path\to\stack.tif --method auto
```

To compare several thresholds and export one summary row per threshold:

```bash
.\.venv\Scripts\morphostack sweep path\to\stack.tif --start 50 --stop 200 --step 10 --out sweep.csv --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5
```

The sweep CSV includes frame counts, valid contour fraction, warning codes, and
summary statistics for the same shape descriptors used by `analyze`.

To run the current headless analysis pipeline and export per-frame metrics:

```bash
.\.venv\Scripts\morphostack analyze path\to\stack.tif --threshold 100 --out metrics.csv --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5
```

With a project file, the same command can reuse stored threshold, profile,
voxel size, ROI, Z range, mesh, and contour settings:

```bash
.\.venv\Scripts\morphostack analyze path\to\stack.tif --out metrics.csv --project morphostack.project.json
```

Use `--profile vesicle` or `--profile rbc` to record the biological analysis
profile. The current RBC profile shares the same threshold-contour engine while
providing a clean branch point for RBC-specific metrics.

Add `--mesh` to assemble contour masks and include marching-cubes 3D surface area, volume, equivalent sphere diameter, and sphericity in the CSV.
Use `--z-range ZMIN ZMAX` to trim top/bottom stack slices before thresholding,
preview, sweep, analysis, or batch processing. Bounds are inclusive-exclusive,
so `--z-range 5 30` analyzes source frames 5 through 29 and preserves those
source frame indices in exported rows.
By default, `morphostack analyze` also writes `<metrics.csv>.manifest.json`
with source path, version, profile, voxel size, ROI, Z range, threshold, mesh
settings, source SHA-256, voxel source, run-level summary statistics, quality
warnings, and CSV columns.
Use `--no-manifest` to skip it or
`--manifest path\to\run.json` to choose the JSON path.
Add `--report` to also write a Markdown report at
`<metrics.csv>.report.md`, or pass `--report path\to\report.md` to choose the
path.
Use `--bundle-dir runs` to create a run folder containing `metrics.csv`,
`manifest.json`, and `report.md` together.

To analyze a folder of stacks and produce one summary table:

```bash
.\.venv\Scripts\morphostack batch path\to\stacks --threshold 100 --out batch_summary.csv --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5
```

Add `--recursive` to include subdirectories, and `--metrics-dir path\to\frames`
to also save each stack's per-frame metrics CSV.
Add `--bundle-dir path\to\runs` to create one run bundle per stack, each with
`metrics.csv`, `manifest.json`, and `report.md`.
The batch summary includes each stack's source SHA-256 so exported rows can be
matched back to exact input files.

To compare a new CSV export against a reference export:

```bash
.\.venv\Scripts\morphostack validate reference_metrics.csv new_metrics.csv --tolerance 0.000001
```

Use `--columns area_um2 circularity deformation_index` to restrict validation
to selected metrics. This is intended for regression checks against trusted
legacy outputs or curated lab reference datasets.
Use `--all-columns` when comparing batch summary CSVs and provenance columns
such as `source_sha256` should be checked exactly.

To start the local backend for the future web UI:

```bash
.\.venv\Scripts\morphostack serve
```

To start the local backend and web UI together during development:

```bash
.\.venv\Scripts\morphostack dev
```

Use `.\.venv\Scripts\morphostack dev --check` to verify that Python API
dependencies, npm, and web dependencies are available before launching.
It also checks that the selected backend and web ports are free; use
`--api-port` or `--web-port` if another process is already using the defaults.

Current API endpoints:

- `GET /health`
- `POST /inspect`
- `POST /analyze`
- `POST /threshold`
- `POST /preview`
- `POST /sweep`
- `POST /upload/inspect`
- `POST /upload/analyze`
- `POST /upload/batch`
- `POST /upload/validate`
- `POST /upload/threshold`
- `POST /upload/preview`
- `POST /upload/sweep`

To start only the browser UI during development:

```bash
cd apps\web
npm install
npm run dev
```

The browser UI can preview threshold segmentation, analyze a selected TIFF/CZI
file through upload endpoints, or use a local stack path when the backend can
already access the file. After analysis, the frame metrics table can be
downloaded as a CSV file, and the run manifest can be downloaded as JSON.
The browser can also download a Markdown report from the latest analysis run.
The web app can also run a threshold sweep and download the sweep summary as
CSV or a Markdown threshold sweep report.
Project settings JSON can be loaded into the browser controls or downloaded
from the current controls for reuse in the CLI.
Multiple uploaded stacks can be batch analyzed into one spreadsheet-friendly
summary CSV and a Markdown batch report.
CSV validation is available in the browser for comparing new exports against
reference metric files.
The analysis summary reports valid-frame means, minima, maxima, and standard
deviations for core shape descriptors.
Current 2D descriptors include area, perimeter, circularity, bounding-box size,
aspect ratio, elongation, deformation index, extent, equivalent diameter, and
solidity.
The `Suggest` threshold tool uses Otsu thresholding when available and falls
back to a percentile-based suggestion.
Threshold sweep support can compare a range of candidate thresholds and export
spreadsheet-friendly summary rows for threshold sensitivity checks.
Analysis warnings are shown in the UI and included in the run manifest.
If voxel spacing falls back to MorphoStack defaults, analysis outputs include a
`default_voxel_size` warning because physical units are uncalibrated.
The analysis profile selector currently supports `vesicle` and `rbc`.

## Architecture Direction

- Python core package for scientific analysis.
- FastAPI backend for local app/runtime APIs.
- Vite web frontend in `apps/web`.
- Later packaging through `pipx`, GitHub Releases, and a Windows installer.

No GitHub remote is configured yet.

## Core Migration Rules

- Keep GUI behavior out of `morphostack.core`.
- Load files non-interactively; voxel sizes must come from metadata, defaults, or explicit caller overrides.
- Store physical spacing as micrometers through `VoxelSize`.
- Record whether voxel spacing came from metadata, a user override, or defaults.
- Use project settings JSON when a dataset needs reproducible CLI defaults.
- Use `vx * vy` for areas and anisotropic segment lengths for perimeters.
- Keep shape descriptors unit-consistent; solidity must compare physical area
  with physical convex-hull area.
- Keep basic threshold previews usable without OpenCV; use optional OpenCV only for richer contour smoothing/extraction.
- When `opencv-python` is installed, `segmentation_preview` uses real external contours instead of the rectangular fallback.
- Use `analyze_stack` as the headless core pipeline for CLI/API/UI workflows.
- Use `morphostack batch` when a directory of stacks should become one
  spreadsheet-friendly summary table.
- Use `morphostack sweep` when a threshold needs sensitivity checking before a
  fixed analysis run.
- Use `morphostack validate` to compare generated CSV metrics against reference
  outputs before trusting analysis changes.
- Treat vesicle and RBC analysis as explicit profiles, even where early shared
  processing is identical.
- Treat heavy analysis libraries such as OpenCV and scikit-image as optional until the pipeline needs them.
- Ambiguous 3D arrays with final channel size 3 or 4 are treated as single color images; grayscale stacks should be shaped `(z, y, x)` without an RGB-like final channel.
