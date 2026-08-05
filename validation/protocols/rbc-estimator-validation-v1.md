# RBC estimated-model validation protocol v1

**Status:** **WITHHELD** — no lab-approved formula addendum registered for production.

## Prerequisites

1. Phase 4 `RbcEstimator` protocol and empty production registry.
2. Research addendum with: complete formula, parameter units, fitting inputs, uncertainty, failure conditions, primary citations.
3. Lab approval of scientific assumptions and acceptance gates.

## Current decision

| Item | Status |
| --- | --- |
| Production provider registered | **No** (`get_production_estimator() is None`) |
| Model ID / version | n/a |
| API `/rbc/estimate` | 409 `rbc_estimator_not_validated` |
| Synthetic-only formula | **Rejected** — Phase 5 forbids inventing coefficients |

## When a provider may be registered

- Addendum committed under `researches/rbc-estimated-model-addendum.md` (or linked path).
- `tests/test_rbc_estimator_model.py` pass against addendum reference geometries.
- Real-stack bias report under `validation/runs/rbc-estimator-v1/` reviewed by lab.
- Explicit lab sign-off recorded in `validation/reports/rbc-estimator-validation-v1.md`.

Until then: **do not** call `register_production_estimator` from application startup.
