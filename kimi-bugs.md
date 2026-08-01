# Bug Log

Found during a deep audit on 2026-07-31. Not yet fixed.

## Bug 1 (HIGH): Wrong µm calibration on ImageJ/Fiji TIFFs

- **Where:** `src/morphostack/core/io.py:107-108`, `src/morphostack/core/io.py:221-232`
- **What:** `voxel_from_tiff` reads pixel size from TIFF `XResolution`/`YResolution` tags but never reads the `ResolutionUnit` tag. TIFF resolutions are pixels *per unit* (2 = inch, 3 = cm), not pixels per micron.
- **Impact:** Files saved by ImageJ/Fiji with micron calibration (`resolutionunit=3`, cm) come out **10,000× too small**; inch-unit files come out **25,400× too small**. Every µm value in CSV exports, manifests, mesh spacing, and sweep summaries is silently wrong for those files, while `voxel_source="metadata"` makes it look trustworthy.
- **Reproduced:** with tifffile 2026.3.3 — a cm-unit file with true 0.5 µm pixels yields `x_um=5e-05`; an inch-unit file with true 1.0 µm pixels yields `3.937e-05`.
- **Fix:** read `ResolutionUnit` in `voxel_from_tiff` and scale the result: unit 2 → ×25400, unit 3 → ×10000, unit absent/1 → keep current µm behavior. Same fix pass should honor the `unit=` token ImageJ writes next to `spacing=` in `image_description_spacing_um` (`io.py:235-245`).
- **Careful:** `tests/test_core_io.py:107-118` pins the current behavior for files *without* a unit tag — the fix must keep that unchanged.

## Bug 2 (LOW): Missing single TIFF resolution axis invents 1.0 µm

- **Where:** `src/morphostack/core/io.py:114-117`
- **What:** If a TIFF has `XResolution` but no `YResolution` (or vice versa), the missing axis silently defaults to 1.0 µm instead of copying the present axis — fabricating anisotropy that feeds perimeter, deformation index, and mesh spacing.
- **Impact:** Wrong measurements for cameras with square pixels when only one tag exists (rare — most writers emit both tags). The CZI reader (`io.py:189-193`) already mirrors x↔y "like Fiji/Bio-Formats", so the TIFF path contradicts the repo's own convention.
- **Fix:** when exactly one of `XResolution`/`YResolution` is present, mirror it to the missing axis, matching the CZI branch.


---

## Bug 3 (MEDIUM): ImageJ `unit=` token ignored — nm/mm z-spacing read as µm

- **Where:** `src/morphostack/core/io.py:235-245` (`image_description_spacing_um`)
- **What:** The regex extracts `spacing=<number>` from the ImageJ `ImageDescription` but never parses the adjacent `unit=` token.
- **Impact:** `spacing=500.0 unit=nm` is read as **500.0 µm** instead of 0.5 µm (z-spacing inflated ×1000; inverse for `unit=mm`). Volume and z-axis metrics silently corrupt. `unit=nm` is common in acquisition software.
- **Reproduced:** confirmed by running the function in the project venv.
- **Fix:** also parse `unit\s*=\s*(\w+)` and scale: nm → ÷1000, mm → ×1000, micron/um → unchanged; unknown unit → return None instead of guessing.
- *(Related to Bug 1 — same fix pass.)*

## Bug 4 (MEDIUM-LOW): Skeleton perimeter assumes square XY pixels

- **Where:** `src/morphostack/core/skeleton.py:124-171` (`calculate_vs_perimeter` takes one scalar `voxel_size_um`); called from `preview.py:242`, fed by `pipeline.py:742`, `pipeline.py:1019`, `pipeline.py:1130` — all pass only `voxel_size.x_um`.
- **What:** The Vossepoel–Smeulders perimeter constants assume square pixels. With `x_um ≠ y_um`, `skel_perimeter_um` is silently wrong, while `docs/metrics.md:32` advertises the contour `perimeter_um` as "anisotropic-safe" — results can be misread as interchangeable.
- **Trigger:** anisotropic XY pixels (rare in confocal; z-anisotropy irrelevant since skeleton is per-slice 2D).
- **Fix:** resample chain step lengths with per-axis spacing, or warn + document the square-pixel assumption when `x_um != y_um`.

## Bug 5 (LOW): Skeleton chain-walk stops at first connected component

