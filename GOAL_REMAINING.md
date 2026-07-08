# MorphoStack Remaining Goal Checklist

Last updated: 2026-07-08

This file tracks what is still left from the original MorphoStack goal: a refreshed, researcher-friendly local web app for vesicle/GUV and RBC shape analysis, replacing the old GUI workflow while keeping scientific computation reproducible and testable.

## Current Progress Estimate

- Working demo / prototype: **97%** done
- Internship/lab-usable internal tool: **92%** done
- Paper-supporting, biologically validated tool: **78%** done
- Publicly distributable open-source app: **72%** done

Single-number answer for the original goal: about **92%** done for a solid internal lab tool. The remaining work is mostly RBC science sign-off, LimeSeg real-data stabilization, fuller validation visuals, and packaging polish.

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
- Real-data validation runs: DOPC smoke test, crowded CZI 1650 (two objects), crowded RBC Image 46 (two objects).
- **Synthetic sphere validation** with reference metrics regression (`scripts/validate_synthetic.py`).
- Docs: `limitations.md`, `validation.md`, `troubleshooting.md`, `limeseg.md`, **`metrics.md`**.
- Full test suite passes: **187 tests**.
- Web build passes.

## Highest Priority Remaining Work

### 1. Freeze The Current Working Tree — DONE

Committed lab-tool goals, frame-index fixes, mesh-export tests, crowded validation, and this continuation batch.

### 2. Validate On Real Multi-Object Vesicle And RBC Data — MOSTLY DONE

Done:
- Crowded vesicle run: `validation/runs/czi-1650-crowded-two-objects/`
- Crowded RBC run: `validation/runs/rbc-image46-crowded-two-objects/`
- Distinct metrics for different selected objects documented in README files.

Still open:
- Validation runs for `1644_z stack.czi`, `Image 32.lsm`, and DOPC re-run with object seeds.
- Screenshot/preview overlay images saved into validation folders.
- LimeSeg vs threshold comparison on the same crowded datasets.

### 3. Lock Down Voxel Calibration — DONE

Metadata extraction, UI badges, scary default styling, manifest/report warnings, and calibration help panel are implemented. Calibration is stored in project settings JSON.

### 4. Finish RBC-Specific Science — BLOCKED ON LAB INPUT

Needs lab decision on which RBC outputs matter for the first paper/demo version. `docs/metrics.md` documents current contour metrics; RBC-specific warnings and report wording remain thin until requirements are confirmed.

### 5. Improve Object Selection Robustness — MOSTLY DONE

Done:
- Tracking debug overlay.
- Export warnings for lost tracking, ROI boundary touch, neighbor merge.
- Crowded validation examples with documented pass/fail behavior.

Still open:
- Side-by-side comparison of circle seed, polygon seed, ROI crop, threshold, and LimeSeg on the same datasets.
- IoU/overlap tracking between adjacent slices.
- Watershed splitting when cells touch (partial via LimeSeg pre-split).

### 6. Manual Review And Correction Workflow — PARTIAL

Done:
- Frame metrics table with per-frame **Exclude** checkboxes.
- Re-analyze with exclusions (updates summary, mesh, manifest, CSV).
- Excluded frames recorded in reports and manifests.

Still open:
- Accept/reject contour marking beyond exclude.
- Polygon/freehand contour correction.
- Export review overlays for lab notebooks.

### 7. 3D Mesh Viewer And Export Polish — PARTIAL

Done:
- Mesh export: OBJ, STL, PLY.
- Mask export: TIFF.
- Interactive Plotly 3D preview.

Still open:
- GLB export.
- Standalone HTML export button for presentations.
- Camera presets, opacity controls, screenshot button.
- Stronger loading/progress state for large stacks.

### 8. LimeSeg Profile Stabilization — PARTIAL

Done:
- LimeSeg-lite engine with watershed/seed-mask improvements and unit tests.
- `docs/limeseg.md` guidance.

Still open:
- Real-data comparison runs on DOPC, multi-vesicle CZI, and RBC LSM.
- Regression against threshold-contour meshes with saved manifests.

### 9. UI Ergonomics For Researchers — PARTIAL

Done:
- Step badges, calibration prominence, tracking overlay, voxel source badges.

Still open:
- Full workflow redesign and run/session sidebar.
- Reduce duplicated controls and dense panels.

### 10. Validation And Reference Dataset System — PARTIAL

Done:
- Real-data crowded validation structure.
- Synthetic sphere reference with `compare_metric_csv` regression.
- `scripts/validate_synthetic.py` and `scripts/validate_crowded.py`.

Still open:
- Synthetic ellipsoid and touching-object failure references.
- Visual overlays/screenshots in validation folders.
- Automated validation report comparing all runs after code changes.

### 11. Packaging And Install Path — PARTIAL

Done:
- `morphostack app` launcher (built UI + API on one port).
- `docs/distribution.md` updated with lab install path.

Still open:
- Wheel packaging with bundled web assets.
- pipx / GitHub Releases / Windows package-manager manifests.

### 12. Documentation For Lab And Paper Use — MOSTLY DONE

Done:
- README and `prototype_usage.md` updated in prior commits.
- `limitations.md`, `validation.md`, `troubleshooting.md`, `limeseg.md`.
- **`docs/metrics.md`** with formulas and limitations.

Still open:
- Citation/license notes for external algorithms.
- Methods section ready for direct paste into a paper supplement.

## Suggested Next Implementation Order

1. LimeSeg vs threshold comparison on crowded validation stacks.
2. Save preview overlay screenshots into validation folders.
3. RBC-specific science after lab feedback.
4. Standalone mesh HTML export and presentation screenshot controls.
5. Wheel packaging with bundled `apps/web/dist`.

## Do Not Do Yet Unless There Is A Strong Reason

- Do not add Cellpose/StarDist as a required dependency yet.
- Do not rewrite the frontend from scratch.
- Do not replace the Python core with Java/Fiji integration.
- Do not chase perfect RBC science before the lab defines required outputs.
- Do not present default-voxel surface/volume as biological measurements.

## Current Bottom Line

MorphoStack is now a credible internal lab tool: crowded-object validation, honest calibration warnings, tracking diagnostics, mesh/mask export, frame exclusion, synthetic regression, and a one-command `morphostack app` launcher. The remaining gap is trust at the science/packaging layer, not basic functionality.