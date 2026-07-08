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
- Seed center: `(166.58, 304.13)`
- Seed radius: `12` px
- Seed type: `circle`

## Tracking Diagnostics

- Tracked frames: 15 lost of 28 total

## Frame Summary

- Frames: 28
- Valid frames: 13
- Valid fraction: 0.464286

## Warnings

- `partial_contours` (warning): 15 of 28 frames did not produce a valid contour.
- `tracking_lost_many_frames` (warning): Object tracking was lost on 15 of 28 frames (54%). Metrics may mix frames or omit slices.
- `likely_neighbor_merge` (warning): Tracked component area grew sharply on 12 frame(s); neighbors may have merged.
- `default_voxel_size` (warning): Voxel spacing came from MorphoStack defaults. Physical units should be treated as uncalibrated.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 2615.58 | 13 | 5181 | 2052.34 |
| perimeter_um | 263.103 | 34.6274 | 675.235 | 171.638 |
| circularity | 0.410276 | 0.0893539 | 0.710632 | 0.180176 |
| bbox_width_um | 64 | 8 | 105 | 37.1773 |
| bbox_height_um | 60.4615 | 8 | 92 | 30.3153 |
| aspect_ratio | 1.12022 | 1 | 1.20833 | 0.0463461 |
| elongation | 0.105728 | 0 | 0.172414 | 0.038522 |
| deformation_index | 0.0562418 | 0 | 0.0943396 | 0.0210288 |
| extent | 0.499385 | 0.203125 | 0.767072 | 0.151015 |
| equivalent_diameter_um | 50.6028 | 4.06843 | 81.2198 | 27.7418 |
| solidity | 0.804647 | 0.376812 | 0.964916 | 0.158836 |

## Mesh Summary

- Surface area: 12945.2 um^2
- Volume: 35361.5 um^3
- Equivalent sphere diameter: 40.7234 um
- Sphericity: 0.402465

## First 10 Frame Rows

| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |
| ---: | :---: | ---: | ---: | ---: | ---: |
| 0 | no | 0 | 0 | 0 | 0 |
| 1 | no | 0 | 0 | 0 | 0 |
| 2 | no | 0 | 0 | 0 | 0 |
| 3 | no | 0 | 0 | 0 | 0 |
| 4 | no | 0 | 0 | 0 | 0 |
| 5 | yes | 13 | 34.6274 | 0.136243 | 0 |
| 6 | yes | 3242 | 675.235 | 0.0893539 | 0.0769231 |
| 7 | yes | 4518 | 395.588 | 0.362802 | 0.0575916 |
| 8 | yes | 4856.5 | 353.948 | 0.48714 | 0.0569948 |
| 9 | yes | 5126 | 359.706 | 0.497845 | 0.0659898 |
