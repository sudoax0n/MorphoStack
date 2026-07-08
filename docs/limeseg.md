# LimeSeg Profile Notes

MorphoStack ships a **LimeSeg-lite** active-surfaces profile for advanced segmentation when threshold contours are unstable.

## When to use

- Weak or uneven membrane signal where thresholding leaks into neighbors.
- Single seeded object with moderate spacing from neighbors.
- After ROI crop narrows the field.

## When to avoid

- Dense touching objects without ROI isolation — watershed pre-split helps but cannot guarantee separation.
- Default-voxel LSM stacks where quantitative mesh size matters.
- Fast batch runs — LimeSeg optimization is slower than threshold contours.

## Validation status

LimeSeg remains **experimental**. Compare against threshold-based mesh on the same seed before using LimeSeg outputs in figures or tables.

Regression tests cover seed masks, watershed pre-split, and touching-object cases in `tests/test_core_limeseg.py`.