# Phase 5: RBC Evidence-Dependent Validation and Surface Refinement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` only after the prerequisites below are present. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide, from real Zeiss data and instrument evidence, which RBC capabilities can be presented as biologically validated and whether a production estimated model or upper/lower surface refinement is supportable.

**Architecture:** Keep Phases 1-4 unchanged as the engineering baseline. Add datasets, protocols, and algorithms only through versioned validation artifacts; capability promotion is an evidence decision, and failure leaves the capability withheld rather than forcing a release.

**Tech Stack:** Existing MorphoStack validation framework, NumPy/SciPy/scikit-image, versioned JSON/CSV/Markdown reports, annotated TIFF/OME-TIFF stacks, microscope calibration records.

## Global Constraints

- This packet owns the approximately 30% that cannot be completed honestly from synthetic data alone.
- Do not start until the required input bundle is available.
- Raw stacks and annotations are immutable evidence; derived masks and meshes record source hashes.
- A failed validation is a valid outcome and must keep the affected capability withheld.
- Do not tune and evaluate on the same cells without labeling the split.
- The lab, not the software agent, approves biological acceptance thresholds and the production estimator's scientific assumptions.

## Required Input Bundle

- At least three representative, complete Zeiss RBC Z-stacks spanning the acquisition conditions intended for use.
- Verified X/Y/Z spacing and acquisition records for objective, numerical aperture, immersion medium, excitation/emission wavelengths, pinhole, and Z step.
- Ten to twenty representative annotated slices covering center, rim, cap, low-signal, and difficult-boundary cases; two blinded annotators are preferred when available.
- A written note identifying preparation conditions and any known morphology classes or artifacts.
- Bead/PSF measurements or an explicit lab decision that surface/thickness capability remains unavailable without them.
- A deep-research addendum for the estimated biconcave model that specifies formula, parameter units, fitting inputs, uncertainty, failure conditions, and primary citations.

---

## File Structure

- Store immutable accepted inputs or references under `validation/data/rbc/` according to repository size and privacy rules.
- Create `validation/protocols/rbc-real-stack-validation-v1.md` for dataset split, metrics, adjudication, and lab-approved gates.
- Create `validation/references/rbc-annotations-v1/` for masks/contours plus source hashes and annotator metadata.
- Create `scripts/validate_rbc_real_stacks.py` for repeatable evaluation.
- Create versioned outputs under `validation/runs/rbc-real-v1/` and a summary under `validation/reports/`.
- Add a production estimator module only after its model contract passes Task 3.
- Add upper/lower surface code only after acquisition tier assessment passes Task 4.

---

### Task 1: Register and quality-check the lab evidence bundle

**Files:**

- Create: `validation/protocols/rbc-real-stack-validation-v1.md`
- Create: `validation/references/rbc-annotations-v1/manifest.json`
- Create: `scripts/validate_rbc_evidence_bundle.py`
- Test: `tests/test_rbc_validation_bundle.py`

**Interfaces:**

- Produces: a versioned evidence manifest with source hashes, calibration, acquisition metadata, annotation coverage, preparation notes, and train/tune/evaluate assignment.

- [ ] **Step 1: Write failing manifest validation tests**

```python
def test_bundle_rejects_missing_axis_calibration(tmp_path):
    result = validate_rbc_evidence_bundle(bundle_without_z_spacing(tmp_path))
    assert not result.accepted
    assert "missing_verified_z_calibration" in result.reasons


def test_bundle_requires_center_rim_and_cap_annotations(tmp_path):
    result = validate_rbc_evidence_bundle(center_only_bundle(tmp_path))
    assert not result.accepted
    assert "annotation_coverage_incomplete" in result.reasons
```

