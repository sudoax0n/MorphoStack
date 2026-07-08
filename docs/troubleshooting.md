# Troubleshooting

## Unsupported or unreadable file

- Supported: `.tif`, `.tiff`, `.lsm`, `.czi`.
- Run `morphostack inspect path/to/stack` and check shape + voxel source.
- Large CZI files can take several seconds; wait for the command to finish.

## Default voxel size (1 × 1 × 1 µm)

- UI highlights default calibration; manifests/reports emit `default_voxel_size`.
- **Fix:** `--voxel-x/y/z`, manual UI calibration, or a file with reliable metadata.
- Do not publish absolute surface/volume from default-calibration runs.

## Empty mesh or mesh export skipped

- Adjust threshold (`morphostack threshold --method otsu` or sweep).
- Check `valid_frame_count` in the manifest.
- Crowded stacks: set an object seed on the target.
- Active surfaces needs a seed and is slower; try `vesicle`/`rbc` first for QC.

## Tracking lost / wrong object

- Enable **Show tracked-object debug overlay** after Analyze in the UI.
- Nudge seed radius; tighten `max_tracking_dist_um` only when jumps are small.
- Crop with ROI to exclude neighbors.
- Read `tracking_lost_*` and `likely_neighbor_merge` in the report.

## Bad threshold

- **Suggest Threshold** or `morphostack threshold --method otsu`.
- Sweep: `morphostack sweep stack.tif --start 20 --stop 200 --step 10 --out sweep.csv`.
- RBC stacks often need lower thresholds than bright vesicle membranes.

## Web UI cannot reach API

```bash
morphostack doctor
morphostack init          # analysis/api deps
morphostack init --web    # npm deps for apps/web
morphostack dev --check
morphostack dev
```

- Default UI: `http://127.0.0.1:5173` (dev) or `http://127.0.0.1:8000` (`app`).
- Busy ports: `morphostack dev --api-port 8123 --web-port 5123`.

## `morphostack` / `mst` not found

- Use the venv scripts: `./.venv/Scripts/morphostack` (Windows) or activate the venv.
- Confirm install: `python -m pip install -e ".[all]"` from the repo root.
- Both names map to the same entry point in `pyproject.toml`.

## Active surfaces looks wrong

- Experimental — compare threshold vs active-surfaces mesh on the same seed.
- Avoid dense touching fields without ROI isolation.
- See [active-surfaces.md](active-surfaces.md) and [limitations.md](limitations.md).

## Tests fail after a change

```bash
pytest -q
pytest tests/test_core_metrics.py -q
```

- Prefer synthetic fixtures for unit tests; put large real-data cases under `validation/` and mark slow integration tests `@pytest.mark.slow`.

## Related

[getting-started.md](getting-started.md) · [usage.md](usage.md) · [validation.md](validation.md)
