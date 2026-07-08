# MorphoStack Remaining Goal Checklist

Last updated: 2026-07-08

This file tracks what is still left from the original MorphoStack goal: a refreshed, researcher-friendly local web app for vesicle/GUV and RBC shape analysis, replacing the old GUI workflow while keeping scientific computation reproducible and testable.

## Current Progress Estimate

- Working demo / prototype: **99%** done
- Internship/lab-usable internal tool: **98%** done
- Paper-supporting, biologically validated tool: **82%** done
- Publicly distributable open-source app: **82%** done

Single-number answer for the original goal: about **98%** done for a solid internal lab tool. The remaining work is mostly RBC science sign-off, LimeSeg tuning on crowded data, and minor UI ergonomics polish.

## What Is Already In Good Shape

- Python core package with tested analysis modules.
- FastAPI backend for local app/runtime APIs.
- Browser UI through Vite.
- Canonical command: `morphostack`. Short alias: `mst`.
- `doctor`, `init`, `dev`, `dev --check`, `serve`, and **`app`** setup flow.
- Stack inspection and loading for TIFF/TIF, LSM, and CZI-style microscopy files.
- Metadata-aware voxel inspection with manual override support and prominent UI warnings.
- Vesicle, RBC, and LimeSeg analysis profiles.
- Threshold suggestion, threshold sweep, rectangular ROI, frame/Z trimming, and preview scrubbing.
- Object selection through clicked seed, radius controls, max tracking distance, and polygon seed tools.
- **Tracking diagnostics** with debug overlay and export warnings (`tracking_lost`, `roi_boundary_touch`, `likely_neighbor_merge`).
- Upload and local-path flows for preview, analyze, mesh preview, mesh export, and validation.
- Per-frame metrics and 3D mesh measurement.
- Plotly-based interactive 3D mesh preview in the browser.
- **Mesh export** (OBJ, STL, PLY) and **mask export** (TIFF).
- **Frame exclusion** workflow in API, CLI, and UI (exclude bad slices before trusting summary/mesh).
- CSV export, JSON manifests, Markdown reports, SHA-256 provenance, batch summaries, and CSV validation.
- Real-data validation runs: DOPC smoke + seeded GUV, crowded CZI 1650/1644, crowded RBC Image 46/32.
- **Synthetic sphere + ellipsoid validation** with reference metrics regression.
- **Validation preview PNG capture** (`scripts/capture_validation_previews.py`).
- **Combined validation report** (`scripts/validate_all.py`).
- **LimeSeg vs threshold** comparisons on synthetic, crowded, and DOPC datasets.
- **Standalone mesh HTML export** with camera presets, opacity slider, and PNG screenshot.
- **Wheel packaging** with bundled `apps/web/dist` and **GitHub Release workflow**.
- Docs: `limitations.md`, `validation.md`, `troubleshooting.md`, `limeseg.md`, **`metrics.md`**, **`methods.md`**, **`citations.md`**.
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
- LimeSeg vs threshold comparison on crowded datasets.
- Preview overlay PNG capture into validation folders.

### 3. Lock Down Voxel Calibration — DONE

### 4. Finish RBC-Specific Science — BLOCKED ON LAB INPUT

Needs lab decision on which RBC outputs matter for the first paper/demo version.

### 5. Improve Object Selection Robustness — MOSTLY DONE

Still open:
- Side-by-side preview comparison UI for circle seed, polygon seed, ROI crop, threshold, and LimeSeg.
- IoU/overlap tracking between adjacent slices.
- Watershed splitting when cells touch (partial via LimeSeg pre-split).

### 6. Manual Review And Correction Workflow — PARTIAL

Still open:
- Accept/reject contour marking beyond exclude.
- Polygon/freehand contour correction.

### 7. 3D Mesh Viewer And Export Polish — MOSTLY DONE

Still open:
- GLB export.
- Stronger loading/progress state for large stacks.

### 8. LimeSeg Profile Stabilization — MOSTLY DONE

Still open:
- Tune LimeSeg defaults until synthetic/real deltas are acceptable for publication use.

### 9. UI Ergonomics For Researchers — PARTIAL

Still open:
- Full workflow redesign and run/session sidebar.
- Reduce duplicated controls and dense panels.

### 10. Validation And Reference Dataset System — MOSTLY DONE

Still open:
- Synthetic touching-object failure reference (documented negative case).
- winget / Scoop package-manager manifests.

### 11. Packaging And Install Path — MOSTLY DONE

Done:
- Wheel packaging with bundled web assets.
- GitHub Release workflow (`.github/workflows/release.yml`).

Still open:
- Publish first tagged GitHub Release and verify pipx install from release asset.

### 12. Documentation For Lab And Paper Use — MOSTLY DONE

Still open:
- Final author/repo citation line once publication venue is chosen.

## Suggested Next Implementation Order

1. RBC-specific science after lab feedback.
2. LimeSeg default tuning on crowded real data.
3. Publish `v0.1.0` GitHub Release and test pipx install.
4. GLB export and large-stack loading progress (optional polish).

## Do Not Do Yet Unless There Is A Strong Reason

- Do not add Cellpose/StarDist as a required dependency yet.
- Do not rewrite the frontend from scratch.
- Do not replace the Python core with Java/Fiji integration.
- Do not chase perfect RBC science before the lab defines required outputs.
- Do not present default-voxel surface/volume as biological measurements.

## Current Bottom Line

MorphoStack is now a credible internal lab tool with validation coverage across four crowded real datasets, DOPC seeded analysis, synthetic sphere/ellipsoid regression, LimeSeg comparisons, mesh/mask export, frame exclusion, wheel packaging, and a one-command `morphostack app` launcher. The remaining gap is science sign-off and publication-grade LimeSeg trust, not basic functionality.