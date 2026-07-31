# Changelog: Evolution from Shape-Analysis to MorphoStack

This changelog documents the transition from the **Shape-Analysis** research prototype to the production-ready **MorphoStack** biophysics suite.

---

## [1.0.0] - July 2026

### Added
* **Automated Voxel Metadata Loader**: Extracts voxel dimensions natively from TIFF/LSM tags and Zeiss CZI XML metadata, converting SI meters to microns automatically. Manual entry confirms are bypassed unless overridden.
* **Single-Object Seed Tracking**: Enables isolation of individual vesicles or RBCs in crowded multi-vesicle fields. By providing an initial seed point $(x, y, z)$, the pipeline tracks the target object across slices by scoring candidates based on boundary containment and size consistency.
* **Analysis Profiles**: Structured dedicated profiles for `"vesicle"` (default thresholding/skeletonization), `"rbc"` (red blood cell morphometry), and `"active_surfaces"` (contour deformation model).
* **Automated Batch Processing & Sweeps**:
  * Added `morphostack batch` CLI command to analyze every stack in a directory recursively and export a single combined CSV spreadsheet with statistical averages.
  * Added `morphostack sweep` to automatically process a stack across a range of thresholds to identify the mathematically optimal segmentation point.
* **Reproducible Project Configurations**: Introduced `morphostack.project.json` settings files to store reuseable ROIs, Z-ranges, and analysis profiles.
* **Multiple 3D Mesh Export Formats**: Exports the reconstructed 3D shape directly to Wavefront `.obj`, binary/ASCII `.stl`, `.ply`, and binary glTF `.glb` (for direct web viewing).

### Changed
* **Corrected 3D Mesh Scaling Error**:
  * *Problem*: Shape-Analysis downsampled stacks by 50% for rendering speed without scaling voxel spacing. This resulted in underestimating 3D volume by 8x and surface area by 4x.
  * *Fix*: MorphoStack calculates volume and area on the **original, full-resolution mesh** for the CSV spreadsheet. For browser rendering, it uses a decimated mesh but scales the voxel spacing *up* (`voxel * factor`) to preserve the true physical dimensions.
* **Outlier Contour Filtering**: Automatically filters out noisy/junk slices (areas < 10% of median area) to prevent floating spikes in the 3D mesh.
* **Centroid Alignment**: Uses affine transformations (`cv2.warpAffine`) to align the center of all Z-slices before meshing.
* **Grayscale Stack Normalization**: Standardizes multi-channel stacks to clean grayscale arrays for calculations while keeping color channels in memory for web display.
* **State Isolation**: Tracks frame modes (`STATE.frameSegModes`) to prevent global threshold slider changes from wiping custom manual drawings.
