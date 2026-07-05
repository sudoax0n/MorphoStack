# DOPC Smoke-Test vs Reference Code Comparison Checklist

**Run:** `dopc-smoke-test`
**Date:** 2026-07-05
**Input:** `D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif`
**Reference A:** `D:\Shape-Analysis` (optimised MorphoStack predecessor)
**Reference B:** `D:\tanmays original code\Shape-Analysis` (Tanmay Pandey's original GUI code)

---

## Calibration Disclaimer

> Surface area and volume are computational outputs using the configured voxel size
> (default: 1.0 µm). Biological interpretation requires verified microscope calibration.
> All numeric comparisons below assume 1 µm/pixel unless otherwise noted.

---

## Checklist

### 1. Stack Loading

| Check | Expected | MorphoStack | Status |
|-------|----------|-------------|--------|
| Frame count | 26 | 26 | PASS |
| Stack shape | (26, 447, 318) | (26, 447, 318) | PASS |
| Voxel source | No metadata; fallback to 1 µm | voxel_source=default | PASS |
| File loaded without error | Yes | Yes | PASS |

### 2. Threshold Selection

| Check | Reference approach | MorphoStack | Notes |
|-------|-------------------|-------------|-------|
| Auto-threshold method | Otsu (cv2) | Otsu (skimage) | Both use Otsu |
| Reported threshold value | ~30–60 range typical | See threshold cmd output | Run to confirm |
| Consistent with visual inspection | Yes | Run to verify | Visual check needed |

### 3. Contour Detection

| Check | Reference (Shape-Analysis) | MorphoStack | Status |
|-------|---------------------------|-------------|--------|
| Method | cv2.findContours RETR_EXTERNAL | cv2 or fallback polygon | Compatible |
| Selects largest contour | Yes (max area) | Yes (largest connected component) | Compatible |
| Frame coverage (valid frames) | ~20–26 expected | See valid_frame_count in manifest | Run to verify |
| Contour type | Nx2 int array | Nx2 float64 array | Minor diff, no impact |

### 4. 2D Shape Metrics

| Metric | Reference column | MorphoStack column | Notes |
|--------|-----------------|-------------------|-------|
| Area (pixel units) | `area` (from cv2.contourArea * x * y) | `area_px2` | Reference scales by voxel; MorphoStack stores both |
| Area (µm²) | `area` (scaled) | `area_um2` | Equivalent at 1 µm/px |
| Perimeter (µm) | `perimeter` (from cv2.arcLength * x) | `perimeter_um` | Equivalent at 1 µm/px |
| Circularity | `circularity` = 4π·A/P² | `circularity` = 4π·A/P² | Same formula |
| Aspect ratio | `aspect_ratio` = major/minor (ellipse) | `aspect_ratio` = bbox major/minor | Different method — note discrepancy |
| Eccentricity | `eccentricity` (ellipse fit) | Not present | MorphoStack uses `elongation` instead |
| Solidity | `solidity` (hull from cv2) | `solidity` (hull from custom impl) | Same definition |
| Equivalent diameter | Not explicit | `equivalent_diameter_um` | MorphoStack extension |
| Elongation | Not present | `elongation` = 1 - minor/major | MorphoStack extension |
| Deformation index | Not present | `deformation_index` = (maj-min)/(maj+min) | MorphoStack extension |
| Extent | Not present | `extent` = area / bbox_area | MorphoStack extension |

**Aspect ratio / eccentricity discrepancy:** Reference uses `cv2.fitEllipse` to measure
the ellipse axes. MorphoStack uses the bounding box. For near-circular vesicles the
values should be similar; for elongated shapes they will differ. This is a known
intentional difference — MorphoStack avoids `fitEllipse` because it requires ≥5 points
and can fail on sparse contours.

### 5. 3D Mesh Metrics

| Metric | Reference (3D map) | MorphoStack | Notes |
|--------|-------------------|-------------|-------|
| Volume | Integration of slice areas * z_step | `mesh_volume_um3` (marching cubes) | Different method — both valid |
| Surface area | Not directly computed | `mesh_surface_area_um2` | MorphoStack extension |
| Sphericity | Not directly computed | `mesh_sphericity` | MorphoStack extension |
| Equivalent sphere diameter | Not directly computed | `mesh_equivalent_sphere_diameter_um` | MorphoStack extension |

**Volume method note:** The reference code integrates per-slice contour areas times the
z-step (Cavalieri method). MorphoStack uses marching cubes on the full 3D binary mask.
For a complete dataset (all 26 frames with clean contours) both should give similar
volumes. For partial stacks, the marching-cubes approach may under-estimate due to
open top/bottom surfaces.

### 6. CSV Column Compatibility

| MorphoStack column | Present in reference CSV | Compatible |
|-------------------|--------------------------|-----------|
| frame_index | Yes (varies: `frame`, `z`) | Yes |
| threshold | No (not saved in ref) | N/A |
| profile | No | N/A |
| method | No | N/A |
| has_contour | No | N/A |
| area_px2 | Yes (`area` * 1/voxel^2) | Yes |
| perimeter_px | Yes (`perimeter` * 1/voxel) | Yes |
| area_um2 | Yes (`area`) | Yes |
| perimeter_um | Yes (`perimeter`) | Yes |
| circularity | Yes | Yes |
| bbox_width_um | Yes (derived from ellipse) | Approx |
| bbox_height_um | Yes (derived from ellipse) | Approx |
| aspect_ratio | Yes (ellipse) | Different method |
| elongation | No | MorphoStack only |
| deformation_index | No | MorphoStack only |
| extent | No | MorphoStack only |
| equivalent_diameter_um | No | MorphoStack only |
| solidity | Yes | Yes |
| mesh_surface_area_um2 | No | MorphoStack only |
| mesh_volume_um3 | Partial (slice integration) | Different method |
| mesh_equivalent_sphere_diameter_um | No | MorphoStack only |
| mesh_sphericity | No | MorphoStack only |

### 7. Area / Perimeter Trends Across Frames

Expected behaviour for a vesicle Z-stack:
- Area should be roughly parabolic: small at top/bottom slices, maximum at equator.
- Perimeter should follow the same trend.
- Circularity should be high (>0.7) for round GUVs.

Check `metrics.csv` for monotonicity violations or anomalous frames.

### 8. Runtime / Usability

| Aspect | Reference | MorphoStack | Notes |
|--------|-----------|-------------|-------|
| Interface | Interactive GUI (matplotlib) | CLI + web UI | MorphoStack is headless-friendly |
| Per-frame manual correction | Yes (PolygonSelector) | Object seed tracking | Different approach |
| Batch processing | No | Yes (`batch` command) | MorphoStack extension |
| CSV export | Yes | Yes | Both produce CSV |
| Mesh export | 3D surface plot (matplotlib) | JSON manifest + optional OBJ | MorphoStack more scriptable |
| Runtime (26 frames, no mesh) | ~seconds (with GUI) | < 5s expected headless | Run to confirm |
| Runtime (26 frames, with mesh) | N/A | < 30s expected | Run to confirm |

---

## How to Update This Checklist

After running `.\scripts\validate_dopc.ps1`:

1. Open `validation\runs\dopc-smoke-test\metrics.csv` and check frame counts and
   metric ranges.
2. Open `validation\runs\dopc-smoke-test\manifest.json` and verify `valid_frame_count`.
3. Compare area/circularity trends visually or with a quick pandas summary.
4. Update the "Status" column above from "Run to verify" to PASS/FAIL/NOTE.
5. If voxel calibration is determined, re-run with `--voxel-x X --voxel-y Y --voxel-z Z`
   and record the corrected values here.

---

## Open Questions

- [ ] What is the real pixel size for this confocal dataset?
- [ ] Does the reference code (`D:\Shape-Analysis`) produce a saved CSV for this file? If so,
      run `morphostack validate` to compare numerically.
- [ ] Are all 26 frames expected to contain a valid vesicle contour, or are some
      out-of-focus (valid_frame_count < 26 is expected)?
- [ ] Is the mesh watertight? (use `trimesh` for cross-check — see research-notes.md).
