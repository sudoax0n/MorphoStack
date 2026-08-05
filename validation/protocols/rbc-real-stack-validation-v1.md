# RBC real-stack validation protocol v1

**Status:** engineering protocol only — **no biological acceptance thresholds approved by the lab yet**.  
**Depends on:** Phases 1–4 engineering baseline on `feat/rbc-3d-morphometry`.

## Purpose

Define the evidence required before MorphoStack may present any RBC capability as **biologically validated**. Until the input bundle is complete and lab-approved thresholds are recorded here, all biological promotions remain **WITHHELD**.

## Required input bundle

| Item | Requirement |
| --- | --- |
| Stacks | ≥3 complete Zeiss (or equivalent confocal) RBC Z-stacks spanning intended use conditions |
| Calibration | Verified X, Y, and Z spacing (µm) per stack; no inferred axes |
| Acquisition record | Objective, NA, immersion, excitation/emission, pinhole, Z step |
| Annotations | 10–20 slices covering **center**, **rim**, **cap**, low-signal, and difficult boundary; preferred: two blinded annotators |
| Preparation note | Known morphology classes / artifacts |
| PSF / beads | Measurements **or** explicit lab decision that surface/thickness stays unavailable |
| Estimator addendum | Separate document with formula, units, priors, uncertainty, failure conditions, citations |

## Split rules

- Cell IDs used for **tune** and **evaluate** must not overlap.
- Changing any acceptance threshold creates **protocol version 2** (do not rewrite v1 history).
- Raw stacks and annotations are immutable; derived masks/meshes record source hashes.

## Metric families (real-stack runner)

When an accepted evidence bundle exists, evaluation must report:

1. `segmentation` (Dice, IoU)
2. `surface_distance` (ASSD, HD95 where surfaces exist)
3. `topology` (outer/inner loop errors, hole preservation)
4. `z_linking` (gaps, merges, lost tracks)
5. `morphometry` (volume/SA bias only where references exist)
6. `repeatability` (fixed seed re-runs)
7. `capability_decision` (pass / withhold per capability)

## Lab-approved acceptance thresholds

| Capability | Gate | Lab approval date | Approver |
| --- | --- | --- | --- |
| Calibrated 2D projected metrics | *pending* | — | — |
| Validated 3D occupancy | *pending* | — | — |
| Validated 3D surface / thickness | *pending* | — | — |
| Production estimated model | *pending* | — | — |

**v1 note:** empty thresholds mean **no biological promotion**. Engineering phantom gates (Phase 4) remain separate and do not fill this table.

## Outcome recording

- Accepted bundle → `validation/runs/rbc-real-v1/` + report under `validation/reports/`.
- Missing bundle → evidence validator refuses with exact codes; capability decision stays WITHHELD.
