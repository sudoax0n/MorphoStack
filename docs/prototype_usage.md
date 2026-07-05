# MorphoStack Prototype Usage

This is the quick working guide for presenting the current RBC/vesicle shape
analysis prototype.

## Start The App

From `D:\MorphoStack`:

```powershell
.\.venv\Scripts\morphostack dev --check
.\.venv\Scripts\morphostack dev
```

Open:

```text
http://127.0.0.1:5173
```

If the default ports are busy:

```powershell
.\.venv\Scripts\morphostack dev --api-port 8123 --web-port 5123
```

## Normal Demo Workflow

1. In **Stack**, choose a `.tif`, `.tiff`, or `.czi` file.
2. Enter voxel calibration in micrometers.
   - Use metadata values if known.
   - If unsure, leave `1`, but say that physical units are uncalibrated.
3. Click **Inspect**.
   - Confirm the stack shape and voxel source.
4. In **Preview & Analyze**, choose profile:
   - `RBC` for tomorrow's RBC prototype.
   - `Vesicle` for the older vesicle-style workflow.
5. Optional: set **Z range**.
   - `start=5`, `stop=30` means frames 5 through 29.
   - Leave blank to use the full stack.
6. Optional: set **XY ROI**.
   - Leave blank unless you need to isolate one object.
7. Click **Suggest Threshold**.
8. Click **Preview** and inspect the segmentation overlay.
9. Adjust threshold or preview frame if needed.
10. Click **Analyze**.
11. Download:
   - **CSV** for frame metrics.
   - **Manifest** for run settings/provenance.
   - **Report** for lab notes or presentation backup.

## What To Say During The Presentation

Use this phrasing:

> MorphoStack is a working local prototype for microscopy stack morphometry. It
> supports RBC and vesicle profiles, stack upload, voxel calibration, Z trimming,
> ROI masking, threshold preview, quantitative shape metrics, batch analysis, and
> reproducible reports/manifests.

Be honest about the current RBC status:

> The RBC profile currently uses the shared threshold-contour analysis engine.
> The next scientific step is validating RBC-specific metrics and reference
> datasets with lab feedback.

## Useful Outputs

The frame metrics CSV includes:

- area
- perimeter
- circularity
- bounding-box width and height
- aspect ratio
- elongation
- deformation index
- extent
- equivalent diameter
- solidity
- optional 3D mesh surface area and volume

The manifest records:

- source file path/name
- source SHA-256
- profile
- threshold
- voxel size
- Z range
- ROI
- mesh setting
- contour backend setting
- warnings
- MorphoStack version

## Batch Workflow

Use **Batch** when you have several stacks to process with the same settings.

1. Set profile, voxel size, threshold, Z range, ROI, and mesh options.
2. Select multiple stack files in **Batch**.
3. Click **Analyze Batch**.
4. Download batch CSV or batch report.

## Threshold Sweep Workflow

Use **Threshold Sweep** when you need to justify threshold choice.

1. Enter start, stop, and step values.
2. Click **Run Sweep**.
3. Pick a threshold with high valid fraction and stable metrics.
4. Download the sweep CSV/report if needed.

## CLI Backup Commands

Single RBC analysis:

```powershell
.\.venv\Scripts\morphostack analyze path\to\stack.tif --profile rbc --threshold 100 --z-range 5 30 --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5 --out metrics.csv --report
```

Create a reusable project file:

```powershell
.\.venv\Scripts\morphostack project init --out rbc.project.json --profile rbc --threshold 100 --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5 --z-range 5 30
```

Analyze using that project:

```powershell
.\.venv\Scripts\morphostack analyze path\to\stack.tif --project rbc.project.json --out metrics.csv --report
```

Batch analysis:

```powershell
.\.venv\Scripts\morphostack batch path\to\folder --project rbc.project.json --out batch_summary.csv
```

## Current Limitations

- Manual polygon correction is not yet in MorphoStack.
- RBC-specific biological metrics still need lab validation.
- Mesh values depend strongly on segmentation quality and voxel calibration.
- If voxel spacing is unknown, physical units should be treated cautiously.

## Quick Troubleshooting

If the app does not start:

```powershell
.\.venv\Scripts\morphostack doctor
.\.venv\Scripts\morphostack init --web
```

If preview or analysis says no valid contours:

- lower or raise the threshold
- trim blank Z slices
- set an XY ROI around the object
- check image contrast

If the browser cannot connect:

- check that `morphostack dev` is still running
- try `http://127.0.0.1:5173`
- run `morphostack dev --check`
