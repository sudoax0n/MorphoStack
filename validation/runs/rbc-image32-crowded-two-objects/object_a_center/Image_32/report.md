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
- Seed center: `(293, 510)`
- Seed radius: `12` px
- Seed type: `circle`

## Tracking Diagnostics

- Tracked frames: 12 lost of 28 total

## Frame Summary

- Frames: 28
- Valid frames: 16
- Valid fraction: 0.571429
- Excluded frames: none

## Warnings

- `partial_contours` (warning): 12 of 28 frames did not produce a valid contour.
- `tracking_lost_many_frames` (warning): Object tracking was lost on 12 of 28 frames (43%). Metrics may mix frames or omit slices.
- `likely_neighbor_merge` (warning): Tracked component area grew sharply on 14 frame(s); neighbors may have merged.
- `default_voxel_size` (warning): Voxel spacing came from MorphoStack defaults. Physical units should be treated as uncalibrated.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 1446.78 | 187.5 | 3287.5 | 1016.4 |
| perimeter_um | 197.636 | 102.225 | 375.931 | 79.8114 |
| circularity | 0.435285 | 0.147785 | 0.866201 | 0.192828 |
| bbox_width_um | 47.375 | 16 | 80 | 20.2697 |
| bbox_height_um | 45.875 | 25 | 89 | 17.3561 |
| aspect_ratio | 1.22739 | 1 | 1.5625 | 0.166289 |
| elongation | 0.170479 | 0 | 0.36 | 0.110243 |
| deformation_index | 0.0971621 | 0 | 0.219512 | 0.0661797 |
| extent | 0.581967 | 0.379555 | 0.770497 | 0.0992115 |
| equivalent_diameter_um | 39.944 | 15.451 | 64.6976 | 15.7027 |
| solidity | 0.804149 | 0.600962 | 0.981 | 0.110625 |

## Mesh Summary

- Surface area: 39789 um^2
- Volume: 24045.1 um^3
- Equivalent sphere diameter: 35.8104 um
- Sphericity: 0.101252

## First 10 Frame Rows

| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |
| ---: | :---: | ---: | ---: | ---: | ---: |
| 0 | no | 0 | 0 | 0 | 0 |
| 1 | no | 0 | 0 | 0 | 0 |
| 2 | no | 0 | 0 | 0 | 0 |
| 3 | no | 0 | 0 | 0 | 0 |
| 4 | no | 0 | 0 | 0 | 0 |
| 5 | yes | 187.5 | 126.267 | 0.147785 | 0.155556 |
| 6 | yes | 743.5 | 143.439 | 0.454108 | 0.0833333 |
| 7 | yes | 824.5 | 181.38 | 0.314937 | 0.146341 |
| 8 | yes | 1081 | 211.765 | 0.302921 | 0.133333 |
| 9 | yes | 811.5 | 157.439 | 0.411411 | 0.075 |
