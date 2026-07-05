# External Library Research Notes

Surveyed to inform MorphoStack development. Repos cloned to `D:\morphostack-research-temp\`
(outside the MorphoStack repo, not committed here).

---

## trimesh

- **Repo:** https://github.com/mikedh/trimesh
- **License:** MIT
- **Direct code reuse safe?** YES — MIT, permissive.
- **Reference only or integrate?** Can integrate when mesh export (OBJ/STL/PLY) is needed.
- **Useful files/functions/ideas:**
  - `trimesh.Trimesh` — mesh class with built-in volume, surface area, watertight checks.
  - `mesh.export("file.obj")` — simple OBJ/STL/PLY export.
  - `mesh.is_watertight` — mesh validation, immediately useful for validating MorphoStack's
    marching-cubes output.
  - `mesh.volume`, `mesh.area` — cross-check against MorphoStack's own mesh metrics.
  - `trimesh.creation.icosphere()` — useful for generating synthetic validation spheres.
- **Relevant now or later?**
  Later (next step): mesh export and validation. Would replace or complement the current
  `mesh.py` custom implementation. Does NOT need to touch the main app yet.

---

## roifile

- **Repo:** https://github.com/cgohlke/roifile (PyPI: `roifile`)
- **License:** BSD-3-Clause
- **Direct code reuse safe?** YES — BSD-3, permissive.
- **Reference only or integrate?** Can integrate when ImageJ/Fiji ROI import/export is required.
- **Useful files/functions/ideas:**
  - `roifile.ImagejRoi` — read/write `.roi` and `.zip` (multi-ROI) ImageJ files.
  - Useful for exporting MorphoStack contours as ImageJ-compatible ROIs.
  - Useful for importing user-drawn Fiji ROIs as MorphoStack ROI inputs.
- **Relevant now or later?**
  Later: ImageJ interop is useful for labs already using Fiji. Not blocking for current
  validation work.

---

## cellpose

- **Repo:** https://github.com/mouseland/cellpose
- **License:** BSD-3-Clause
- **Direct code reuse safe?** YES — BSD-3, permissive.
- **Reference only or integrate?** Reference/later integration; heavy dependency (PyTorch).
- **Useful files/functions/ideas:**
  - `cellpose.models.Cellpose` — instance segmentation for crowded fields.
  - `cellpose.io` — standard image I/O helpers.
  - Useful as a future optional segmentation engine for crowded vesicle/RBC images where
    simple thresholding fails.
  - The `--no_npy` flag and headless usage pattern is worth copying for CLI integration.
- **Relevant now or later?**
  Later. Do NOT add PyTorch to the main app now. The current thresholding pipeline is
  sufficient for isolated vesicles. Cellpose becomes relevant for dense images.

---

## GeoV

- **Repo:** https://github.com/Biophysical-Engineering-Group/GeoV
- **License:** **GPL v3** (confirmed in README: "licensed under the GPL v. 3 license")
- **Direct code reuse safe?** NO — GPL v3 is copyleft. Any derivative work must also be GPL v3.
- **Reference only or integrate?** Reference only. Do NOT copy any code into MorphoStack (MIT).
- **Useful files/functions/ideas:**
  - Reference implementation for GUV 3D reconstruction from confocal Z-stacks.
  - Thresholding finder approach (`thresholdfinder.py`) — useful as algorithm reference only.
  - 3D viewer approach — reference only.
  - Volume/surface area from 3D slice integration — algorithm concept is in public literature.
- **Relevant now or later?**
  Now (reference/validation): compare GeoV's outputs on DOPC against MorphoStack.
  Do NOT integrate any GeoV code. Use only as a validation cross-reference.

---

## redtell

- **Repo:** https://github.com/marrlab/redtell
- **License:** **No LICENSE file found** (all rights reserved by default under copyright law).
- **Direct code reuse safe?** NO — no license = all rights reserved. Contact authors before reuse.
- **Reference only or integrate?** Reference only. Study the approach; do NOT copy code.
- **Useful files/functions/ideas:**
  - `redtell.py` — RBC shape feature extraction from segmentation masks.
  - Morphology metrics for RBCs: discocyte/stomatocyte/echinocyte classification.
  - Useful as inspiration for RBC-specific metric presets in MorphoStack's profile system.
  - Algorithm ideas (not code) for deformation index and membrane roughness can be
    reimplemented independently.
- **Relevant now or later?**
  Later. Relevant when MorphoStack adds an RBC analysis profile. Contact Marr Lab
  (https://marr-lab.de) to request a permissive license if code reuse is desired.

---

## LimeSeg

- **Repo:** https://github.com/NicoKiaru/LimeSeg
- **License:** CC0 1.0 Universal (public domain dedication).
- **Direct code reuse safe?** YES — CC0, maximum permissiveness.
- **Reference only or integrate?** Reference for algorithm ideas; Java/Fiji plugin so no
  direct Python code to reuse.
- **Useful files/functions/ideas:**
  - 3D membrane fitting via active surface model ("SurfaceTension" parameter).
  - The approach of initialising surfaces from a seed point is similar to MorphoStack's
    object-seed tracking.
  - Useful as a ground-truth validation tool: run LimeSeg on the DOPC dataset in Fiji and
    compare exported surface area/volume against MorphoStack outputs.
  - The CC0 license means any algorithm ideas can be reimplemented without restriction.
- **Relevant now or later?**
  Now (reference/validation): run LimeSeg on DOPC as external ground truth.
  Later (integration): possibly implement LimeSeg-style active-surface refinement as an
  optional mesh-smoothing step.

---

## Summary Table

| Repo | License | Reuse Safe | Action |
|------|---------|-----------|--------|
| trimesh | MIT | YES | Integrate later for mesh export/validation |
| roifile | BSD-3 | YES | Integrate later for ImageJ ROI I/O |
| cellpose | BSD-3 | YES | Later — heavy dep (PyTorch) |
| GeoV | **GPL v3** | **NO** | Reference ONLY — copyleft, cannot reuse in MIT project |
| redtell | **No license** | **NO** | Reference only — contact authors for license |
| LimeSeg | CC0 | YES | Reference/validation now; Java so no direct Python reuse |

---

## Immediate Actions from Research

1. **Validation:** Use LimeSeg (Fiji) on DOPC data as external ground-truth comparison.
2. **Mesh cross-check:** Install `trimesh` in a scratch venv, load MorphoStack OBJ output,
   verify `is_watertight` and compare `area`/`volume` to MorphoStack's reported values.
3. **GeoV:** Attempt to reproduce their reported surface area/volume for DOPC vesicles and
   compare; contact authors for license clarification.
4. **Do not add** any of these dependencies to `pyproject.toml` at this stage.

---

*Survey date: 2026-07-05. Clone location: D:\morphostack-research-temp\ (not tracked in repo).*
