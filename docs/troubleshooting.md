# MorphoStack Troubleshooting

## Unsupported or unreadable file

- Supported extensions: `.tif`, `.tiff`, `.lsm`, `.czi`.
- Run `morphostack inspect path\to\stack` and check shape plus voxel source.
- Large CZI files may take several seconds to inspect; wait for the CLI to finish.

## Default voxel size (1 × 1 × 1 µm)

- The UI highlights default calibration in red. Reports and manifests emit `default_voxel_size`.
- Fix: provide `--voxel-x/y/z` on CLI, manual calibration in the web UI, or use a file with embedded metadata (many CZI files).
- Do not cite surface area or volume from default-calibration runs in papers.

## Empty mesh or mesh export skipped

- Raise contrast: adjust threshold or run `morphostack threshold --method otsu`.
- Ensure contours exist: check `valid_frame_count` in the manifest.
- For crowded stacks, set an object seed on the target vesicle/RBC.
- LimeSeg requires a seed and is slower; try vesicle/RBC profile first.

## Tracking lost / wrong object

- Enable **Show tracked-object debug overlay** in the web UI after Analyze.
- Increase seed radius slightly or reduce `max_tracking_dist_um` only when jumps are genuinely small.
- Crop with ROI to exclude neighbors.
- Read `tracking_lost_*` and `likely_neighbor_merge` warnings in the report.

## Bad threshold

- Use **Suggest Threshold** or `morphostack threshold --method otsu`.
- Run a sweep: `morphostack sweep stack.tif --start 20 --stop 200 --step 10 --out sweep.csv`.
- RBC stacks often need lower thresholds than vesicle stacks.

## Web UI cannot reach API

- Start dev mode: `morphostack dev` or `morphostack dev --check`.
- Confirm `morphostack doctor` shows API dependencies installed (`morphostack init`).

## LimeSeg looks wrong

- LimeSeg is experimental. Compare threshold mesh and LimeSeg mesh on the same seed.
- Avoid LimeSeg when objects are densely touching without ROI isolation.
- See `docs/limitations.md` for profile guidance.