- **Where:** `src/morphostack/core/skeleton.py:155-166`
- **What:** The greedy 8-neighbor walk only walks the chain reachable from the first pixel. Disconnected skeleton fragments or residual spurs are silently excluded — the function returns a plausible-looking partial perimeter instead of signaling incompleteness.
- **Trigger:** noisy masks whose pruned skeleton keeps spur fragments or disjoint components.
- **Fix:** restart the walk from an unvisited node when it stalls (≥3 nodes remain), or warn when `len(ordered) < len(coords)`.

## Bug 6 (LOW): Tracking distance converts µm→px using x spacing only

- **Where:** `src/morphostack/core/pipeline.py:1062` and `pipeline.py:1624` (plus a hardcoded `40.0` floor heuristic at `pipeline.py:1627`)
- **What:** A physical jump tolerance (isotropic in µm) is converted to pixels with `voxel_size.x_um` only. With `x_um ≠ y_um` the y-tolerance differs from the user's setting by the anisotropy factor.
- **Trigger:** tracking/jump-gating on XY-anisotropic stacks (rare, same caveat as Bug 4).
- **Fix:** convert per-axis (ellipse in xy-µm space), or use `max(x_um, y_um)` and document.


---

## Bug 7 (LOW): Two seed-mapping paths round half-pixels differently

- **Where:** `src/morphostack/core/pipeline.py:190-191` (`StackViewTransform.to_local_seed` uses Python's banker's rounding) vs `src/morphostack/core/seed_mapping.py` (`_nearest_int` rounds half-away-from-zero)
- **What:** For an exactly-half-pixel seed coordinate (e.g. `x=32.5`), the two paths snap to different pixels (32 vs 33) — a 1-px divergence between viewer-3D seeds and tracked positions, while the tracking cache key stores the sub-pixel coordinate as identity.
- **Reproduced:** `to_local_seed(ObjectSeed(x=32.5, y=41.5, …))` → `(22, 32, 2)` but `_nearest_int` gives `33/42`.
- **Trigger:** seed placed at an exactly-half-pixel coordinate inside a z-cropped/ROI run.
- **Fix:** use `_nearest_int` from `seed_mapping` for `local_x`/`local_y` in `to_local_seed`.

## Bug 8 (LOW): `touches_seed_disk` clipping warning checked against wrong center

- **Where:** `src/morphostack/core/pipeline.py:1152-1157`
- **What:** The check compares against `sres.center_xy` — the *result* centroid — but the disk that actually clipped the mask is centered on the *search center* (previous tracked center, `seeded_vesicle.py:1145-1146`). When the per-frame centroid drifts more than 1.5 px from the search center, genuine disk clipping goes unflagged and the exported warning under-reports.
- **Trigger:** drifting GUVs — routine in real data — where the accepted center moved >1.5 px and the mask hit the 1.15·R search disk rim.
- **Fix:** carry the frame's actual search center through `SeededSliceResult` (e.g. a `search_center_xy` field set in `_advance_one`) and pass that to `_solid_mask_touches_seed_disk`.


---

## Bug 9 (HIGH): Batch mode silently overwrites results when stacks share a name

- **Where:** `src/morphostack/core/batch.py:313` and `:316`, reached via CLI `src/morphostack/cli/main.py:1141-1143`
- **What:** Per-stack outputs are keyed by filename *stem only*. Two inputs that share a stem overwrite each other: `stack.tif` + `stack.tiff`, or `a/stack.tif` + `b/stack.tif` with `--recursive`. Both are reported `ok` in the summary, but the second stack's `metrics.csv` / `manifest.json` / `report.md` silently replaces the first's.
- **Impact:** silent loss of analysis output — you think you measured 20 stacks, you have 19.
- **Reproduced:** confirmed both collision variants map to the same output paths.
- **Trigger:** `morphostack batch dir --out s.csv --bundle-dir bundles` or `--metrics-dir` with any stem collision.
- **Fix:** when the target bundle dir / metrics filename already exists for a different source, disambiguate (append extension or index) or fail that stack instead of overwriting.

## Bug 10 (MEDIUM): Seed tuning flags silently ignored without seed coordinates

- **Where:** `src/morphostack/cli/main.py:711-716` (`object_seed_from_cli`)
- **What:** `--seed-max-dist-um` / `--seed-radius` without `--seed-x/y/frame` are silently dropped — you get a full *unseeded* analysis with your constraint discarded, no warning. Sibling option groups (voxel, sweep) correctly error in this situation; seed flags fall outside the completeness check.
- **Reproduced:** `object_seed_from_cli(None, None, None, 25.0, 5.0)` → `None`, no message.
- **Fix:** treat "any seed flag set" as requiring x/y/frame — exit 2 with the same all-or-nothing message as the other groups.

