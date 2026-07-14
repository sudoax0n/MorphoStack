# MorphoStack Web

Local browser UI for the MorphoStack FastAPI backend.

## Development

From the repository root, the easiest development command is:

```bash
.\.venv\Scripts\morphostack dev
```

Start the backend from the repository root:

```bash
.\.venv\Scripts\morphostack serve
```

Start the frontend from this folder:

```bash
npm install
npm run dev
```

Vite proxies `/api/*` requests to `http://127.0.0.1:8000`.
Set `MORPHOSTACK_API_TARGET` to point Vite at a different backend.

The UI supports direct TIFF/CZI uploads for normal local use. The path input is
kept as a developer fallback when the backend can access a file directly. Users
can preview threshold segmentation before analysis and download the returned
frame metrics as a CSV file after analysis. Users can also download a JSON run
manifest with source, source SHA-256, profile, voxel size, ROI, threshold, mesh
settings, Z range, and quality warnings. The metrics include core 2D shape descriptors such as area,
perimeter, circularity, aspect ratio, equivalent diameter, elongation, extent,
and solidity. The Mode selector supports Standard (`vesicle`), RBC (`rbc`), and
Experimental active surfaces (`active_surfaces`). For multi-vesicle fields use
Standard + Select Object; Experimental is a slow single-object fallback only.
modes. The `Suggest` threshold control uses Otsu thresholding when available and
falls back to a percentile suggestion.
Z-range controls trim top/bottom stack slices before preview, threshold
suggestion, sweep, analysis, and batch runs while preserving source frame
indices in exports.
Threshold sweeps can be downloaded as CSV or as a Markdown report for lab notes.
CSV validation can compare inferred numeric metrics or all shared columns,
including text provenance such as source SHA-256.
