# MorphoStack Analysis Report

## Run Settings

- Source: `C:\Users\systemm\Downloads\1650_z stack.czi`
- Source SHA-256: `9a8d42c04b63f7ee37ef8a5a6c8d70911a6326bd6d680b9362f75a110de46372`
- MorphoStack version: `0.1.0`
- Profile: `vesicle`
- Threshold: `190.0`
- ROI: `full stack`
- Z range: `{'zmin': 90, 'zmax': 120}`
- Include mesh: `True`
- Prefer OpenCV contours: `True`
- Voxel source: `metadata`
- Voxel size: x=0.219218 um, y=0.219218 um, z=0.5 um

## Object Selection

- Seed frame: `105`
- Seed center: `(479.06, 94.07)`
- Seed radius: `12` px
- Seed type: `circle`

## Tracking Diagnostics

- Tracked frames: 0 lost of 30 total

## Frame Summary

- Frames: 30
- Valid frames: 30
- Valid fraction: 1

## Warnings

- `roi_boundary_touch` (warning): Selected component touches the ROI or crop boundary on 24 frame(s); area may be clipped.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 1849.73 | 132.563 | 10084.2 | 3090.41 |
| perimeter_um | 1457.42 | 467.046 | 3819.32 | 1039.53 |
| circularity | 0.00678682 | 0.00174428 | 0.0301979 | 0.00613542 |
| bbox_width_um | 81.1105 | 26.9638 | 142.711 | 37.6049 |
| bbox_height_um | 89.8281 | 39.8976 | 207.38 | 54.4886 |
| aspect_ratio | 1.26618 | 1.00395 | 1.92683 | 0.18073 |
| elongation | 0.196098 | 0.00393701 | 0.481013 | 0.101391 |
| deformation_index | 0.112335 | 0.00197239 | 0.316667 | 0.0647905 |
| extent | 0.129363 | 0.0445688 | 0.513153 | 0.119989 |
| equivalent_diameter_um | 36.2692 | 12.9917 | 113.312 | 32.2442 |
| solidity | 0.18514 | 0.0729391 | 0.684804 | 0.163297 |

## Mesh Summary

- Surface area: 48788.1 um^2
- Volume: 27745.1 um^3
- Equivalent sphere diameter: 37.5603 um
- Sphericity: 0.0908436

## First 10 Frame Rows

| Frame | Contour | Area (um^2) | Perimeter (um) | Circularity | Deformation index |
| ---: | :---: | ---: | ---: | ---: | ---: |
| 90 | yes | 3251.49 | 2899.12 | 0.00486139 | 0.0482456 |
| 91 | yes | 3092.69 | 3147.22 | 0.00392367 | 0.0818505 |
| 92 | yes | 10084.2 | 2048.5 | 0.0301979 | 0.040625 |
| 93 | yes | 9793.29 | 3409.61 | 0.0105859 | 0.200508 |
| 94 | yes | 9104.57 | 2592.71 | 0.0170201 | 0.10785 |
| 95 | yes | 8681.65 | 2155.6 | 0.0234787 | 0.141329 |
| 96 | yes | 1763.72 | 3121.43 | 0.00227474 | 0.0713725 |
| 97 | yes | 1545.59 | 2603.45 | 0.00286554 | 0.0628183 |
| 98 | yes | 1522.31 | 2634.24 | 0.00275677 | 0.0889262 |
| 99 | yes | 2024.78 | 3819.32 | 0.00174428 | 0.211538 |
