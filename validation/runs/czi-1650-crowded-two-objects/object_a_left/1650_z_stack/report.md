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
- Seed center: `(359.97, 516.78)`
- Seed radius: `12` px
- Seed type: `circle`

## Tracking Diagnostics

- Tracked frames: 0 lost of 30 total

## Frame Summary

- Frames: 30
- Valid frames: 30
- Valid fraction: 1

## Warnings

- `roi_boundary_touch` (warning): Selected component touches the ROI or crop boundary on 4 frame(s); area may be clipped.

## Metric Summary

| Metric | Mean | Min | Max | Std |
| --- | ---: | ---: | ---: | ---: |
| area_um2 | 2752.1 | 432.651 | 10084.2 | 3319.15 |
| perimeter_um | 1984.82 | 539.824 | 3819.32 | 815.244 |
| circularity | 0.00876556 | 0.00174428 | 0.0331572 | 0.00936037 |
| bbox_width_um | 112.773 | 64.45 | 142.711 | 19.1196 |
| bbox_height_um | 130.617 | 82.2066 | 207.38 | 30.4143 |
| aspect_ratio | 1.17478 | 1.00205 | 1.56352 | 0.146588 |
| elongation | 0.137065 | 0.00204918 | 0.360417 | 0.0946872 |
| deformation_index | 0.0764954 | 0.00102564 | 0.219822 | 0.0575673 |
| extent | 0.153434 | 0.0411769 | 0.561439 | 0.161109 |
| equivalent_diameter_um | 50.5321 | 23.4706 | 113.312 | 30.8316 |
| solidity | 0.218333 | 0.0538838 | 0.791055 | 0.22237 |

## Mesh Summary

- Surface area: 90311.8 um^2
- Volume: 40267.6 um^3
- Equivalent sphere diameter: 42.5258 um
- Sphericity: 0.0629086

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
