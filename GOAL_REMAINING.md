# MorphoStack Remaining Goal Checklist

Last updated: 2026-07-08

This file tracks what is still left from the original MorphoStack goal: a refreshed, researcher-friendly local web app for vesicle/GUV and RBC shape analysis, replacing the old GUI workflow while keeping scientific computation reproducible and testable.

## Current Progress Estimate

These percentages use the current working tree, not only the last clean commit. The current tree passes tests, but it is still dirty and should be committed after review.

- Working demo / prototype: 95 percent done
- Internship/lab-usable internal tool: 86 percent done
- Paper-supporting, biologically validated tool: 74 percent done
- Publicly distributable open-source app: 66 percent done

Single-number answer for the original goal: about 86 percent done, 14 percent remaining for a solid internal lab tool. The remaining 14 percent is mostly validation, researcher ergonomics, documentation, and packaging rather than raw feature coding.

## What Is Already In Good Shape

- Python core package with tested analysis modules.
- FastAPI backend for local app/runtime APIs.
- Browser UI through Vite.
- Canonical command: `morphostack`.
- Short alias: `mst`.
- `doctor`, `init`, `dev`, and `dev --check` setup flow.
- Stack inspection and loading for TIFF/TIF, LSM, and CZI-style microscopy files.
- Metadata-aware voxel inspection for TIFF/CZI paths, with manual override support.
- Vesicle, RBC, and LimeSeg analysis profiles.
- Threshold suggestion, threshold sweep, rectangular ROI, frame/Z trimming, and preview scrubbing.
- Object selection through clicked seed, radius controls, max tracking distance, and polygon seed tools.
- Upload and local-path flows for preview, analyze, mesh preview, and validation.
- Per-frame metrics: area, perimeter, circularity, aspect ratio, elongation, deformation index, extent, equivalent diameter, solidity.
- 3D mesh measurement: surface area, volume, equivalent sphere diameter, sphericity.
- Plotly-based interactive 3D mesh preview in the browser.
- CSV export, JSON manifests, Markdown reports, SHA-256 provenance, batch summaries, and CSV validation.
- Real-data validation structure under `validation/`.
- DOPC vesicle validation run.
- RBC LSM smoke-test run.
- LimeSeg-lite active surfaces engine and tests.
- Full test suite currently passes: 168 tests.
- Web build currently passes.

## Current Working Tree Notes

Stabilization cleanup (2026-07-08) committed LimeSeg watershed/seed-mask
improvements, RBC Image 46 validation artifacts, and reference-folder
documentation. Local-only folders (`mcps/`, `scratch/`, `terminals/`,
`.clones/`) are documented in `REFERENCE_FOLDERS.md` and ignored by git.
DOPC validation timestamp-only manifest churn was reverted to avoid noise.

## Highest Priority Remaining Work

### 1. Freeze The Current Working Tree

Goal: make the current good state reproducible.

Tasks:

- Review the uncommitted LimeSeg and pipeline changes.
- Decide whether validation manifest changes should be committed or regenerated.
- Decide whether the RBC smoke-test output should become a committed validation artifact.
- Add `.gitignore` rules for scratch/terminal/MCP artifacts if they are local-only.
- Run full tests and web build after cleanup.
- Commit the clean state with a clear message.

Acceptance criteria:

- `git status --short` is clean except intentionally ignored local files.
- `python -m pytest` passes.
- `npm run build` passes.
- The app still loads LSM, CZI, and TIFF examples.

### 2. Validate On Real Multi-Object Vesicle And RBC Data

Goal: prove object selection and 3D mesh are not only synthetic-test correct.

Known real data candidates:

- `D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif`
- `C:\Users\systemm\Downloads\1650_z stack.czi`
- `C:\Users\systemm\Downloads\1644_z stack.czi`
- `D:\rbc data pranay\Image 46.lsm`
- `D:\rbc data pranay\Image 32.lsm`

Tasks:

- Create one validation run per file.
- For crowded stacks, select at least two different objects and compare metrics.
- Save screenshots or preview overlays showing the selected object.
- Record threshold, profile, ROI, Z range, seed point, radius, and calibration mode.
- Compare whether preview, analyze, and 3D mesh all target the same object.
- Record failure cases where tracking switches objects, loses object, or merges neighbors.

