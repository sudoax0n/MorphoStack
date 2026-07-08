# MorphoStack Improvements

This file is the living log for turning MorphoStack from a working research
prototype into a dependable local morphometry tool for biophysics lab use. Add
items when they come from current code, real datasets, test failures, reviewer
feedback, or lab workflow needs.

_Last consolidated from the old goal checklist: 2026-07-08._

## Progress Snapshot

| Milestone | Estimate |
| --- | ---: |
| Working demo / prototype | 99% |
| Internship / lab-usable internal tool | 99% |
| Paper-supporting, biologically validated tool | 84% |
| Publicly distributable open-source app | 84% |

**Bottom line:** MorphoStack is a credible internal lab tool. Remaining gap is
science sign-off, crowded-data Active Surfaces trust, and publishing the first
release — not basic functionality.

## Current Status

MorphoStack has a local Python CLI, FastAPI backend, and browser UI. The
canonical command is `morphostack`; the short alias is `mst`.

Supported workflow pieces include:

- stack inspection for TIFF/TIF, LSM, and CZI inputs
- metadata-aware voxel inspection with manual override and UI warnings
- threshold suggestion and threshold sweeps
- Z-range trimming, frame preview scrubbing, frame exclusion
- global XY ROI and object seed (circle, polygon), tracking diagnostics
- vesicle, RBC, and **active_surfaces** profile selection
- 3D mesh preview (Plotly), mesh export (OBJ/STL/PLY/GLB), mask export (TIFF)
- standalone mesh HTML export with camera presets and PNG screenshot
- upload progress for inspect / analyze / mesh-preview uploads
- project settings JSON import/export, batch analysis
- CSV validation, JSON manifests, Markdown reports, SHA-256 provenance
- real-data validation runs (DOPC, crowded CZI/RBC), synthetic sphere/ellipsoid
  regression, synthetic touching-failure negative reference
- Active Surfaces vs threshold comparison reports
- wheel packaging, GitHub Release workflow, `morphostack app` launcher
- `morphostack init`, `doctor`, `dev --check` for setup diagnostics
- 195+ tests; web build passes

The RBC profile records RBC intent but still uses the same threshold-contour
engine as vesicles until lab-defined metrics land.

## Remaining Work

### Blocked on lab input

- [ ] **RBC-specific science** — decide which RBC outputs matter for the first
  paper/demo version before adding more metrics.
- [ ] **Final author/repo citation line** — add once publication venue is chosen.

### Release and packaging

- [ ] **Publish `v0.1.0` GitHub Release** — tag, push, confirm workflow uploads wheel.
- [ ] **Verify pipx install** from release asset (`scripts/verify_release_wheel.ps1`
  for local smoke test first).
- [ ] **winget / Scoop manifests** (optional).

### Active Surfaces and segmentation

- [ ] **Crowded real-data Active Surfaces sign-off** — synthetic defaults are
  tuned (~10% sphere delta); crowded CZI/RBC previews still diverge; compare
  side-by-side before paper use.
- [ ] **Side-by-side preview comparison UI** — circle seed, polygon seed, ROI
  crop, threshold, and Active Surfaces on the same frame.
- [ ] **IoU / overlap tracking** between adjacent slices.
- [ ] **Watershed splitting** when cells touch (partial via Active Surfaces
  pre-split today).

### Manual review and UI ergonomics

- [ ] **Accept/reject contour marking** beyond frame exclude.
- [ ] **Polygon / freehand contour correction** after preview.
- [ ] **Workflow redesign** — run/session sidebar, less duplicated controls,
  clearer run state for researchers.

### Mesh, loading, and polish

- [ ] **Server-side progress** for local-path reads of very large CZI/LSM files
  (upload progress already done).
- [ ] **Fiji export bridge** (optional; deferred unless strongly needed).

### Suggested order

1. RBC science after lab feedback.
2. Crowded real-data Active Surfaces preview sign-off.
3. Publish `v0.1.0` and test pipx install.
4. Side-by-side preview UI and workflow redesign (optional polish).

### Do not do yet unless there is a strong reason

- Do not add Cellpose/StarDist as a required dependency.
- Do not rewrite the frontend from scratch.
- Do not replace the Python core with Java/Fiji integration.
- Do not chase perfect RBC science before the lab defines required outputs.
- Do not present default-voxel surface/volume as biological measurements.

