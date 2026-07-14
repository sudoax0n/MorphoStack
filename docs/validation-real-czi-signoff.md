# Real CZI / LSM seeded-identity sign-off (manual)

This protocol is **separate from** synthetic unit tests and the labelled
touching suite (`scripts/validate_synthetic_touching.py`,
`tests/test_contact_qc_labelled_safety.py`).

**Synthetic pass does not establish publication-grade biological validity.**
Deterministic rings only prove computational identity, isolation, and
fail-closed gates. Lab review of real stacks is required before paper or
production claims.

Do **not** commit large raw CZI/LSM binaries into CI or the unit-test tree.

## Purpose

Confirm that Standard seeded isolation, contact QC, tracking gaps,
merge-safety rejects, and overlays behave acceptably on **representative real
data**.

## Prerequisites

1. **Voxel calibration** — record voxel size source (`metadata` vs `override` vs
   `default`) and spacing in µm. Default 1×1×1 µm is **not** biological. Note
   instrument log if available. Confirm XY (and Z if used) match the imaging
   session before trusting physical metrics.
2. **Software build** — known commit / wheel version of MorphoStack.
3. **Blinded contour-overlay review** — domain user scores overlays without
   knowing the case tier label until after scoring (optional second reviewer).

## Case selection (local lab data only)

Pick at least one stack (or FOV crop) in each row:

| Tier / phenotype | Content | Minimum |
| --- | --- | ---: |
| Easy | Isolated GUV/vesicle, clear membrane, little contact | 2 |
| Tangent contact | Neighbour touches target at a narrow contact zone | 1 |
| Broad / flat contact | Wide membrane apposition or flattened contact face | 1 |
| Weak membrane | Low SNR, broken arcs, or dim poles near a distractor | 1 |
| Deformed single | Legitimate flattened / elliptical / pear-shaped vesicle (no neighbour required) | 1 |
| Hard crowded (optional) | Multi-object FOV, gap-prone track | 1 |

Store paths and notes under lab storage (not necessarily in-repo). Optional
pointers in `validation/data-notes/` without binary blobs.

## Review procedure

For each stack / object:

1. Open in MorphoStack UI (or CLI analyze) with **Standard** profile.
2. Confirm calibration fields in the UI/manifest before analyzing.
3. Draw a **circle seed** on a clear equatorial-ish slice.
4. Scrub Z: note provisional vs exact/tracked labels if present.
5. Run **Analyze**; export metrics CSV + manifest + optional mask/overlay.
6. **Blinded contour-overlay review** by a domain user:
   - Contour stays on the intended object (yes / no / unsure).
   - Neighbour membrane contamination (none / mild / severe).
   - Gaps or merge-suspect / merge-rejected warnings (list codes).
   - ROI boundary or seed-disk clip flags (yes / no).
   - Mesh / volume plausible vs visual coverage (yes / no / N/A).

## Pass / reject criteria

Record **per-object** and aggregate:

| Outcome | Definition |
| --- | --- |
| Pass | Intended object isolated; no severe neighbour contamination on accepted frames |
| Safe reject | Frame lost or `circle_seed_merge_reject` / merge warning; **no** wrong-neighbour contour |
| Fail | Silent identity jump, mixed dual-object contour accepted, or severe contamination without reject |

Lab judgment bars:

- **Easy:** intended isolation on ≥90% of in-range slices; no severe neighbour
  contamination on accepted frames.
- **Tangent / broad contact:** no silent identity jump; residual contact either
  isolated correctly **or** rejected/lost with a clear warning. Prefer
  conservative rejection over an automatic mixed contour.
- **Weak membrane:** must not steal a bright neighbour; gap/reject is acceptable.
- **Deformed single:** must not be rejected solely for non-circular shape when
  isolation is clean.
- **Hard crowded:** no requirement for perfect isolation; **must not** silently
  accept a wrong neighbour as the target.

Document:

- Pass / safe-reject / fail counts (frames and objects).
- Number of **rejected frames** (gaps + merge rejects) and warning codes.
- Reviewer initials, date, software version, seed parameters, ROI/Z range.
- Voxel-calibration confirmation (`voxel_source`, spacing).

Do not claim biological truth solely from MorphoStack metrics.

## Calibration and reporting checklist

- [ ] `voxel_source` and spacing recorded in manifest
- [ ] If `default` voxels: physical units marked **uncalibrated**
- [ ] Software version / commit recorded
- [ ] Seed, ROI, Z range recorded
- [ ] Warning codes and rejected-frame count recorded
- [ ] Blinded overlay scores attached (or lab notebook reference)
- [ ] Explicit note: synthetic CI pass ≠ publication-grade biological validity

## Completed sign-off records (when present)

Look under `validation/runs/real-vesicle-seeded-signoff-YYYYMMDD/` for dated evidence
packs (`SIGNOFF.md`, `review_records.json`, object bundles, overlays). A missing or
**INCOMPLETE** pack means lab sign-off is not finished.

Latest attempted pack (partial, DOPC-only as of 2026-07-11):
`validation/runs/real-vesicle-seeded-signoff-20260711/SIGNOFF.md`.

## Out of scope for this protocol

- Automated CI binary downloads.
- Replacing synthetic unit tests with real CZI fixtures.
- Unverified claims that a contour “is” two cells without imaging evidence.
- Treating labelled-ring IoU gates as biological ground truth.
