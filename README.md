# MorphoStack

MorphoStack is a planned local morphometry toolkit for microscopy Z-stacks, starting with vesicle analysis and expanding to red blood cell analysis.

The first milestone is intentionally small: prove the project structure, command ownership, and diagnostics before migrating scientific code from the older Shape-Analysis prototype.

## Current Commands

```bash
morphostack doctor
morphostack init
morphostack inspect path\to\stack.tif
morphostack analyze path\to\stack.tif --threshold 100 --out metrics.csv
morphostack serve
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

Add `--mesh` to assemble contour masks and include marching-cubes 3D surface area and volume in the CSV.

To start the local backend for the future web UI:

```bash
.\.venv\Scripts\morphostack serve
```

Current API endpoints:

- `GET /health`
- `POST /inspect`
- `POST /analyze`

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
- Keep basic threshold previews usable without OpenCV; use optional OpenCV only for richer contour smoothing/extraction.
- When `opencv-python` is installed, `segmentation_preview` uses real external contours instead of the rectangular fallback.
- Use `analyze_stack` as the headless core pipeline for CLI/API/UI workflows.
- Treat heavy analysis libraries such as OpenCV and scikit-image as optional until the pipeline needs them.
- Ambiguous 3D arrays with final channel size 3 or 4 are treated as single color images; grayscale stacks should be shaped `(z, y, x)` without an RGB-like final channel.