Acceptance criteria:

- At least one vesicle and one RBC crowded-stack validation run exists.
- Different selected objects produce different metrics when visually expected.
- Reports clearly state whether voxel calibration is real or default.
- Known limitations are written down, not hidden.

### 3. Lock Down Voxel Calibration

Goal: prevent fake biological units.

Tasks:

- Extract voxel sizes from TIFF/LSM/CZI metadata wherever possible.
- Show voxel source prominently in the UI: metadata, override, or default.
- Make default `1 x 1 x 1 um` visually scary enough that users do not trust it blindly.
- Add warnings in reports and manifests when voxel values are defaults.
- Add a small calibration panel explaining what X/Y/Z values mean.
- Store calibration in project settings.

Acceptance criteria:

- Surface area and volume outputs cannot be mistaken as biologically final when calibration is missing.
- Metadata-derived values are test-covered.
- Manual overrides are preserved in manifests and reports.

### 4. Finish RBC-Specific Science

Goal: make the RBC profile scientifically meaningful, not just a label on the vesicle pipeline.

Tasks:

- Ask the lab which RBC outputs matter most.
- Decide supported RBC metrics for the first paper/demo version.
- Candidate RBC outputs:
  - projected area
  - perimeter
  - circularity
  - aspect ratio
  - elongation
  - deformation index
  - solidity
  - equivalent diameter
  - thickness or Z-depth proxy if meaningful
  - volume and surface area only when calibration and segmentation support it
  - biconcavity-related descriptors only if imaging supports them
- Add RBC-specific warnings when the input is not suitable for a metric.
- Add RBC-specific report wording.
- Add tests with synthetic RBC-like shapes.

Acceptance criteria:

- RBC metrics are documented with formulas and limitations.
- Lab agrees the chosen metrics are useful.
- Reports distinguish exploratory RBC mesh demos from validated RBC morphometry.

### 5. Improve Object Selection Robustness

Goal: make crowded images reliable.

Current direction:

- Seed point or polygon defines target object.
- Connected components and centroid/edge tracking try to follow it across Z.
- LimeSeg profile can refine active surfaces from a seed.

Remaining tasks:

- Compare circle seed, polygon seed, ROI crop, threshold contour, and LimeSeg on the same crowded datasets.
- Add a debug overlay showing per-frame tracked object centroid/contour.
- Add a warning when tracking is lost on many frames.
- Add a warning when selected component touches ROI bounds or merges with neighbors.
- Consider IoU/overlap tracking between adjacent slices instead of centroid-only tracking.
- Consider watershed or distance-transform splitting when cells touch.
- Keep Cellpose/StarDist as later optional integrations, not immediate core dependencies.

Acceptance criteria:

- Users can see when tracking succeeded or failed.
- Analyze and 3D mesh use the same selected-object logic.
- Crowded examples have documented pass/fail behavior.

### 6. Manual Review And Correction Workflow

Goal: let a researcher fix bad segmentation before trusting output.

Tasks:

- Add frame-by-frame review table.
- Let users exclude bad frames from analysis/mesh.
- Let users mark selected contour as accepted/rejected.
- Add polygon/freehand correction for bad contours if needed.
- Save correction state in project/run metadata.
- Export overlays for lab notebook review.

Acceptance criteria:

- A user can detect and exclude a bad slice without editing code.
- Final reports list excluded frames and why.

### 7. 3D Mesh Viewer And Export Polish

Goal: make 3D outputs presentation-ready and interoperable.

Tasks:

- Add mesh export: OBJ, STL, PLY, or GLB.
- Add standalone HTML export for the interactive 3D viewer.
- Add mask export as TIFF/OME-TIFF where possible.
- Add ImageJ/Fiji ROI export later, likely through `roifile`.
- Add camera presets and reset view.
- Add color/opacity controls.
- Add screenshot/export button for presentations.
- Add stronger loading/progress state for large stacks.

Acceptance criteria:

- A researcher can export a mesh and open it outside MorphoStack.
- Presentation screenshots do not require manual browser hacks.

### 8. LimeSeg Profile Stabilization

