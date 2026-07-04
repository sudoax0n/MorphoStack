# MorphoStack

MorphoStack is a planned local morphometry toolkit for microscopy Z-stacks, starting with vesicle analysis and expanding to red blood cell analysis.

The first milestone is intentionally small: prove the project structure, command ownership, and diagnostics before migrating scientific code from the older Shape-Analysis prototype.

## Current Commands

```bash
morphostack doctor
morphostack init
morphostack inspect path\to\stack.tif
morphostack analyze path\to\stack.tif --threshold 100 --out metrics.csv
morphostack analyze path\to\stack.tif --threshold 100 --profile rbc --out metrics.csv
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

To inspect the machine and optionally install the heavier analysis/API
dependencies into the active environment:

```bash
.\.venv\Scripts\morphostack init
```

To inspect a stack after installing analysis dependencies:

```bash
.\.venv\Scripts\morphostack inspect path\to\stack.tif --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5
```

To run the current headless analysis pipeline and export per-frame metrics:

```bash
.\.venv\Scripts\morphostack analyze path\to\stack.tif --threshold 100 --out metrics.csv --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5
```

Use `--profile vesicle` or `--profile rbc` to record the biological analysis
profile. The current RBC profile shares the same threshold-contour engine while
providing a clean branch point for RBC-specific metrics.

Add `--mesh` to assemble contour masks and include marching-cubes 3D surface area and volume in the CSV.

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

Current API endpoints:

- `GET /health`
- `POST /inspect`
- `POST /analyze`
- `POST /preview`
- `POST /upload/inspect`
- `POST /upload/analyze`
- `POST /upload/preview`

To start only the browser UI during development:

```bash
cd apps\web
npm install
npm run dev
```

The browser UI can preview threshold segmentation, analyze a selected TIFF/CZI
file through upload endpoints, or use a local stack path when the backend can
already access the file. After analysis, the frame metrics table can be
downloaded as a CSV file. Current 2D descriptors include area, perimeter,
circularity, bounding-box size, aspect ratio, elongation, extent, equivalent
diameter, and solidity.
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
- Use `vx * vy` for areas and anisotropic segment lengths for perimeters.
- Keep shape descriptors unit-consistent; solidity must compare physical area
  with physical convex-hull area.
- Keep basic threshold previews usable without OpenCV; use optional OpenCV only for richer contour smoothing/extraction.
- When `opencv-python` is installed, `segmentation_preview` uses real external contours instead of the rectangular fallback.
- Use `analyze_stack` as the headless core pipeline for CLI/API/UI workflows.
- Treat vesicle and RBC analysis as explicit profiles, even where early shared
  processing is identical.
- Treat heavy analysis libraries such as OpenCV and scikit-image as optional until the pipeline needs them.
- Ambiguous 3D arrays with final channel size 3 or 4 are treated as single color images; grayscale stacks should be shaped `(z, y, x)` without an RGB-like final channel.
