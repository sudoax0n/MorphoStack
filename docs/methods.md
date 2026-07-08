# Methods Supplement (Draft)

Paste-ready methods text for vesicle/GUV and RBC shape analysis with MorphoStack.
Replace bracketed placeholders with instrument-specific calibration values before submission.

## Image preprocessing

Microscopy Z-stacks in TIFF, LSM, or CZI format were loaded in MorphoStack (v0.1.0).
Grayscale slices were optionally cropped to a rectangular region of interest and trimmed to a
selected Z-frame range. Voxel spacing was taken from file metadata when available; otherwise
manual overrides were applied after verification against the acquisition log.

## Segmentation and contour extraction

For vesicle and RBC profiles, each frame was thresholded and the largest external contour was
retained. When multiple objects were present, a seed point (circle or polygon) constrained
connected-component selection and frame-to-frame centroid tracking. Contour area and perimeter
were computed from the polygon representation; circularity followed the isoperimetric ratio
\(4\pi A / P^2\).

## 3D surface reconstruction

When enabled, per-frame binary masks were stacked and meshed with marching cubes on a
downsampled contour volume. Reported mesh surface area, volume, equivalent-sphere diameter,
and sphericity are computational geometry outputs in micrometers only when voxel calibration
is verified.

## Quality control

Frames with lost tracking, ROI boundary contact, or likely neighbor merges were flagged in
run warnings. Users could exclude individual frames and re-analyze before exporting summary
metrics, CSV tables, JSON manifests, and mesh files.

## Reproducibility

Each analysis run recorded source path, SHA-256 checksum, threshold, profile, voxel source,
object seed, excluded frames, and MorphoStack version in the exported manifest.

## Limitations

Default 1×1×1 µm voxel spacing is a placeholder. Biological interpretation of absolute area,
volume, or sphericity requires validated microscope calibration. Active-surfaces
segmentation is experimental on crowded or touching objects and should be compared against
threshold segmentation on representative frames before publication use.