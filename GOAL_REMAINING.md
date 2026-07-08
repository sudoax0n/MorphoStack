# MorphoStack Remaining Goal Checklist

Last updated: 2026-07-08

This file tracks what is still left from the original MorphoStack goal: a refreshed, researcher-friendly local web app for vesicle/GUV and RBC shape analysis, replacing the old GUI workflow while keeping scientific computation reproducible and testable.

## Current Progress Estimate

- Working demo / prototype: **98%** done
- Internship/lab-usable internal tool: **96%** done
- Paper-supporting, biologically validated tool: **80%** done
- Publicly distributable open-source app: **78%** done

Single-number answer for the original goal: about **96%** done for a solid internal lab tool. The remaining work is mostly RBC science sign-off, LimeSeg tuning on crowded data, optional extra validation datasets, and UI ergonomics polish.

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
- **Validation preview PNG capture** (`scripts/capture_validation_previews.py`).
- **Combined validation report** (`scripts/validate_all.py`).
- **LimeSeg vs threshold** comparisons including synthetic, crowded CZI/RBC, and DOPC (`scripts/compare_limeseg_threshold.py`).
- **Standalone mesh HTML export** with camera presets, opacity slider, and PNG screenshot in the mesh viewer.
- **Wheel packaging** with bundled `apps/web/dist` (`scripts/build_wheel.ps1`, `morphostack/_web_static`).
- Docs: `limitations.md`, `validation.md`, `troubleshooting.md`, `limeseg.md`, **`metrics.md`**, **`methods.md`**, **`citations.md`**.
- Full test suite passes: **190+ tests**.
- Web build passes.

## Highest Priority Remaining Work

### 1. Freeze The Current Working Tree — DONE

Committed lab-tool goals, frame-index fixes, mesh-export tests, crowded validation, and this continuation batch.

### 2. Validate On Real Multi-Object Vesicle And RBC Data — MOSTLY DONE

Done:
- Crowded vesicle run: `validation/runs/czi-1650-crowded-two-objects/`
- Crowded RBC run: `validation/runs/rbc-image46-crowded-two-objects/`
- Distinct metrics for different selected objects documented in README files.
- LimeSeg vs threshold comparison on crowded datasets.
- Preview overlay PNG capture into validation folders.

Still open:
- Validation runs for `1644_z stack.czi`, `Image 32.lsm`, and DOPC re-run with explicit object seeds.

### 3. Lock Down Voxel Calibration — DONE

Metadata extraction, UI badges, scary default styling, manifest/report warnings, and calibration help panel are implemented. Calibration is stored in project settings JSON.

### 4. Finish RBC-Specific Science — BLOCKED ON LAB INPUT

Needs lab decision on which RBC outputs matter for the first paper/demo version. `docs/metrics.md` documents current contour metrics; RBC-specific warnings and report wording remain thin until requirements are confirmed.

### 5. Improve Object Selection Robustness — MOSTLY DONE

Done:
- Tracking debug overlay.
- Export warnings for lost tracking, ROI boundary touch, neighbor merge.
- Crowded validation examples with documented pass/fail behavior.
- LimeSeg vs threshold side-by-side metric comparison on shared seeds.

Still open:
- Side-by-side preview comparison UI for circle seed, polygon seed, ROI crop, threshold, and LimeSeg.
- IoU/overlap tracking between adjacent slices.
- Watershed splitting when cells touch (partial via LimeSeg pre-split).

### 6. Manual Review And Correction Workflow — PARTIAL

Done:
- Frame metrics table with per-frame **Exclude** checkboxes.
- Re-analyze with exclusions (updates summary, mesh, manifest, CSV).
- Excluded frames recorded in reports and manifests.
- Validation preview PNG export for lab notebooks.

Still open:
- Accept/reject contour marking beyond exclude.
- Polygon/freehand contour correction.

### 7. 3D Mesh Viewer And Export Polish — MOSTLY DONE

Done:
- Mesh export: OBJ, STL, PLY.
- Mask export: TIFF.
- Interactive Plotly 3D preview.
- Standalone HTML export button for presentations.
- Camera presets, opacity controls, and PNG screenshot in mesh viewer.

Still open:
- GLB export.
- Stronger loading/progress state for large stacks.

### 8. LimeSeg Profile Stabilization — MOSTLY DONE

Done:
- LimeSeg-lite engine with watershed/seed-mask improvements and unit tests.
- `docs/limeseg.md` guidance.
- **`scripts/compare_limeseg_threshold.py`** with reports for synthetic sphere, crowded CZI 1650, RBC Image 46, and DOPC Movie 1 under `validation/reports/`.
- Comparison shows large deltas on real crowded data — LimeSeg correctly documented as experimental.

Still open:
- Tune LimeSeg defaults until synthetic/real deltas are acceptable for publication use.

### 9. UI Ergonomics For Researchers — PARTIAL

Done:
- Step badges, calibration prominence, tracking overlay, voxel source badges.

Still open:
- Full workflow redesign and run/session sidebar.
- Reduce duplicated controls and dense panels.

### 10. Validation And Reference Dataset System — MOSTLY DONE

Done:
- Real-data crowded validation structure.
- Synthetic sphere reference with `compare_metric_csv` regression.
- `scripts/validate_synthetic.py`, `scripts/validate_crowded.py`, `scripts/validate_all.py`.
- Visual overlays/screenshots in validation folders via `capture_validation_previews.py`.

Still open:
- Synthetic ellipsoid and touching-object failure references.
- Validation runs for additional datasets (`1644_z stack.czi`, `Image 32.lsm`).

### 11. Packaging And Install Path — MOSTLY DONE

Done:
- `morphostack app` launcher (built UI + API on one port).
- `docs/distribution.md` updated with lab install path.
- Wheel packaging with bundled web assets (`scripts/build_wheel.ps1`).

Still open:
- pipx / GitHub Releases / Windows package-manager manifests.

### 12. Documentation For Lab And Paper Use — MOSTLY DONE

Done:
- README and `prototype_usage.md` updated in prior commits.
- `limitations.md`, `validation.md`, `troubleshooting.md`, `limeseg.md`.
- **`docs/metrics.md`** with formulas and limitations.
- **`docs/methods.md`** draft for paper supplement.
- **`docs/citations.md`** for external libraries and datasets.

Still open:
- Final author/repo citation line once publication venue is chosen.

## Suggested Next Implementation Order

1. RBC-specific science after lab feedback.
2. Validation runs for `1644_z stack.czi` and `Image 32.lsm`.
3. LimeSeg default tuning on crowded real data.
4. pipx / GitHub Releases packaging polish.

## Do Not Do Yet Unless There Is A Strong Reason

- Do not add Cellpose/StarDist as a required dependency yet.
- Do not rewrite the frontend from scratch.
- Do not replace the Python core with Java/Fiji integration.
- Do not chase perfect RBC science before the lab defines required outputs.
- Do not present default-voxel surface/volume as biological measurements.

## Current Bottom Line

MorphoStack is now a credible internal lab tool: crowded-object validation, honest calibration warnings, tracking diagnostics, mesh/mask export, frame exclusion, synthetic regression, validation preview capture, LimeSeg comparisons including DOPC, standalone mesh HTML export, wheel packaging, and a one-command `morphostack app` launcher. The remaining gap is trust at the science/packaging layer, not basic functionality.