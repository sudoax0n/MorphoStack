# Acquisition & annotation checklist (real-data promotion PoC)

Use this before claiming holdout scoring. **Do not commit private raw files.**

## Incomplete sign-off (required wording)

> Touching-vesicle real-data sign-off incomplete. Synthetic and isolated-stack results do not establish accuracy on crowded or contacting vesicles.

## Minimum PoC corpus

| Requirement | Min |
| --- | ---: |
| Labelled target objects (S1–S8) | 12 |
| Independent acquisitions | 3 |
| Contact objects (S2+S3) | 4 |
| Negative seeds (S9) | 3 |
| Holdout contact labelled + calibrated | ≥1 object with frame masks |

Freeze `holdout_manifest.json` **before** scoring a promotion candidate.

## Per-acquisition fields

- [ ] `source_id`, `source_basename`, `source_sha256`
- [ ] `format`, dtype, shape axes / channel used
- [ ] `voxel_source` ∈ metadata | override | default
- [ ] `spacing_um` {z,y,x}
- [ ] `calibrated_biological_units` true **only** if verified (never with default 1×1×1)
- [ ] lab path ref under lab storage or `validation/data-notes/` (not private secrets in public commits)
- [ ] acquisition notes (bleach, tilt, contact FOV, etc.)

## Per-object fields

- [ ] `object_id`, `source_id`, primary + secondary `stratum_ids`
- [ ] frozen seed (circle/polygon, frame, radius/points)
- [ ] ROI / Z range if used
- [ ] `partition` train | tune | holdout
- [ ] `contact_group_id` shared for touching pairs (**same partition**)
- [ ] annotator / adjudicator initials for holdout contact

## Annotation density (PoC)

- [ ] Seed frame always labelled
- [ ] Contact span every Z ±2 frames
- [ ] Cap entry/exit: first/last 5 visible frames
- [ ] Quiet mid-track every k=3 (Z≤40) or k=5 (longer)
- [ ] Uncertain frames: `exclude_from_contour_metrics` / boundary flags set
- [ ] Dual review or full adjudicator pass on holdout S2/S3 contact spans

## Leakage rules

- [ ] Split by object_id / source_id — never random frames of same object
- [ ] Touching pair objects stay in one partition
- [ ] Holdout IDs listed in frozen manifest before scoring
- [ ] Synthetic not mixed into real holdout scores

## Timing card (Gate D)

- [ ] Machine CPU/RAM/GPU/OS, Python, commit
- [ ] Cold vs warm separated
- [ ] Provisional p95, seed exact p95, target-Z p95, full-track wall
- [ ] Attempts / method counts from manifest
- [ ] CZI open cost itemized when present

## Run harness

```text
python scripts/run_real_data_promotion_gates.py --corpus path/to/corpus --out path/to/report
```

Expect **BLOCKED** until labelled calibrated holdout contact exists.