## Bug 11 (MEDIUM, security): Wildcard CORS + arbitrary-path file writes on the local API

- **Where:** `src/morphostack/api/app.py:390-396` and `:3527-3535` (`allow_origins=["*"]`), combined with `/mesh-export` (`app.py:1609`) and `/mask-export` (`app.py:1649-1653`) writing to a request-supplied `destination`
- **What:** Any website open in your browser can POST to the running local server and write attacker-chosen content to any path (overwriting existing files); `/inspect` doubles as a file-existence probe. Classic localhost drive-by.
- **Trigger:** `morphostack dev`/`serve` running while you browse to a malicious page.
- **Fix:** restrict `allow_origins` to `http://127.0.0.1:*` / `http://localhost:*` (or drop CORS and rely on same-port serving).

## Bug 12 (LOW): Leftover DEBUG print dumps in `/analyze`

- **Where:** `src/morphostack/api/app.py:935-943` and `:969-972`
- **What:** `print("=== DEBUG ANALYZE REQUEST ===")` etc. dumps every request's local paths, ROI, seeds, and frame list to the server console on each call — dev debugging shipped in an endpoint; noisy and leaks local file paths into logs.
- **Fix:** delete the print statements (or route through `logging.debug`).

## Bug 13 (LOW): `sweep` reports invalid parameters as runtime failure (exit 1, not 2)

- **Where:** `src/morphostack/cli/main.py:1016` with blanket catch at `:1033-1035`
- **What:** `--step 0` or `stop < start` prints "Failed to run threshold sweep: ..." and exits 1, while every other CLI usage error exits 2. Misleading message (looks like a stack failure) and inconsistent scripting behavior.
- **Reproduced:** confirmed exit code 1 for `--step 0`.
- **Fix:** validate start/stop/step before the `try` and return 2.


---

## Bug 14 (HIGH): Web preview never sends the selected profile — non-vesicle previews computed as `vesicle`

- **Where:** `apps/web/src/main.ts:1872-1889` (`previewJsonBody` omits `profile`) vs `src/morphostack/api/app.py:254` (`PreviewRequest.profile` defaults to `"vesicle"`)
- **What:** Analyze, Sweep, Mesh, and even tracking corrections all send the selected profile — only `/api/preview` omits it. The backend feeds `request.profile` into `obtain_exact_seeded_slice` (`app.py:1246`) and into the tracking cache key (`app.py:1334`), so preview overlays and the tracking cache are computed under `vesicle` while a later Analyze uses the real profile — preview and analysis disagree, and correction anchors won't match the cached preview.
- **Trigger:** pick Mode = `rbc` or `active_surfaces`, place an object seed, run preview.
- **Fix:** one line — add `profile: readProfile(),` to `previewJsonBody`'s return object.

## Bug 15 (MEDIUM): 3D seed pick sets the 2D frame scrubber to a global index in a local control

- **Where:** `apps/web/src/main.ts:5104-5109` (`applyObjectSeedFrom3D`)
- **What:** The frame slider is local to the current z-range (max = frame count − 1; requests re-add `zmin`), but a 3D seed jump stores the *global* `frame_index` directly. With Z Range start > 0, the next preview requests `zmin + global_index` — the wrong slice, with a seed marker baked for the intended one.
- **Trigger:** zmin=10, 3D seed-pick at global z=15 → next preview shows global slice 25.
- **Fix:** subtract the z-range start (`selectedObjectSeed.frame_index - (readZRange()?.zmin ?? 0)`) and clamp before assigning to the slider/input.

## Bug 16 (LOW): Emptying the threshold field silently sends `threshold: 0`

- **Where:** `apps/web/src/main.ts:5832-5838` (`readNumber`; `Number("") === 0` passes the finite guard)
- **What:** An emptied threshold input sends literal `0` to the backend (no auto sentinel — `app.py:252`, flows into `analyze_frame` at `pipeline.py:719`), producing a degenerate full-frame mask with no error surfaced.
- **Trigger:** clear the Threshold input → Run Preview/Analyze.
- **Fix:** throw on empty/non-positive threshold, or restore the field default when blank.
