# RBC acquisition tier assessment v1

**Outcome: Tier C (upper/lower surface refinement) WITHHELD**

## Tiers (protocol summary)

| Tier | Meaning | MorphoStack surface/thickness |
| --- | --- | --- |
| A | Inspection / pixel preview only | WITHHELD |
| B | Calibrated 2D + optional occupancy engineering | Dimple/rim thickness WITHHELD |
| C | Sufficient Z sampling, SBR, cap coverage, membrane separation, RI + PSF/bead evidence | Surface refinement may be considered |

## Assessment without lab stacks

No Zeiss RBC evidence bundle is registered under `validation/references/rbc-annotations-v1/`.  
Without:

- verified anisotropic sampling records,
- cap coverage statistics,
- membrane separation / SBR evidence,
- bead/PSF measurements **or** explicit lab waiver,

the intended production condition **cannot be classified as Tier C**.

## Decision

| Item | Status |
| --- | --- |
| `src/morphostack/core/rbc_surfaces.py` | **Not created** |
| `3D_SURFACE_VALIDATED` | **Not enabled** |
| Dimple / rim thickness | **Remain `None`** |

Re-run this assessment when the Phase 5 evidence bundle is accepted.
