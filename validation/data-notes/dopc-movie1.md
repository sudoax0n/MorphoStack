# DOPC Movie 1 Data Notes

## Source

- **File:** `syst202400052-sup-0001-movie1-dopc.tif`
- **Full path:** `D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif`
- **File size:** ~10.6 MB
- **Associated paper:** "Shape Analysis of Biomimetic and Plasma Membrane Vesicles"
  DOI: https://doi.org/10.1002/syst.202400052

## Stack Properties (as read by MorphoStack)

| Property | Value |
|----------|-------|
| Grayscale shape | (26, 447, 318) — 26 z-slices, 447 rows, 318 cols |
| Color shape | (26, 447, 318, 3) |
| Voxel source | **default** (1.0 µm x 1.0 µm x 1.0 µm) |
| Embedded calibration | None found in TIFF metadata |

## Calibration Disclaimer

> **Surface area and volume are computational outputs using the configured voxel size
> (default: 1.0 µm). Biological interpretation requires verified microscope calibration
> from the original acquisition metadata or instrument log.**

The actual voxel size for confocal images of GUVs (giant unilamellar vesicles) in
the context of this paper is likely in the range of 0.05–0.5 µm/pixel. Until the
exact instrument settings are confirmed from the original acquisition files or the
paper's Methods section, all reported `area_um2`, `perimeter_um`, `mesh_surface_area_um2`,
`mesh_volume_um3`, and related metrics should be treated as **pixel-scale outputs**,
not biological measurements.

**What to do:**
1. Check the paper's supplementary or methods for the objective/zoom/pixel size.
2. Apply `--voxel-x`, `--voxel-y`, `--voxel-z` overrides when the real calibration is known.
3. Re-run `validate_dopc.ps1` with the corrected voxel size.

## Content Description (visual inspection)

The movie contains confocal Z-sections through DOPC (1,2-dioleoyl-sn-glycero-3-phosphocholine)
giant unilamellar vesicles. Expect:

- Roughly circular to ellipsoidal bright membrane contours.
- Vesicle diameter in the range of 10–50 µm (typical for GUVs prepared by electroformation).
- Some frames may show partial membranes, noise, or out-of-focus regions.
- The largest contour per frame is typically the target GUV.

## Suggested Threshold Range

Based on `morphostack threshold --method otsu`, the auto-threshold is reported as part
of the `validate_dopc.ps1` run output. A manual sweep from 20 to 80 is provided in the
`sweep.csv` output to assess threshold sensitivity.

## Reference Code Notes

The Shape-Analysis reference code (`D:\Shape-Analysis\main.py`) processes this file using:
- Otsu thresholding (or manual input)
- `cv2.findContours` with `RETR_EXTERNAL, CHAIN_APPROX_SIMPLE`
- Ellipse fitting via `cv2.fitEllipse` for eccentricity/aspect ratio
- Volume from 3D slice integration
- Area and perimeter from `cv2.contourArea` and `cv2.arcLength`

MorphoStack uses a compatible approach (OpenCV contours, polygon area formula, mesh via
marching cubes). Metric naming differs slightly — see the checklist in
`reports/dopc-vs-reference.md`.
