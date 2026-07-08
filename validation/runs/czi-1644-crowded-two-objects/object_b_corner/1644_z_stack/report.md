# MorphoStack Analysis Report

## Run Settings

- Source: `C:\Users\systemm\Downloads\1644_z stack.czi`
- Source SHA-256: `e9319b31b969c062cddabc0188d176f99fcee553119d6abb811866cd1858aa2d`
- MorphoStack version: `0.1.0`
- Profile: `vesicle`
- Threshold: `484.0`
- ROI: `full stack`
- Z range: `{'zmin': 40, 'zmax': 80}`
- Include mesh: `True`
- Prefer OpenCV contours: `True`
- Voxel source: `metadata`
- Voxel size: x=0.219218 um, y=0.219218 um, z=0.5 um

## Object Selection

- Seed frame: `56`
- Seed center: `(637, 170)`
- Seed radius: `12` px
- Seed type: `circle`

## Tracking Diagnostics

- Tracked frames: 0 lost of 40 total

## Frame Summary

- Frames: 40
- Valid frames: 40
- Valid fraction: 1
- Excluded frames: none

## Warnings

- `likely_neighbor_merge` (warning): Tracked component area grew sharply on 7 frame(s); neighbors may have merged.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 21.9275 | 0.0961127 | 92.8449 | 31.2775 |
| perimeter_um | 63.0526 | 5.16397 | 223.804 | 55.0079 |
| circularity | 0.0569503 | 0.00904586 | 0.195524 | 0.046505 |
| bbox_width_um | 8.71938 | 0.87687 | 17.5374 | 5.65872 |
| bbox_height_um | 12.3858 | 1.31531 | 44.282 | 10.7922 |
| aspect_ratio | 1.51295 | 1 | 2.8 | 0.514292 |
| elongation | 0.274918 | 4.21885e-15 | 0.642857 | 0.195425 |
| deformation_index | 0.175403 | 2.11387e-15 | 0.473684 | 0.142286 |
| extent | 0.133985 | 0.0261956 | 0.407523 | 0.100936 |
| equivalent_diameter_um | 3.99205 | 0.349821 | 10.8726 | 3.46158 |
| solidity | 0.284555 | 0.0655738 | 0.710309 | 0.144486 |

## Mesh Summary

- Surface area: 1774.47 um^2
- Volume: 487.562 um^3
- Equivalent sphere diameter: 9.76511 um
- Sphericity: 0.168824

## First 10 Frame Rows

| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |
| ---: | :---: | ---: | ---: | ---: | ---: |
| 40 | yes | 9.53919 | 58.8454 | 0.0346176 | 0.029703 |
| 41 | yes | 10.1639 | 59.5406 | 0.0360283 | 0.027027 |
| 42 | yes | 11.125 | 68.9605 | 0.0293975 | 0.0839695 |
| 43 | yes | 39.4302 | 223.804 | 0.00989242 | 0.453237 |
| 44 | yes | 85.7325 | 123.134 | 0.0710563 | 0.245283 |
| 45 | yes | 85.7325 | 97.7742 | 0.112696 | 0.153846 |
| 46 | yes | 85.3721 | 79.6517 | 0.169097 | 0.236842 |
| 47 | yes | 92.8449 | 128.833 | 0.070293 | 0.452915 |
| 48 | yes | 88.4237 | 93.0266 | 0.1284 | 0.242604 |
| 49 | yes | 22.7066 | 150.513 | 0.0125955 | 0.264368 |
