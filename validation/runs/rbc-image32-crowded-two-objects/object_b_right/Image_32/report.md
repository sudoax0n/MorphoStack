# MorphoStack Analysis Report

## Run Settings

- Source: `D:\rbc data pranay\Image 32.lsm`
- Source SHA-256: `fa348e37b28cedb35ac72828f73c3f19b77ce99c88e3a52d451a434bea80dd73`
- MorphoStack version: `0.1.0`
- Profile: `rbc`
- Threshold: `49.0`
- ROI: `full stack`
- Z range: `{'zmin': 0, 'zmax': 28}`
- Include mesh: `True`
- Prefer OpenCV contours: `True`
- Voxel source: `default`
- Voxel size: x=1 um, y=1 um, z=1 um

## Object Selection

- Seed frame: `16`
- Seed center: `(556, 345)`
- Seed radius: `12` px
- Seed type: `circle`

## Tracking Diagnostics

- Tracked frames: 9 lost of 28 total

## Frame Summary

- Frames: 28
- Valid frames: 19
- Valid fraction: 0.678571
- Excluded frames: none

## Warnings

- `partial_contours` (warning): 9 of 28 frames did not produce a valid contour.
- `tracking_lost_many_frames` (warning): Object tracking was lost on 9 of 28 frames (32%). Metrics may mix frames or omit slices.
- `likely_neighbor_merge` (warning): Tracked component area grew sharply on 17 frame(s); neighbors may have merged.
- `default_voxel_size` (warning): Voxel spacing came from MorphoStack defaults. Physical units should be treated as uncalibrated.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 2053.95 | 42 | 3016 | 933.341 |
| perimeter_um | 192.701 | 91.397 | 220.593 | 29.75 |
| circularity | 0.633125 | 0.0471457 | 0.850798 | 0.245545 |
| bbox_width_um | 50.6316 | 14 | 63 | 14.2763 |
| bbox_height_um | 50.8421 | 15 | 62 | 13.5928 |
| aspect_ratio | 1.03828 | 1 | 1.15789 | 0.0455614 |
| elongation | 0.0351136 | 0 | 0.136364 | 0.0399293 |
| deformation_index | 0.0183028 | 0 | 0.0731707 | 0.0212773 |
| extent | 0.688072 | 0.2 | 0.777778 | 0.164112 |
| equivalent_diameter_um | 48.6113 | 7.31273 | 61.9685 | 15.878 |
| solidity | 0.88755 | 0.297872 | 0.981126 | 0.195356 |

## Mesh Summary

- Surface area: 8445.28 um^2
- Volume: 40516.1 um^3
- Equivalent sphere diameter: 42.6131 um
- Sphericity: 0.675495

## First 10 Frame Rows

| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |
| ---: | :---: | ---: | ---: | ---: | ---: |
| 0 | no | 0 | 0 | 0 | 0 |
| 1 | no | 0 | 0 | 0 | 0 |
| 2 | yes | 42 | 91.397 | 0.0631823 | 0.0344828 |
| 3 | yes | 1586 | 220.593 | 0.409572 | 0.0588235 |
| 4 | yes | 1969.5 | 209.38 | 0.564542 | 0.0555556 |
| 5 | yes | 2353.5 | 212.208 | 0.65675 | 0.00884956 |
| 6 | yes | 2604 | 201.966 | 0.802225 | 0 |
| 7 | yes | 2761 | 207.966 | 0.80222 | 0 |
| 8 | yes | 2940 | 211.137 | 0.828759 | 0.00813008 |
| 9 | yes | 2989 | 210.794 | 0.845317 | 0.016129 |
