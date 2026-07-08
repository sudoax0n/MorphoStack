# MorphoStack Analysis Report

## Run Settings

- Source: `D:\rbc data pranay\Image 46.lsm`
- Source SHA-256: `097dcaa956d0aebece8c594307ed5fb7c53a1573d7cbca5416f5519835e77523`
- MorphoStack version: `0.1.0`
- Profile: `rbc`
- Threshold: `37.0`
- ROI: `full stack`
- Z range: `{'zmin': 0, 'zmax': 28}`
- Include mesh: `True`
- Prefer OpenCV contours: `True`
- Voxel source: `default`
- Voxel size: x=1 um, y=1 um, z=1 um

## Frame Summary

- Frames: 28
- Valid frames: 25
- Valid fraction: 0.892857

## Warnings

- `partial_contours` (warning): 3 of 28 frames did not produce a valid contour.
- `default_voxel_size` (warning): Voxel spacing came from MorphoStack defaults. Physical units should be treated as uncalibrated.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 2061.4 | 1 | 5237 | 1919.97 |
| perimeter_um | 209.274 | 4 | 440.014 | 133.585 |
| circularity | 0.443786 | 0.115827 | 0.785398 | 0.150582 |
| bbox_width_um | 51.4 | 1 | 105 | 35.8329 |
| bbox_height_um | 51.32 | 1 | 93 | 32.4761 |
| aspect_ratio | 1.30537 | 1 | 1.875 | 0.23711 |
| elongation | 0.210344 | 0 | 0.466667 | 0.131858 |
| deformation_index | 0.123773 | 0 | 0.304348 | 0.0849103 |
| extent | 0.594716 | 0.288235 | 1 | 0.128676 |
| equivalent_diameter_um | 43.1926 | 1.12838 | 81.6576 | 27.551 |
| solidity | 0.832026 | 0.427948 | 1 | 0.119949 |

## Mesh Summary

- Surface area: 25091.9 um^2
- Volume: 53394.9 um^3
- Equivalent sphere diameter: 46.7197 um
- Sphericity: 0.273286

## First 10 Frame Rows

| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |
| ---: | :---: | ---: | ---: | ---: | ---: |
| 0 | no | 0 | 0 | 0 | 0 |
| 1 | no | 0 | 0 | 0 | 0 |
| 2 | yes | 1 | 4 | 0.785398 | 0 |
| 3 | yes | 48.5 | 66.669 | 0.137121 | 0.304348 |
| 4 | yes | 167 | 65.1127 | 0.494988 | 0.16129 |
| 5 | yes | 2372.5 | 282.291 | 0.374128 | 0.0420168 |
| 6 | yes | 4121 | 440.014 | 0.267472 | 0.0752688 |
| 7 | yes | 4656 | 393.446 | 0.377966 | 0.0625 |
| 8 | yes | 4928.5 | 362.777 | 0.470593 | 0.0618557 |
| 9 | yes | 5180.5 | 363.948 | 0.491476 | 0.0606061 |
