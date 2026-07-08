# Crowded vesicle validation (CZI 1650)

- Source: `C:\Users\systemm\Downloads\1650_z stack.czi`
- Profile: `vesicle`
- Threshold: `190.0`
- Seed frame: `105`
- Z range: `(90, 120)`

## Selected objects

- **object_a_left** seed `(359.97, 516.78, 105)` → mean area `2752.102950087345` µm²
- **object_b_right** seed `(479.06, 94.07, 105)` → mean area `1849.7278170739146` µm²

## Limitations

- Tracking can switch objects when vesicles/RBCs touch or move farther than the max tracking distance.
- Default-voxel LSM runs are exploratory; physical units require verified calibration.
- Mesh exports are for inspection only when voxel calibration is missing or default.

Distinct object metrics: `True` (ratio 1.49)