- [ ] **Step 2: Run bundle tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_rbc_validation_bundle.py -q`

Expected: collection fails because the evidence validator does not exist.

- [ ] **Step 3: Implement deterministic evidence checks**

Require every manifest field listed in the input bundle, verify source hashes, reject overlapping tune/evaluate cell IDs, and validate annotation-to-source dimensions and calibration. The validator must not infer missing acquisition metadata.

- [ ] **Step 4: Run the evidence validator**

```powershell
.\.venv\Scripts\pytest tests\test_rbc_validation_bundle.py -q
.\.venv\Scripts\python scripts\validate_rbc_evidence_bundle.py validation/references/rbc-annotations-v1/manifest.json
```

Expected: the bundle is either accepted with a complete report or refused with exact missing items.

- [ ] **Step 5: Commit the protocol and accepted manifest**

```powershell
git add validation/protocols/rbc-real-stack-validation-v1.md validation/references/rbc-annotations-v1/manifest.json scripts/validate_rbc_evidence_bundle.py tests/test_rbc_validation_bundle.py
git commit -m "validation: register RBC lab evidence"
```

---

### Task 2: Benchmark segmentation, topology, and morphometry

**Files:**

- Create: `scripts/validate_rbc_real_stacks.py`
- Create: `validation/runs/rbc-real-v1/metrics.csv`
- Create: `validation/runs/rbc-real-v1/manifest.json`
- Create: `validation/reports/rbc-real-stack-validation-v1.md`
- Test: `tests/test_rbc_real_validation.py`

**Interfaces:**

- Produces per-cell and aggregate Dice, IoU, average symmetric surface distance, HD95, topology errors, gap/merge events, volume and surface bias where references exist, repeatability, and capability pass/withhold decisions.

- [ ] **Step 1: Write failing metric-completeness tests**

```python
def test_real_validation_report_contains_required_metric_families(tmp_path, accepted_bundle):
    report = run_rbc_real_validation(accepted_bundle, output_dir=tmp_path)
    assert set(report.metric_families) == {
        "segmentation", "surface_distance", "topology", "z_linking",
        "morphometry", "repeatability", "capability_decision",
    }
```

- [ ] **Step 2: Run validation tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_rbc_real_validation.py -q`

Expected: collection fails because the real-stack runner does not exist.

- [ ] **Step 3: Implement blinded evaluation and adjudication inputs**

Run the frozen Phase 4 engineering configuration on evaluation cells. Compare predictions with each annotator separately and with the adjudicated reference. Record threshold sensitivity and result changes across repeated runs. The protocol must record lab-approved acceptance thresholds before the final capability decision is generated; changing a threshold creates protocol version 2 instead of rewriting version 1.

- [ ] **Step 4: Execute the real-stack validation**

```powershell
.\.venv\Scripts\pytest tests\test_rbc_real_validation.py -q
.\.venv\Scripts\python scripts\validate_rbc_real_stacks.py --protocol validation/protocols/rbc-real-stack-validation-v1.md --output validation/runs/rbc-real-v1
```

Expected: a reproducible report names each passed and withheld capability; no aggregate score hides a critical topology failure.

- [ ] **Step 5: Commit the validation evidence**

```powershell
git add scripts/validate_rbc_real_stacks.py validation/runs/rbc-real-v1 validation/reports/rbc-real-stack-validation-v1.md tests/test_rbc_real_validation.py
git commit -m "validation: benchmark RBC reconstruction on lab stacks"
```

---

### Task 3: Select and validate the production estimated model

**Files:**

- Create: `researches/rbc-estimated-model-addendum.md`
- Create: `validation/protocols/rbc-estimator-validation-v1.md`
- Create: `src/morphostack/core/rbc_estimator_validated.py`
- Modify: `src/morphostack/core/rbc_estimation.py`
- Create: `tests/test_rbc_estimator_model.py`
- Create: `validation/reports/rbc-estimator-validation-v1.md`

**Interfaces:**

- Consumes: the Phase 4 `RbcEstimator` protocol and the lab-approved research addendum.
- Produces: one registered provider with fixed model ID/version, explicit parameter units, applicability limits, uncertainty output, and rejection conditions.

- [ ] **Step 1: Review the research addendum against the provider contract**

Reject the addendum if it lacks a complete formula, parameter units, fitting inputs, uncertainty, failure conditions, or primary citations. Do not choose coefficients from memory or from the synthetic phantom generator.

- [ ] **Step 2: Write model-specific failing tests from the accepted formula**

Tests must reproduce at least two published or addendum-provided reference geometries, verify unit scaling, reject inputs outside the stated domain, and confirm every output remains `ESTIMATED`.

- [ ] **Step 3: Implement the approved provider**

Implement only the accepted formula and fitting procedure. Record all fixed priors and fitted parameters in `RbcEstimatedOutput`; do not use hidden defaults.

- [ ] **Step 4: Run estimator validation**

```powershell
.\.venv\Scripts\pytest tests\test_rbc_estimation.py tests\test_rbc_estimator_model.py -q
.\.venv\Scripts\python scripts\validate_rbc_real_stacks.py --protocol validation/protocols/rbc-estimator-validation-v1.md --output validation/runs/rbc-estimator-v1
```

Expected: the provider passes its formula/reference tests and the report states bias and applicability; otherwise production registration remains empty.

- [ ] **Step 5: Commit only an approved provider**

```powershell
git add researches/rbc-estimated-model-addendum.md validation/protocols/rbc-estimator-validation-v1.md src/morphostack/core/rbc_estimation.py src/morphostack/core/rbc_estimator_validated.py tests/test_rbc_estimator_model.py validation/reports/rbc-estimator-validation-v1.md
git commit -m "feat: add validated estimated RBC model"
```

