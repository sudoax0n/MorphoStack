# Crowded vesicle validation (CZI 1644)

- Source: `C:\Users\systemm\Downloads\1644_z stack.czi`
- Profile: `vesicle`
- Threshold: `484.0`
- Seed frame: `56`
- Z range: `(40, 80)`

## Selected objects

- **object_a_center** seed `(337.0, 319.0, 56)` → mean area `96.23586835536116` µm²
- **object_b_corner** seed `(637.0, 170.0, 56)` → mean area `21.927517259446358` µm²

## Limitations

- Tracking can switch objects when vesicles/RBCs touch or move farther than the max tracking distance.
- Default-voxel LSM runs are exploratory; physical units require verified calibration.
- Mesh exports are for inspection only when voxel calibration is missing or default.

Distinct object metrics: `True` (mean area delta 74.31 um², ratio 4.39)