## Known Gaps And Bugs To Watch

- RBC-specific science is not complete yet. The profile exists, but RBC-specific
  metrics, validation datasets, and domain warnings still need lab feedback.
- The web UI is functional, but still developer-style in places — see Remaining
  Work above.
- Manual ROI is rectangular only; polygon seeds exist for object selection but
  not full ImageJ-style ROI presets or manual contour editing.
- Mesh measurements depend on segmentation quality, voxel calibration, and stack
  sampling; reports must keep assumptions obvious.
- CSV validation proves regression stability, not biological truth, without
  curated references and manual review.

## Command Ownership

The project should own one clear command:

```bash
morphostack
```

The abbreviation should remain:

```bash
mst
```

Both commands should point to the same CLI entry point. The long command is
better for documentation and papers; the short command is better for daily lab
use.

First-run setup should stay under:

```bash
morphostack init
```

Useful first-run modes:

```bash
morphostack init
morphostack init --web
morphostack init --yes --web
morphostack init --extras analysis,api --web
```

The first run should continue to inspect OS, Python, CPU/RAM, optional Python
dependencies, Git/Node/npm availability, and web dependency state. It should ask
before installing requirements unless `--yes` is provided.

Before launching the local app, users should be able to run:

```bash
morphostack dev --check
```

That check should verify Python API dependencies, npm, web dependencies, and
free backend/web ports.

## Distribution Path

Recommended distribution stages:

1. Local source checkout for development:

   ```bash
   python -m pip install -e ".[dev]"
   morphostack init --web
   morphostack dev
   ```

2. Python user install through pip or pipx (wheel exists; first tagged release
   still pending — see Remaining Work):

   ```bash
   pipx install morphostack
   ```

3. GitHub Releases with wheel artifacts (workflow exists; `v0.1.0` not tagged yet).

4. Windows package managers such as winget, Scoop, or Chocolatey.

5. Optional one-command PowerShell installer for friendly lab machines:

   ```powershell
   irm <trusted-release-installer-url> | iex
   ```

Remote script installation should stay optional because university and institute
systems may block or distrust it.

## Web App Versus Desktop GUI

The best direction is a local web app served by the Python backend.

Reasons:

- It works across Windows, macOS, and Linux with the same UI code.
- Researchers can use it in a normal browser.
- The backend can stay Python-first for scientific code.
- The UI can later be wrapped as a desktop executable without rewriting the
  analysis engine.
- It avoids being locked into one GUI toolkit.

The near-term developer command should remain:

```bash
morphostack dev
```

The future user-facing command can become:

```bash
morphostack app
```

or:

```bash
mst app
```

That command should start the backend, open the browser, and hide development
details.

## Scientific Priorities

High priority:

- define RBC-specific outputs with the lab before adding too many metrics
- collect small representative vesicle and RBC test datasets
- create trusted reference CSV outputs for regression validation
- improve the interactive 3D preview with export controls, camera presets,
  stronger loading states, and optional Fiji export
- add manual contour correction after the preview overlay so users can fix
  difficult RBC/vesicle segmentations before exporting final metrics
- make voxel calibration unavoidable or visibly warned
- improve threshold sweep guidance so users can choose thresholds defensibly
- make reports suitable for lab notebooks and methods sections

Medium priority:

- add richer per-run provenance: MorphoStack version, dependency versions, OS,
  command line, and project settings snapshot
- add visual overlays for contour/segmentation review in the web UI
- add batch run folders with previews and reports for each stack
- make failed files in batch mode easier to inspect and retry
- add export formats useful for downstream plotting and statistics

Lower priority:

- desktop wrapper
- package-manager release automation
- remote installer script
- hosted documentation site

## Near-Term Implementation Plan

1. Stabilize the local app workflow: `init`, `doctor`, `dev --check`, and
   `dev`.
2. Improve the web UI around the existing backend instead of replacing the
   analysis engine.
3. Add reviewer-friendly outputs: reports, manifests, checksums, and validation.
4. Add RBC-specific metrics only after the biological requirements are clear.
5. Package the project after the CLI and web workflow are boringly reliable.

The guiding rule: keep scientific computation in tested Python modules, expose
it through a local API, and make the browser UI a clean layer on top.