If validation fails, commit the protocol and report without registering the provider; use commit message `validation: withhold estimated RBC model`.

---

### Task 4: Decide whether upper/lower surface refinement is supportable

**Files:**

- Create: `validation/reports/rbc-acquisition-tier-assessment-v1.md`
- Create only after a Tier-C pass: `src/morphostack/core/rbc_surfaces.py`
- Create only after a Tier-C pass: `tests/test_rbc_surfaces.py`
- Modify only after a Tier-C pass: `src/morphostack/core/rbc_qc.py`
- Modify only after a Tier-C pass: `src/morphostack/core/rbc_metrics.py`

**Interfaces:**

- Produces either a documented Tier-B ceiling or `reconstruct_rbc_surfaces(occupancy, intensity, voxel, psf) -> RbcSurfacePair` with validated upper/lower surfaces.

- [ ] **Step 1: Classify acquisition support**

Use Z sampling, lateral sampling, SBR, saturation, cap coverage, membrane separation, refractive-index information, and bead/PSF evidence to classify each acquisition condition. If the intended condition is not Tier C, stop this task after committing the assessment and keep surface/thickness capability unavailable.

- [ ] **Step 2: For Tier-C data, write failing synthetic and annotated-surface tests**

Cover tilted cells, dimple/rim thickness recovery, missing cap signal, asymmetric noise, and top/bottom crossing rejection. The tests must compare surfaces in physical coordinates and reject self-intersection.

- [ ] **Step 3: Implement separate upper and lower surfaces**

Fit surfaces only inside the accepted footprint, preserve anisotropic coordinates, enforce upper-above-lower ordering, and retain unsmoothed measurement authority. Store smoothing only as display metadata.

- [ ] **Step 4: Validate thickness and biconcavity outputs**

Run synthetic tests plus the lab protocol. Enable `3D_SURFACE_VALIDATED`, central dimple thickness, rim thickness, and the documented thickness ratio only when their acceptance gates pass.

- [ ] **Step 5: Commit the evidence-based outcome**

Commit either the assessment that keeps Tier C withheld or the validated implementation plus tests and report. Do not merge a partially passing surface implementation behind the normal RBC profile.

---

### Task 5: Make the biological capability decision

**Files:**

- Modify: `docs/limitations.md`
- Modify: `docs/metrics.md`
- Modify: `docs/usage.md`
- Modify: `improvements.md`
- Create: `validation/reports/rbc-capability-decision-v1.md`

**Interfaces:**

- Consumes: Tasks 1-4 reports.
- Produces: a capability matrix naming which acquisition conditions support 2D, occupancy, surface, or estimated outputs and which remain withheld.

- [ ] **Step 1: Assemble the evidence matrix**

For every capability and acquisition condition, link the protocol, dataset manifest, run manifest, metrics, failure cases, and lab approval. A missing evidence link means `WITHHELD`.

- [ ] **Step 2: Review claims with the lab**

Record the lab's approval or rejection in the versioned decision report. Do not translate exploratory agreement into a paper-use claim.

- [ ] **Step 3: Update capability defaults and documentation**

Enable only approved capabilities. Keep failed or untested capabilities behind the existing withholding reasons. State preparation and acquisition limits in user docs.

- [ ] **Step 4: Run the full release evidence gate**

```powershell
.\.venv\Scripts\pytest
.\.venv\Scripts\python scripts\validate_rbc_phantoms.py
.\.venv\Scripts\python scripts\validate_rbc_real_stacks.py --protocol validation/protocols/rbc-real-stack-validation-v1.md --output validation/runs/rbc-real-v1
cd apps\web
npm run build
```

Expected: engineering and approved biological gates pass; unavailable capabilities remain explicitly withheld.

- [ ] **Step 5: Commit the capability decision**

```powershell
git add docs/limitations.md docs/metrics.md docs/usage.md improvements.md validation/reports/rbc-capability-decision-v1.md
git commit -m "docs: record validated RBC capability limits"
```

---

## Phase 5 Exit Gate

- The evidence bundle is complete, hashed, calibrated, and separated into tuning/evaluation cells.
- Real-stack reports include segmentation, surface-distance, topology, Z-linking, morphometry, repeatability, and capability decisions.
- The estimator is either validated and registered or explicitly withheld.
- Upper/lower surfaces are either Tier-C validated or explicitly withheld.
- Documentation and defaults match the evidence matrix.
- No biological claim depends only on synthetic data or visual plausibility.
