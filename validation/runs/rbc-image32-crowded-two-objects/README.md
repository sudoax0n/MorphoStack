# Crowded RBC validation (Image 32)

- Source: `D:\rbc data pranay\Image 32.lsm`
- Profile: `rbc`
- Threshold: `49.0`
- Seed frame: `16`
- Z range: `(0, 28)`

## Selected objects

- **object_a_center** seed `(293.0, 510.0, 16)` → mean area `1446.78125` µm²
- **object_b_right** seed `(556.0, 345.0, 16)` → mean area `2053.9473684210525` µm²

## Limitations

- Tracking can switch objects when vesicles/RBCs touch or move farther than the max tracking distance.
- Default-voxel LSM runs are exploratory; physical units require verified calibration.
- Mesh exports are for inspection only when voxel calibration is missing or default.

Distinct object metrics: `True` (mean area delta 607.17 um², ratio 1.42)
