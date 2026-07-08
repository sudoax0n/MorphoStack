# MorphoStack Remaining Goal Checklist

Last updated: 2026-07-08

This file tracks what is still left from the original MorphoStack goal: a refreshed, researcher-friendly local web app for vesicle/GUV and RBC shape analysis, replacing the old GUI workflow while keeping scientific computation reproducible and testable.

## Current Progress Estimate

- Working demo / prototype: **99%** done
- Internship/lab-usable internal tool: **98%** done
- Paper-supporting, biologically validated tool: **84%** done
- Publicly distributable open-source app: **84%** done

Single-number answer for the original goal: about **99%** done for a solid internal lab tool. The remaining work is mostly RBC science sign-off, crowded-data Active Surfaces trust, and publishing the first GitHub Release.

## What Is Already In Good Shape

- Python core package with tested analysis modules.
- FastAPI backend for local app/runtime APIs.
- Browser UI through Vite.
- Canonical command: `morphostack`. Short alias: `mst`.
- `doctor`, `init`, `dev`, `dev --check`, `serve`, and **`app`** setup flow.
- Stack inspection and loading for TIFF/TIF, LSM, and CZI-style microscopy files.
- Metadata-aware voxel inspection with manual override support and prominent UI warnings.
- Vesicle, RBC, and Active Surfaces analysis profiles.
- Threshold suggestion, threshold sweep, rectangular ROI, frame/Z trimming, and preview scrubbing.
- Object selection through clicked seed, radius controls, max tracking distance, and polygon seed tools.
- **Tracking diagnostics** with debug overlay and export warnings (`tracking_lost`, `roi_boundary_touch`, `likely_neighbor_merge`).
- Upload and local-path flows for preview, analyze, mesh preview, mesh export, and validation.
- Per-frame metrics and 3D mesh measurement.
- Plotly-based interactive 3D mesh preview in the browser.
- **Mesh export** (OBJ, STL, PLY, **GLB**) and **mask export** (TIFF).
- **Frame exclusion** workflow in API, CLI, and UI (exclude bad slices before trusting summary/mesh).
- CSV export, JSON manifests, Markdown reports, SHA-256 provenance, batch summaries, and CSV validation.
- Real-data validation runs: DOPC smoke + seeded GUV, crowded CZI 1650/1644, crowded RBC Image 46/32.
- **Synthetic sphere + ellipsoid validation** with reference metrics regression.
- **Validation preview PNG capture** (`scripts/capture_validation_previews.py`).
- **Combined validation report** (`scripts/validate_all.py`).
- **Active Surfaces vs threshold** comparisons on synthetic, crowded, and DOPC datasets.
- **Standalone mesh HTML export** with camera presets, opacity slider, and PNG screenshot.
- **Wheel packaging** with bundled `apps/web/dist` and **GitHub Release workflow**.
- Docs: `limitations.md`, `validation.md`, `troubleshooting.md`, `active-surfaces.md`, **`metrics.md`**, **`methods.md`**, **`citations.md`**.
- Full test suite passes: **195+ tests**.
- Web build passes.

## Highest Priority Remaining Work

### 1. Freeze The Current Working Tree — DONE

### 2. Validate On Real Multi-Object Vesicle And RBC Data — DONE

Done:
- Crowded vesicle runs: `czi-1650-crowded-two-objects/`, `czi-1644-crowded-two-objects/`
- Crowded RBC runs: `rbc-image46-crowded-two-objects/`, `rbc-image32-crowded-two-objects/`
- DOPC seeded GUV run: `dopc-seeded-object/`
- Distinct metrics for different selected objects documented in README files.
- Active Surfaces vs threshold comparison on crowded datasets.
- Preview overlay PNG capture into validation folders.

### 3. Lock Down Voxel Calibration — DONE

### 4. Finish RBC-Specific Science — BLOCKED ON LAB INPUT

Needs lab decision on which RBC outputs matter for the first paper/demo version.

### 5. Improve Object Selection Robustness — MOSTLY DONE

Still open:
- Side-by-side preview comparison UI for circle seed, polygon seed, ROI crop, threshold, and Active Surfaces.
- IoU/overlap tracking between adjacent slices.
- Watershed splitting when cells touch (partial via Active Surfaces pre-split).

### 6. Manual Review And Correction Workflow — PARTIAL

Still open:
- Accept/reject contour marking beyond exclude.
- Polygon/freehand contour correction.

### 7. 3D Mesh Viewer And Export Polish — MOSTLY DONE

Done:
- GLB export (API, CLI, browser mesh preview toolbar).
- Upload progress bar for inspect, analyze, and mesh-preview uploads.

Still open:
- Server-side progress for local-path reads of very large CZI/LSM files.

### 8. Active Surfaces Profile Stabilization — MOSTLY DONE

Done:
- Retuned `ACTIVE_SURFACES_DEFAULTS` (`k_grad=0.05`, `f_pressure=0.02`, `optimization_steps=300`) for ~10% synthetic-sphere mesh delta.

Still open:
- Crowded real-data deltas remain large; publication use still needs side-by-side preview sign-off.

### 9. UI Ergonomics For Researchers — PARTIAL

Still open:
- Full workflow redesign and run/session sidebar.
- Reduce duplicated controls and dense panels.

### 10. Validation And Reference Dataset System — MOSTLY DONE

Done:
- Synthetic touching-object failure reference (`validation/runs/synthetic-touching-failure/`).

Still open:
- winget / Scoop package-manager manifests.

### 11. Packaging And Install Path — MOSTLY DONE

Done:
- Wheel packaging with bundled web assets.
- GitHub Release workflow (`.github/workflows/release.yml`).

Still open:
- Publish first tagged GitHub Release and verify pipx install from release asset.

Helper:
- `scripts/verify_release_wheel.ps1` — local wheel build + isolated install smoke test.

### 12. Documentation For Lab And Paper Use — MOSTLY DONE

Still open:
- Final author/repo citation line once publication venue is chosen.

## Suggested Next Implementation Order

1. RBC-specific science after lab feedback.
2. Crowded real-data Active Surfaces preview sign-off (defaults tuned for synthetic only).
3. Publish `v0.1.0` GitHub Release and test pipx install (`scripts/verify_release_wheel.ps1`).
4. Side-by-side preview comparison UI and workflow redesign (optional polish).

## Do Not Do Yet Unless There Is A Strong Reason

- Do not add Cellpose/StarDist as a required dependency yet.
- Do not rewrite the frontend from scratch.
- Do not replace the Python core with Java/Fiji integration.
- Do not chase perfect RBC science before the lab defines required outputs.
- Do not present default-voxel surface/volume as biological measurements.

## Current Bottom Line

MorphoStack is now a credible internal lab tool with validation coverage across four crowded real datasets, DOPC seeded analysis, synthetic sphere/ellipsoid/touching-failure references, Active Surfaces comparisons, mesh/mask/GLB export, upload progress for large files, frame exclusion, wheel packaging, and a one-command `morphostack app` launcher. The remaining gap is science sign-off, crowded-data Active Surfaces trust, and publishing the first release — not basic functionality.