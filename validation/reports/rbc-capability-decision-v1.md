# RBC capability decision matrix v1

**Biological validation: false**  
**Date context:** Phase 5 infrastructure committed without lab stacks.

## Matrix

| Capability | Engineering (Phases 1–4) | Biological / product promotion | Evidence link |
| --- | --- | --- | --- |
| Seed + calibration refusal gates | Available | Available as engineering honesty | Phase 1 tests |
| Topology-preserving occupancy | Available | Not biologically certified | Phase 2 tests + phantoms |
| Projected 2D morphometry (L, W, EI_static) | Available when calibrated 2D | **WITHHELD as lab-validated** until real-stack gates | Phase 3 metrics; real-stack pending |
| 3D occupancy volume / SA | Available only under engineering QC `3D_OCCUPANCY_VALIDATED` | **WITHHELD as lab-validated** | Phase 3–4; real-stack pending |
| Estimated biconcave model | Plumbing only | **WITHHELD** | `rbc-estimator-validation-v1.md` |
| Upper/lower surfaces & thickness | Not implemented | **WITHHELD** (not Tier C) | `rbc-acquisition-tier-assessment-v1.md` |

## Lab inputs still required

See `validation/protocols/rbc-real-stack-validation-v1.md` required input bundle.

## Defaults in software

- Production estimator registry: **empty**
- UI estimate action: **disabled** with disclaimer
- Dimple/rim thickness fields: **null**
- Documentation: distinguish engineering completion from biological validation

## Sign-off

| Role | Status |
| --- | --- |
| Software engineering baseline | Complete (Phases 1–4) |
| Lab biological acceptance | **Pending** |
