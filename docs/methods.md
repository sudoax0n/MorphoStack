# Methods Supplement (Draft)

Paste-ready methods text for vesicle/GUV and RBC shape analysis with MorphoStack **v1.0.0**.  
Replace bracketed placeholders with instrument-specific values before submission. Read [limitations.md](limitations.md) first.

## Image preprocessing

Microscopy Z-stacks in TIFF, LSM, or CZI format were loaded in MorphoStack (v1.0.0). Multi-channel or color stacks were converted to grayscale for analysis. Slices were optionally cropped to a rectangular region of interest and trimmed to a selected Z-frame range `[zmin, zmax)`. Voxel spacing was taken from file metadata when available; otherwise manual overrides of `[vx, vy, vz]` µm were applied after verification against the acquisition log. Analyses that retained the software default spacing of 1 × 1 × 1 µm were treated as uncalibrated and were not used for absolute biological dimensions.

## Object selection (crowded fields)

When multiple objects appeared in the field of view, a user-defined seed (circular neighborhood or polygon) on a chosen frame constrained connected-component selection. The selected component was tracked across Z using overlap-first association with centroid-distance fallback. Tracking diagnostics (lost frames, ROI boundary contact, likely neighbor merge) were recorded in the run manifest.

## Segmentation and 2D metrics

For vesicle and RBC profiles, each frame was intensity-thresholded and an object contour was extracted. Contour area and perimeter were computed from the polygon representation with anisotropic pixel spacing applied along X and Y. Circularity was evaluated as the isoperimetric quotient \(4\pi A / P^2\). Additional descriptors included bounding-box aspect ratio, elongation, deformation index, extent, equivalent diameter, and solidity (area relative to convex hull). Frame-level metrics were exported as CSV.

## 3D surface reconstruction

When enabled, per-frame binary masks derived from contours were stacked and converted to a triangular surface mesh using marching cubes with voxel spacing \((v_z, v_y, v_x)\). Reported mesh surface area, volume, equivalent-sphere diameter, and sphericity are computational geometry outputs in micrometers only when voxel calibration was verified. Mesh files were exported as OBJ, STL, PLY, or GLB as needed.

## Active surfaces (optional, experimental)

For cases where global thresholding merged neighboring objects or failed on weak membrane signal, an experimental active-surfaces (surfel) profile was optionally applied after seeding. Active-surfaces outputs were compared to threshold-based meshes on the same seed before use in figures. Parameter defaults and validation status are documented in the MorphoStack active-surfaces notes.

## Quality control and reproducibility

Frames with lost tracking, ROI boundary contact, or likely neighbor merges were flagged in run warnings. Individual frames could be excluded and the analysis re-run. Each export recorded source path, SHA-256 checksum of the source file, MorphoStack version, profile, threshold, voxel source, ROI, Z range, object seed, excluded frames, and warning codes in a JSON manifest alongside optional Markdown reports.

## Limitations statement (short form)

Absolute area, volume, and sphericity require validated microscope calibration. Default voxel spacing is a computational placeholder. The RBC profile currently shares the vesicle threshold-contour engine; RBC-specific morphometrics require separate validation. Active-surfaces segmentation is experimental on crowded or touching objects.

## Related

[metrics.md](metrics.md) · [citations.md](citations.md) · [validation.md](validation.md)
