# MorphoStack Analysis Report

## Run Settings

- Source: `D:\rbc data pranay\Image 46.lsm`
- Source SHA-256: `097dcaa956d0aebece8c594307ed5fb7c53a1573d7cbca5416f5519835e77523`
- MorphoStack version: `0.1.0`
- Profile: `rbc`
- Threshold: `43.0`
- ROI: `full stack`
- Z range: `{'zmin': 0, 'zmax': 28}`
- Include mesh: `True`
- Prefer OpenCV contours: `True`
- Voxel source: `default`
- Voxel size: x=1 um, y=1 um, z=1 um

## Object Selection

- Seed frame: `10`
- Seed center: `(290.61, 731.79)`
- Seed radius: `12` px
- Seed type: `circle`

## Tracking Diagnostics

- Tracked frames: 18 lost of 28 total

## Frame Summary

- Frames: 28
- Valid frames: 10
- Valid fraction: 0.357143

## Warnings

- `partial_contours` (warning): 18 of 28 frames did not produce a valid contour.
- `tracking_lost_many_frames` (warning): Object tracking was lost on 18 of 28 frames (64%). Metrics may mix frames or omit slices.
- `default_voxel_size` (warning): Voxel spacing came from MorphoStack defaults. Physical units should be treated as uncalibrated.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 2274.55 | 295.5 | 3133.5 | 1060.57 |
| perimeter_um | 218.138 | 147.095 | 268.049 | 29.6742 |
| circularity | 0.56941 | 0.17162 | 0.82439 | 0.253338 |
| bbox_width_um | 53.3 | 27 | 63 | 12.8534 |
| bbox_height_um | 62.4 | 36 | 69 | 9.5205 |
| aspect_ratio | 1.21287 | 1.03279 | 1.72727 | 0.208355 |
| elongation | 0.155042 | 0.031746 | 0.421053 | 0.120464 |
| deformation_index | 0.0890203 | 0.016129 | 0.266667 | 0.0764987 |
| extent | 0.611018 | 0.304012 | 0.761538 | 0.169 |
| equivalent_diameter_um | 51.5463 | 19.397 | 63.164 | 15.4604 |
| solidity | 0.863756 | 0.622458 | 0.979525 | 0.149469 |

## Mesh Summary

- Surface area: 7977.76 um^2
- Volume: 23610.8 um^3
- Equivalent sphere diameter: 35.5935 um
- Sphericity: 0.498896

## First 10 Frame Rows

| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |
| ---: | :---: | ---: | ---: | ---: | ---: |
| 0 | no | 0 | 0 | 0 | 0 |
| 1 | no | 0 | 0 | 0 | 0 |
| 2 | no | 0 | 0 | 0 | 0 |
| 3 | no | 0 | 0 | 0 | 0 |
| 4 | no | 0 | 0 | 0 | 0 |
| 5 | no | 0 | 0 | 0 | 0 |
| 6 | yes | 2541 | 268.049 | 0.444413 | 0.0866142 |
| 7 | yes | 2927.5 | 227.037 | 0.713699 | 0.0615385 |
| 8 | yes | 3058 | 220.451 | 0.790722 | 0.0534351 |
| 9 | yes | 3133.5 | 218.551 | 0.82439 | 0.0307692 |
