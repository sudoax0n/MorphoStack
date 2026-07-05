# MorphoStack Improvements

This file is the living technical roadmap for turning MorphoStack from a working
research prototype into a dependable local morphometry tool for biophysics lab
use. It should stay evidence-based: add items when they come from current code,
real datasets, test failures, reviewer feedback, or lab workflow needs.

## Current Status

MorphoStack now has a local Python CLI, FastAPI backend, and browser UI. The
canonical command is `morphostack`; the short alias is `mst`.

Supported workflow pieces include:

- stack inspection for TIFF/CZI inputs
- threshold suggestion and threshold sweeps
- Z-range trimming for top/bottom stack slices
- per-frame shape analysis
- vesicle and RBC profile selection
- optional 3D mesh measurements for surface area, volume, equivalent sphere
  diameter, and sphericity
- project settings JSON import/export
- batch analysis
- CSV validation against reference outputs
- JSON manifests, Markdown reports, source SHA-256 provenance, and quality
  warnings
- `morphostack init`, `doctor`, and `dev --check` for setup diagnostics

The RBC profile currently records RBC intent and creates a clean branch point,
but still uses the same threshold-contour measurement engine as vesicles.

## Known Gaps And Bugs To Watch

- RBC-specific science is not complete yet. The profile exists, but RBC-specific
  metrics, validation datasets, and domain warnings still need to be designed
  with lab feedback.
- The web UI is functional, but it is still a developer-style interface. It
  needs stronger researcher ergonomics: clearer run state, better file/session
  organization, less dense controls, and friendlier error recovery.
- Mesh measurements should be treated as optional and carefully documented.
  Surface area and volume depend on segmentation quality, voxel calibration, and
  stack sampling; reports should make those assumptions obvious.
- Threshold-based analysis can fail silently in bad images unless warnings are
  prominent. Existing warnings cover missing/partial contours and default voxel
  sizes, but more domain-specific warnings are needed.
- Validation currently compares CSV outputs, which is useful for regression
  testing. It does not prove biological correctness without curated reference
  datasets and manual review.
- Packaging is still source-checkout oriented. End users should eventually get a
  simpler install path that does not require understanding Python, Node, or Git.

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

2. Python user install through pip or pipx after packaging metadata is ready:

   ```bash
   pipx install morphostack
   ```

3. GitHub Releases with signed or checksummed Windows artifacts.

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