Goal: make the LimeSeg-lite active-surface profile trustworthy enough to use as an advanced option.

Tasks:

- Review current uncommitted nearest-edge and hard seed-mask changes.
- Run LimeSeg profile on DOPC, multi-vesicle CZI, and RBC LSM data.
- Compare LimeSeg output against threshold-contour mesh output.
- Document when LimeSeg should be used and when it should not.
- Add parameters to UI only if users can understand them.
- Keep sane defaults.
- Add regression tests for touching objects, weak edges, and seed masks.

Acceptance criteria:

- LimeSeg is clearly labeled as advanced/experimental or stable.
- It does not silently produce convincing-looking wrong meshes.

### 9. UI Ergonomics For Researchers

Goal: make the web app feel like a lab tool, not a developer dashboard.

Tasks:

- Make workflow order clearer: load, inspect, calibrate, preview, select object, analyze, review, export.
- Reduce duplicated controls and dense panels.
- Improve status messages and error recovery.
- Show selected object state clearly.
- Show active profile and calibration state near outputs.
- Add run/session sidebar or recent runs list.
- Add better table scanning and report download controls.
- Make warnings prominent but not scary when expected.

Acceptance criteria:

- A biology user can run the demo without reading code.
- The UI makes it hard to forget calibration or selected object state.

### 10. Validation And Reference Dataset System

Goal: move from "it runs" to "we can trust changes".

Tasks:

- Create curated validation cases:
  - single vesicle
  - crowded vesicles
  - single RBC if available later
  - crowded RBCs
  - synthetic sphere/ellipsoid stacks with known geometry
  - touching-object failure case
- Store expected metrics where stable.
- Add validation reports comparing new runs to references.
- Include visual overlays in validation folders.
- Add a short validation README per dataset.

Acceptance criteria:

- Future implementation agents can run validation before/after changes.
- Scientific regressions are easier to detect than by eyeballing the UI.

### 11. Packaging And Install Path

Goal: make MorphoStack installable by lab users.

Tasks:

- Finalize `pyproject.toml` metadata for package distribution.
- Test editable install and normal wheel install.
- Add `morphostack app` or `mst app` as a friendlier launcher.
- Decide whether Node build assets are bundled into the Python package.
- Add a simple Windows install path.
- Later: pipx, GitHub Releases, winget/Scoop/Chocolatey, optional desktop wrapper.

Acceptance criteria:

- A new Windows machine can run MorphoStack from documented steps.
- Users do not need to understand Vite/npm during normal use.

### 12. Documentation For Lab And Paper Use

Goal: make the project explainable to the professor, labmates, and possibly reviewers.

Tasks:

- Update README to reflect LSM, LimeSeg, object selection, and current profiles.
- Update prototype usage guide with the current object selection modes.
- Add methods-style documentation for each metric.
- Add limitations page.
- Add validation page.
- Add troubleshooting page for common issues: unsupported file, default voxel size, empty mesh, tracking lost, bad threshold.
- Add citation/license notes for any external tools or algorithms used.

Acceptance criteria:

- The docs match the actual app.
- A presentation can cite outputs and limitations honestly.

## Suggested Implementation Order For Cursor Composer

1. Clean and commit the current working tree.
2. Update docs to match the actual feature set.
3. Create validation runs for multi-vesicle and multi-RBC data.
4. Add visual review overlays and selected-object diagnostics.
5. Stabilize LimeSeg profile on real data.
6. Add mesh/mask export.
7. Define RBC-specific science with lab feedback.
8. Package the app for non-developer use.

## Do Not Do Yet Unless There Is A Strong Reason

- Do not add Cellpose/StarDist as a required dependency yet.
- Do not rewrite the frontend from scratch.
- Do not replace the Python core with Java/Fiji integration.
- Do not chase perfect RBC science before the lab defines required outputs.
- Do not present default-voxel surface/volume as biological measurements.
- Do not commit local scratch folders or terminal logs as project artifacts.

## Current Bottom Line

MorphoStack has moved from a rough migration prototype to a serious internal lab tool prototype. The next work is less about adding random features and more about trust: validation, calibration, reviewer-friendly outputs, selected-object reliability, and clean packaging.
